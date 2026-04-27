"""测试 ``src.llm_tools.cli`` 的 P3 ``rate-images`` 子命令 + ``via_skill`` kwarg。

涵盖 ≥ 5 条:
1. ``test_cli_rate_images_mock_opencode`` — mock subprocess 返回 fake JSON,
   验证 out 文件 schema 正确
2. ``test_formula_image_auto_low_score`` — caption 含 "Equation"/"公式" 时,
   断言 score ≤ 3 + recommended_section="none"(双重保险)
3. ``test_via_skill_kwarg_default_off`` — ``via_skill=False`` 默认不走 subprocess
4. ``test_via_skill_env_var_triggered`` — ``JSR_USE_SKILL_RATE_IMAGES=1`` 走 subprocess
5. ``test_skill_failure_falls_back_to_original`` — mock subprocess timeout → fallback

补充:
- ``test_cli_missing_candidates_returns_error`` — 候选文件不存在 → ok=false / rc=1
- ``test_cli_invalid_candidates_format_returns_error`` — 候选不是 list → ok=false
- ``test_cli_empty_candidates_returns_empty`` — 空 list → ok=true scored=0
- ``test_normalize_score_record_clamps_score`` — score > 10 / < 0 / 非 numeric 都被夹钳
- ``test_parse_rate_images_json_variants`` — 各种 JSON 包裹形态都能解析
- ``test_is_formula_caption_keywords`` — 公式关键词判断
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

def _make_candidates(tmp_path) -> str:
    """3 张测试图: 架构 / 公式 / 实验结果。"""
    p = tmp_path / "candidates.json"
    cands = [
        {
            "image_index": 0,
            "caption": "Figure 1: Overall architecture of ViTacFormer with cross-modal fusion",
            "figure_role": "method",
            "paper_context": "ViTacFormer",
        },
        {
            "image_index": 1,
            "caption": "Equation 3: Cross-attention loss function L_attn = ...",
            "figure_role": "method",
            "paper_context": "ViTacFormer",
        },
        {
            "image_index": 2,
            "caption": "Figure 4: Quantitative comparison on dexterous manipulation benchmarks",
            "figure_role": "results",
            "paper_context": "ViTacFormer",
        },
    ]
    p.write_text(json.dumps(cands, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _fake_skill_response(n: int = 3) -> str:
    """模拟 opencode 返回 fenced json,3 张图分别 8.5 / 8.0 / 7.5 分。"""
    payload = [
        {"image_index": 0, "caption": "Figure 1: arch", "score": 8.5,
         "reason": "高层架构", "recommended_section": "method", "rejected": False},
        {"image_index": 1, "caption": "Equation 3", "score": 8.0,
         "reason": "(opencode 给高分,代码层应 enforce 拉到 ≤3)",
         "recommended_section": "method", "rejected": False},
        {"image_index": 2, "caption": "Figure 4: results", "score": 7.5,
         "reason": "实验结果", "recommended_section": "results", "rejected": False},
    ][:n]
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
# 1. mock opencode → CLI 应正确写出 scores
# -----------------------------------------------------------------------------

def test_cli_rate_images_mock_opencode(tmp_path):
    """mock _run_opencode_rate 返回 fake JSON,验证 out 文件 + stdout JSON。"""
    from src.llm_tools import cli as llm_cli

    cand_path = _make_candidates(tmp_path)
    out_path = str(tmp_path / "scores.json")

    fake_raw = _fake_skill_response()
    with patch.object(llm_cli, "_run_opencode_rate", return_value=fake_raw):
        with patch.object(llm_cli, "_resolve_opencode_model",
                           return_value="deepseek/deepseek-v4-pro"):
            rc = llm_cli.main([
                "rate-images",
                "--candidates", cand_path,
                "--target-count", "3",
                "--out", out_path,
            ])
    assert rc == 0, "应成功"
    assert os.path.isfile(out_path)
    with open(out_path, "r", encoding="utf-8") as f:
        scores = json.load(f)
    assert isinstance(scores, list) and len(scores) == 3
    for s in scores:
        assert "image_index" in s
        assert "score" in s
        assert "recommended_section" in s
        assert s["recommended_section"] in (
            "opening", "intro", "method", "results", "none"
        )


# -----------------------------------------------------------------------------
# 2. 公式图自动降权(双重保险)
# -----------------------------------------------------------------------------

def test_formula_image_auto_low_score(tmp_path):
    """caption 含 Equation/公式 关键词时,即使 opencode 给高分,代码层应 enforce ≤ 3。"""
    from src.llm_tools import cli as llm_cli

    cand_path = _make_candidates(tmp_path)
    out_path = str(tmp_path / "scores.json")

    # opencode 故意给公式图(idx=1) 8.0 分 + section=method, 看代码层是否拉回
    fake_raw = _fake_skill_response()
    with patch.object(llm_cli, "_run_opencode_rate", return_value=fake_raw):
        with patch.object(llm_cli, "_resolve_opencode_model",
                           return_value="deepseek/deepseek-v4-pro"):
            rc = llm_cli.main([
                "rate-images",
                "--candidates", cand_path,
                "--out", out_path,
            ])
    assert rc == 0
    with open(out_path, "r", encoding="utf-8") as f:
        scores = json.load(f)
    formula_rec = next(s for s in scores if s["image_index"] == 1)
    assert formula_rec["score"] <= 3, f"公式图应被 enforce 拉到 ≤3,实际 {formula_rec['score']}"
    assert formula_rec["recommended_section"] == "none", (
        f"公式图 section 应为 none,实际 {formula_rec['recommended_section']}"
    )
    assert formula_rec["rejected"] is True


def test_is_formula_caption_keywords():
    """_is_formula_caption 应识别中英文关键词。"""
    from src.llm_tools.cli import _is_formula_caption

    assert _is_formula_caption("Equation 3: L_attn = sum...")
    assert _is_formula_caption("Figure 5: Loss function visualization")
    assert _is_formula_caption("公式 (3): L = ...")
    assert _is_formula_caption("目标函数定义如下...")
    assert _is_formula_caption("Theorem 1: convergence")
    # 非公式
    assert not _is_formula_caption("Figure 1: Overall architecture")
    assert not _is_formula_caption("")
    assert not _is_formula_caption(None)


# -----------------------------------------------------------------------------
# 3. via_skill=False 默认不调 subprocess
# -----------------------------------------------------------------------------

def test_via_skill_kwarg_default_off(monkeypatch):
    """默认 via_skill=False 且 JSR_USE_SKILL_RATE_IMAGES 未设 → 不应调 _call_image_rating_skill。"""
    monkeypatch.delenv("JSR_USE_SKILL_RATE_IMAGES", raising=False)

    from src.llm_tools import llm_agent

    skill_called = {"v": False}

    def _spy_skill(*args, **kw):
        skill_called["v"] = True
        return [9, 9, 9]

    fake_response = json.dumps({"scores": [7, 6, 5]})

    with patch.object(llm_agent, "_call_image_rating_skill", side_effect=_spy_skill):
        with patch.object(llm_agent, "create_chat_completion",
                           return_value=fake_response):
            scores = llm_agent.rate_image_importance(
                ["arch", "loss", "results"]
            )
    assert skill_called["v"] is False, "默认不应触发 skill 路径"
    assert scores == [7, 6, 5]


# -----------------------------------------------------------------------------
# 4. JSR_USE_SKILL_RATE_IMAGES=1 触发 skill
# -----------------------------------------------------------------------------

def test_via_skill_env_var_triggered(monkeypatch):
    """设 JSR_USE_SKILL_RATE_IMAGES=1 后,_call_image_rating_skill 应被调用。"""
    monkeypatch.setenv("JSR_USE_SKILL_RATE_IMAGES", "1")

    from src.llm_tools import llm_agent

    fake_skill_scores = [8, 3, 7]
    with patch.object(llm_agent, "_call_image_rating_skill",
                       return_value=fake_skill_scores) as m_skill:
        with patch.object(llm_agent, "create_chat_completion",
                           return_value=json.dumps({"scores": [5, 5, 5]})):
            scores = llm_agent.rate_image_importance(
                ["arch", "Equation 3", "results"]
            )
    assert m_skill.called, "env=1 时应触发 skill 路径"
    assert scores == [8, 3, 7]


# -----------------------------------------------------------------------------
# 5. skill 失败时 fallback 原 LLM 路径
# -----------------------------------------------------------------------------

def test_skill_failure_falls_back_to_original():
    """mock subprocess.run 抛 TimeoutExpired,断言 _call_image_rating_skill 返回空列表;
    上层 rate_image_importance(via_skill=True) 应自动 fallback 到原 LLM 路径。"""
    from src.llm_tools import llm_agent

    # _call_image_rating_skill 内部 subprocess 模拟 timeout → 应返回 []
    with patch("subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)):
        skill_out = llm_agent._call_image_rating_skill(
            ["arch", "loss", "results"]
        )
    assert skill_out == [], "skill 失败应返回空列表让上层 fallback"

    # 上层 rate_image_importance(via_skill=True) 应 fallback 走原 LLM
    fake_response = json.dumps({"scores": [9, 4, 8]})
    with patch.object(llm_agent, "_call_image_rating_skill", return_value=[]):
        with patch.object(llm_agent, "create_chat_completion",
                           return_value=fake_response):
            scores = llm_agent.rate_image_importance(
                ["arch", "loss", "results"], via_skill=True
            )
    assert scores == [9, 4, 8]


# -----------------------------------------------------------------------------
# 补充 CLI 边界
# -----------------------------------------------------------------------------

def test_cli_missing_candidates_returns_error(tmp_path):
    """候选文件不存在 → exit 1, ok=false。"""
    rc, out, err = _run_cli(
        "rate-images",
        "--candidates", str(tmp_path / "does_not_exist.json"),
        "--out", str(tmp_path / "scores.json"),
        timeout=15,
    )
    assert rc == 1
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "error" in payload


def test_cli_invalid_candidates_format_returns_error(tmp_path):
    """候选不是 JSON list → exit 1, ok=false。"""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    rc, out, err = _run_cli(
        "rate-images",
        "--candidates", str(bad),
        "--out", str(tmp_path / "scores.json"),
        timeout=15,
    )
    assert rc == 1
    payload = json.loads(out)
    assert payload["ok"] is False


def test_cli_empty_candidates_returns_empty(tmp_path):
    """空 list → ok=true scored=0。"""
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    out_path = str(tmp_path / "scores.json")
    rc, out, err = _run_cli(
        "rate-images",
        "--candidates", str(empty),
        "--out", out_path,
        timeout=15,
    )
    assert rc == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["scored"] == 0
    assert payload["above_5"] == 0
    with open(out_path, "r", encoding="utf-8") as f:
        scores = json.load(f)
    assert scores == []


# -----------------------------------------------------------------------------
# 内部 helpers 单测
# -----------------------------------------------------------------------------

def test_normalize_score_record_clamps_score():
    """score > 10 / < 0 / 非 numeric 都被夹钳到 0-10。"""
    from src.llm_tools.cli import _normalize_score_record

    rec = _normalize_score_record(
        {"image_index": 0, "score": 99, "caption": "x"},
        {"image_index": 0},
    )
    assert rec["score"] == 10.0

    rec = _normalize_score_record(
        {"image_index": 1, "score": -5, "caption": "y"},
        {"image_index": 1},
    )
    assert rec["score"] == 0.0

    rec = _normalize_score_record(
        {"image_index": 2, "score": "not a number"},
        {"image_index": 2, "caption": "z"},
    )
    assert rec["score"] == 5.0  # 默认
    assert rec["caption"] == "z"

    # 非法 section → 兜底 method
    rec = _normalize_score_record(
        {"image_index": 3, "score": 7, "recommended_section": "xxx"},
        {"image_index": 3},
    )
    assert rec["recommended_section"] == "method"


def test_parse_rate_images_json_variants():
    """各种 JSON 包裹格式应能解析。"""
    from src.llm_tools.cli import _parse_rate_images_json

    arr = [{"image_index": 0, "score": 8}]
    raw1 = "```json\n" + json.dumps(arr) + "\n```"
    raw2 = "```\n" + json.dumps(arr) + "\n```"
    raw3 = "Some prefix\n" + json.dumps(arr) + "\nSome suffix"
    for raw in (raw1, raw2, raw3):
        out = _parse_rate_images_json(raw)
        assert isinstance(out, list), f"failed on raw: {raw[:80]!r}"
        assert out[0]["image_index"] == 0
    assert _parse_rate_images_json("") is None
    assert _parse_rate_images_json("not json at all") is None


def test_enforce_formula_constraint_double_safety():
    """即使 record 本身 score 高 + section=method, 命中关键词后必须被拉低。"""
    from src.llm_tools.cli import _enforce_formula_constraint

    rec = {
        "image_index": 1,
        "caption": "Equation 3: loss function",
        "score": 9.0,
        "recommended_section": "method",
        "rejected": False,
        "reason": "",
    }
    out = _enforce_formula_constraint(rec, {"caption": "Equation 3: loss function"})
    assert out["score"] <= 3.0
    assert out["recommended_section"] == "none"
    assert out["rejected"] is True
    assert out["reason"]  # 应自动填理由
