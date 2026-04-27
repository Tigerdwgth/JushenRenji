"""测试 ``src.llm_tools.cli`` 的 P4 ``title-cn`` 子命令 + ``via_skill`` kwarg。

涵盖 ≥ 5 条:
1. ``test_cli_title_cn_mock_opencode`` — mock subprocess 返回 fake JSON,
   断言 cn_title 字段 + out 文件 schema
2. ``test_max_len_constraint`` — mock 返回超长标题 → 自动截断到 max_len
3. ``test_via_skill_kwarg_default_off`` — 默认 ``via_skill=False`` 不调 subprocess
4. ``test_via_skill_env_var_triggered`` — ``JSR_USE_SKILL_TITLE_CN=1`` 走 subprocess
5. ``test_skill_failure_falls_back`` — mock subprocess timeout → fallback 原 LLM 路径

补充:
- ``test_cli_empty_en_title_returns_error`` — 空 en_title → ok=false / rc=1
- ``test_extract_proper_noun_camel_case`` — CamelCase / ALLCAPS / 数字 都能识别
- ``test_extract_proper_noun_no_match`` — 无专有名词时返回空串
- ``test_enforce_max_len_truncates_long`` — 标题超 max_len 自动截断
- ``test_ensure_proper_noun_inserts_when_missing`` — 中文标题缺英文名 → 自动插入
- ``test_normalize_title_record_full_pipeline`` — 完整 normalize: sanitize + ensure + enforce
- ``test_parse_title_cn_json_variants`` — 各种 JSON 包裹形态都能解析
- ``test_sanitize_removes_exaggerated_words`` — "突破/震撼/颠覆" 被去除
- ``test_fallback_default_title_uses_proper_noun`` — 全失败时启发式标题含专有名词
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------

def _fake_skill_response(cn_title: str = "ViTacFormer: 手眼触觉融合做灵巧操作",
                         candidates=None, reason: str = "保留专有名词 + 动词",
                         char_count: int = None) -> str:
    """模拟 opencode 返回 fenced json。"""
    if candidates is None:
        candidates = [cn_title, "ViTacFormer: 视触觉融合驱动灵巧操作"]
    if char_count is None:
        char_count = len(cn_title)
    payload = {
        "cn_title": cn_title,
        "candidates": candidates,
        "reason": reason,
        "char_count": char_count,
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _run_cli(*args, timeout=60):
    cmd = [sys.executable, "-m", "src.llm_tools.cli", *args]
    env = os.environ.copy()
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True,
        env=env, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


# -----------------------------------------------------------------------------
# 1. mock opencode → CLI 应正确写出 cn_title
# -----------------------------------------------------------------------------

def test_cli_title_cn_mock_opencode(tmp_path):
    """mock _run_opencode_title 返回 fake JSON, 验证 out 文件 + stdout JSON。"""
    from src.llm_tools import cli as llm_cli

    out_path = str(tmp_path / "title.json")
    fake_raw = _fake_skill_response()

    with patch.object(llm_cli, "_run_opencode_title", return_value=fake_raw):
        with patch.object(llm_cli, "_resolve_opencode_model",
                           return_value="deepseek/deepseek-v4-pro"):
            rc = llm_cli.main([
                "title-cn",
                "--en-title", "ViTacFormer: Learning Cross-Modal Representation",
                "--abstract", "We propose ViTacFormer, a cross-modal transformer...",
                "--out", out_path,
                "--max-len", "20",
            ])
    assert rc == 0
    assert os.path.isfile(out_path)
    with open(out_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    assert "cn_title" in result
    assert "ViTacFormer" in result["cn_title"]
    assert "candidates" in result and isinstance(result["candidates"], list)
    assert "char_count" in result
    assert result["char_count"] == len(result["cn_title"])
    assert len(result["cn_title"]) <= 20


# -----------------------------------------------------------------------------
# 2. max_len 约束 — 超长标题自动截断
# -----------------------------------------------------------------------------

def test_max_len_constraint(tmp_path):
    """mock 返回 25 字标题, max_len=20 时应自动截到 20 字。"""
    from src.llm_tools import cli as llm_cli

    long_title = "ViTacFormer: 跨模态注意力视触觉融合做精细灵巧操作机器人解读"
    assert len(long_title) > 20

    fake_raw = _fake_skill_response(cn_title=long_title, char_count=len(long_title))
    out_path = str(tmp_path / "title.json")

    with patch.object(llm_cli, "_run_opencode_title", return_value=fake_raw):
        with patch.object(llm_cli, "_resolve_opencode_model",
                           return_value="deepseek/deepseek-v4-pro"):
            rc = llm_cli.main([
                "title-cn",
                "--en-title", "ViTacFormer: paper",
                "--out", out_path,
                "--max-len", "20",
            ])
    assert rc == 0
    with open(out_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    assert len(result["cn_title"]) <= 20, (
        "应被 enforce 截到 ≤ 20 字, 实际 %d 字: %s"
        % (len(result["cn_title"]), result["cn_title"])
    )
    # 截断后仍含 ViTacFormer
    assert "ViTacFormer" in result["cn_title"] or "ViTac" in result["cn_title"]


# -----------------------------------------------------------------------------
# 3. via_skill=False 默认不调 subprocess
# -----------------------------------------------------------------------------

def test_via_skill_kwarg_default_off(monkeypatch):
    """默认 via_skill=False 且 JSR_USE_SKILL_TITLE_CN 未设 → 不应调 _call_title_cn_skill。"""
    monkeypatch.delenv("JSR_USE_SKILL_TITLE_CN", raising=False)

    from src.llm_tools import llm_agent

    skill_called = {"v": False}

    def _spy_skill(*args, **kw):
        skill_called["v"] = True
        return "skill 路径不应被调"

    fake_response = "ViTacFormer: 跨模态融合学习机器人灵巧操作"
    with patch.object(llm_agent, "_call_title_cn_skill", side_effect=_spy_skill):
        with patch.object(llm_agent, "create_chat_completion",
                           return_value=fake_response):
            cn = llm_agent.generate_video_title("ViTacFormer paper text")
    assert skill_called["v"] is False, "默认不应触发 skill 路径"
    assert "ViTacFormer" in cn


# -----------------------------------------------------------------------------
# 4. JSR_USE_SKILL_TITLE_CN=1 触发 skill
# -----------------------------------------------------------------------------

def test_via_skill_env_var_triggered(monkeypatch):
    """设 JSR_USE_SKILL_TITLE_CN=1 后, _call_title_cn_skill 应被调用。"""
    monkeypatch.setenv("JSR_USE_SKILL_TITLE_CN", "1")

    from src.llm_tools import llm_agent

    fake_skill_title = "ViTacFormer: 手眼触觉融合做灵巧操作"
    with patch.object(llm_agent, "_call_title_cn_skill",
                       return_value=fake_skill_title) as m_skill:
        with patch.object(llm_agent, "create_chat_completion",
                           return_value="不应走到这"):
            cn = llm_agent.generate_video_title(
                text="ViTacFormer paper text",
                paper_title="ViTacFormer: Learning Cross-Modal",
                paper_abstract="We propose ViTacFormer...",
            )
    assert m_skill.called, "env=1 时应触发 skill 路径"
    assert cn == fake_skill_title


# -----------------------------------------------------------------------------
# 5. skill 失败时 fallback 原 LLM 路径
# -----------------------------------------------------------------------------

def test_skill_failure_falls_back():
    """mock subprocess.run 抛 TimeoutExpired, 断言 _call_title_cn_skill 返回空串;
    上层 generate_video_title(via_skill=True) 应自动 fallback 到原 LLM 路径。"""
    from src.llm_tools import llm_agent

    # _call_title_cn_skill 内部 subprocess 模拟 timeout → 应返回 ""
    with patch("subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)):
        skill_out = llm_agent._call_title_cn_skill(
            en_title="ViTacFormer: paper",
            abstract="abc",
        )
    assert skill_out == "", "skill 失败应返回空串让上层 fallback"

    # 上层 generate_video_title(via_skill=True) 应 fallback 走原 LLM
    fake_llm_title = "ViTacFormer: 跨模态融合做灵巧操作"
    with patch.object(llm_agent, "_call_title_cn_skill", return_value=""):
        with patch.object(llm_agent, "create_chat_completion",
                           return_value=fake_llm_title):
            cn = llm_agent.generate_video_title(
                text="ViTacFormer paper text",
                via_skill=True,
                paper_title="ViTacFormer: paper",
                paper_abstract="abc",
            )
    assert "ViTacFormer" in cn


# -----------------------------------------------------------------------------
# 补充 CLI 边界
# -----------------------------------------------------------------------------

def test_cli_empty_en_title_returns_error(tmp_path):
    """空 en_title → exit 1, ok=false。"""
    rc, out, err = _run_cli(
        "title-cn",
        "--en-title", "",
        "--out", str(tmp_path / "title.json"),
        timeout=15,
    )
    assert rc == 1
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "error" in payload


# -----------------------------------------------------------------------------
# 内部 helpers 单测
# -----------------------------------------------------------------------------

def test_extract_proper_noun_camel_case():
    """CamelCase / ALLCAPS / 带数字 / 带连字符 应能识别。"""
    from src.llm_tools.cli import _extract_proper_noun

    assert _extract_proper_noun("ViTacFormer: Learning ...") == "ViTacFormer"
    assert _extract_proper_noun("BESTRO: A Game-Theoretic Framework") == "BESTRO"
    assert _extract_proper_noun("LARY: Latent Action ...") == "LARY"
    # 数字保留 (取冒号前最后一个含大写/数字 token, "FAST π0" → "π0" 是方法本名)
    res_fast = _extract_proper_noun("FAST π0: efficient action tokens")
    assert "π0" in res_fast or "π" in res_fast or "FAST" in res_fast
    # 带连字符
    assert "DeeR-VLA" in _extract_proper_noun(
        "DeeR-VLA: Dynamic Reasoning for Robot Manipulation"
    )


def test_extract_proper_noun_no_match():
    """纯描述性英文标题 (无 CamelCase / ALLCAPS / 数字) 应返回空串。"""
    from src.llm_tools.cli import _extract_proper_noun

    # 全小写描述性标题
    assert _extract_proper_noun("learning to manipulate objects") == ""
    assert _extract_proper_noun("") == ""
    assert _extract_proper_noun(None) == ""


def test_enforce_max_len_truncates_long():
    """超长标题应被截断到 max_len。"""
    from src.llm_tools.cli import _enforce_max_len

    long_title = "ViTacFormer: 跨模态注意力视触觉融合精细灵巧操作机器人解读"
    out = _enforce_max_len(long_title, 20)
    assert len(out) <= 20
    assert "ViTacFormer" in out

    # ≤ max_len 不动
    short = "ViTacFormer: 做灵巧操作"
    assert _enforce_max_len(short, 20) == short

    # 空串安全
    assert _enforce_max_len("", 20) == ""
    assert _enforce_max_len(None, 20) == ""


def test_ensure_proper_noun_inserts_when_missing():
    """中文标题缺英文专有名词 → 自动插入。"""
    from src.llm_tools.cli import _ensure_proper_noun

    cn = "做灵巧操作的机器人"
    en = "ViTacFormer: Learning ..."
    out = _ensure_proper_noun(cn, en)
    assert "ViTacFormer" in out
    assert ":" in out

    # 已含则不改
    cn2 = "ViTacFormer: 做灵巧操作"
    out2 = _ensure_proper_noun(cn2, en)
    assert out2 == cn2

    # en_title 无专有名词 → 不改
    cn3 = "测试标题"
    out3 = _ensure_proper_noun(cn3, "no caps title")
    assert out3 == cn3


def test_normalize_title_record_full_pipeline():
    """sanitize + ensure proper noun + enforce max_len 全流程。"""
    from src.llm_tools.cli import _normalize_title_record

    # 含夸张词 + 缺英文名 + 超长
    rec = {
        "cn_title": "首次突破!跨模态注意力视触觉融合精细灵巧操作技术解读",
        "candidates": ["候选1", "候选2"],
        "reason": "测试",
    }
    en_title = "ViTacFormer: paper"
    out = _normalize_title_record(rec, en_title, max_len=20)
    # 不应再含 "首次"
    assert "首次" not in out["cn_title"]
    assert "突破" not in out["cn_title"]
    # 应含英文名
    assert "ViTacFormer" in out["cn_title"]
    # 字数 ≤ 20
    assert len(out["cn_title"]) <= 20
    # char_count 一致
    assert out["char_count"] == len(out["cn_title"])


def test_parse_title_cn_json_variants():
    """各种 JSON 包裹格式应能解析为 dict。"""
    from src.llm_tools.cli import _parse_title_cn_json

    obj = {"cn_title": "test", "candidates": [], "reason": "", "char_count": 4}
    raw1 = "```json\n" + json.dumps(obj) + "\n```"
    raw2 = "```\n" + json.dumps(obj) + "\n```"
    raw3 = "Some prefix\n" + json.dumps(obj) + "\nSome suffix"
    for raw in (raw1, raw2, raw3):
        out = _parse_title_cn_json(raw)
        assert isinstance(out, dict), f"failed on raw: {raw[:80]!r}"
        assert out["cn_title"] == "test"
    assert _parse_title_cn_json("") is None
    assert _parse_title_cn_json("not json at all") is None
    # list 不应被接受 (要求 dict)
    raw_list = "```json\n[1,2,3]\n```"
    assert _parse_title_cn_json(raw_list) is None


def test_sanitize_removes_exaggerated_words():
    """sanitize 应去除"首次/突破/震撼"等。"""
    from src.llm_tools.cli import _sanitize_title_for_channel

    assert "首次" not in _sanitize_title_for_channel("ViTacFormer: 首次实现做灵巧操作")
    assert "突破" not in _sanitize_title_for_channel("BESTRO: 突破多人博弈学习")
    # 正常标题不应被破坏
    safe = "ViTacFormer: 做灵巧操作"
    out = _sanitize_title_for_channel(safe)
    assert "ViTacFormer" in out


def test_fallback_default_title_uses_proper_noun():
    """全失败时启发式标题应含英文专有名词。"""
    from src.llm_tools.cli import _fallback_default_title

    out = _fallback_default_title(
        "ViTacFormer: Learning Cross-Modal Representation",
        max_len=20,
    )
    assert isinstance(out, dict)
    assert "ViTacFormer" in out["cn_title"]
    assert len(out["cn_title"]) <= 20
    assert out["candidates"] == [out["cn_title"]]
    assert "fallback" in out["reason"].lower()


def test_build_title_cn_prompt_smoke():
    """prompt 构造不崩, 含关键约束。"""
    from src.llm_tools.cli import _build_title_cn_prompt

    p = _build_title_cn_prompt(
        en_title="ViTacFormer: paper title",
        abstract="We propose a method...",
        max_len=20,
    )
    assert "ViTacFormer" in p
    assert "20" in p  # max_len
    assert "频道" in p or "动作" in p  # 风格提示
    # 历史好示例至少出现一个
    assert "BESTRO" in p or "VistaBot" in p
