"""``src.figure_cli`` 单元测试 + ``src.figure_analyzer`` skill 分流测试 (P2)。

测试覆盖:
- CLI mock 3 轮 opencode 调用合并 schema
- CLI 验证子进程被调用 3 次 (不是 1 次)
- ``analyze_figure_with_vision_llm`` 默认 ``via_skill=False``, 不走 subprocess
- ``JSR_USE_SKILL_FIGURE=1`` 时走 subprocess
- skill 失败 fallback 到 Qwen-VL 路径
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from unittest import mock

import pytest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 让 src.figure_cli / src.figure_analyzer 都能 import
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ---------- 通用 fixture ----------

@pytest.fixture
def fake_image(tmp_path):
    """造一个最小 1x1 PNG 让 os.path.exists 为真。"""
    p = tmp_path / "fake.png"
    # 89 50 4E 47 0D 0A 1A 0A: PNG 头, 后面随便, 文件存在即可
    p.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return str(p)


def _fake_proc(stdout="", returncode=0, stderr=""):
    """构造一个 subprocess.CompletedProcess-like 对象。"""
    return subprocess.CompletedProcess(args=["opencode"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# ============================================================
# Test 1: 3 轮 reasoning 合并 schema
# ============================================================

def test_cli_analyze_figure_mock_opencode(fake_image, tmp_path):
    """mock opencode 3 轮返回合理 fake JSON, 断言合并后 schema 正确。"""
    from src import figure_cli

    out_path = str(tmp_path / "analysis.json")

    fake_responses = [
        # round 1: components
        '```json\n['
        '{"name": "Encoder", "chinese_name": "编码器", "type": "module", "description": "提取特征"},'
        '{"name": "Decoder", "chinese_name": "解码器", "type": "module", "description": "生成输出"}'
        ']\n```',
        # round 2: connections
        '```json\n['
        '{"from": "Encoder", "to": "Decoder", "label": "z", "type": "arrow", "description": "潜变量传递"}'
        ']\n```',
        # round 3: high-level
        '```json\n{'
        '"figure_type": "architecture", "layout_direction": "left-to-right",'
        '"key_innovation": "跨模态融合", "data_flow": "输入->编码->解码->输出",'
        '"animation_suggestion": "依次淡入", "has_neural_network": true,'
        '"nn_layers": ["transformer"]'
        '}\n```',
    ]
    call_args = []

    def fake_run_round(prompt, model, timeout=180):
        call_args.append(prompt)
        return fake_responses[len(call_args) - 1]

    with mock.patch.object(figure_cli, "_run_opencode_round",
                            side_effect=fake_run_round):
        rc = figure_cli.main([
            "analyze-figure",
            "--image", fake_image,
            "--paper-context", "test paper",
            "--out", out_path,
        ])
    assert rc == 0, "CLI should exit 0"
    assert os.path.exists(out_path)
    with open(out_path, encoding="utf-8") as f:
        data = json.load(f)
    # schema 兼容性断言
    assert data["figure_type"] == "architecture"
    assert data["layout_direction"] == "left-to-right"
    assert data["source"] == "vision_skill"
    assert data["has_precise_bbox"] is False
    assert isinstance(data["components"], list) and len(data["components"]) == 2
    assert data["components"][0]["name"] == "Encoder"
    assert data["components"][0]["chinese_name"] == "编码器"
    # 兜底字段被填进去
    assert data["components"][0]["position"] == "center"
    assert data["components"][0]["shape"] == "rectangle"
    assert isinstance(data["connections"], list) and len(data["connections"]) == 1
    assert data["connections"][0]["from"] == "Encoder"
    assert data["connections"][0]["to"] == "Decoder"
    assert data["key_innovation"] == "跨模态融合"
    assert data["has_neural_network"] is True
    assert "transformer" in data["nn_layers"]


# ============================================================
# Test 2: 3 轮调用次数验证
# ============================================================

def test_cli_3_round_reasoning_calls_opencode_3_times(fake_image, tmp_path):
    """mock subprocess, 断言 _run_opencode_round 被调用 3 次, 不是 1 次。"""
    from src import figure_cli

    out_path = str(tmp_path / "analysis.json")

    counter = {"n": 0}
    fake_responses = [
        '[{"name": "M1", "type": "module"}]',
        '[{"from": "M1", "to": "M1", "label": "self", "type": "arrow"}]',
        '{"figure_type": "pipeline", "layout_direction": "top-to-bottom"}',
    ]

    def fake_round(prompt, model, timeout=180):
        idx = counter["n"]
        counter["n"] += 1
        return fake_responses[idx] if idx < len(fake_responses) else ""

    with mock.patch.object(figure_cli, "_run_opencode_round",
                            side_effect=fake_round):
        rc = figure_cli.main([
            "analyze-figure",
            "--image", fake_image,
            "--paper-context", "x",
            "--out", out_path,
        ])
    assert rc == 0
    assert counter["n"] == 3, "应调 opencode 3 次 (而不是 1 次)"


# ============================================================
# Test 3: via_skill 默认 False, 不走 subprocess
# ============================================================

def test_via_skill_kwarg_default_off(fake_image, monkeypatch):
    """analyze_figure_with_vision_llm 默认不调 _call_figure_skill。"""
    monkeypatch.delenv("JSR_USE_SKILL_FIGURE", raising=False)

    from src import figure_analyzer

    skill_called = {"flag": False}

    def fake_skill(*a, **kw):
        skill_called["flag"] = True
        return None

    # mock 掉 dashscope 调用避免真的发请求
    fake_dashscope = mock.MagicMock()
    fake_mmc = mock.MagicMock()
    # 让 .call() 抛异常, 函数返回 None - 我们只关心 _call_figure_skill 是否被调
    fake_mmc.call.side_effect = RuntimeError("blocked in test")
    fake_dashscope.MultiModalConversation = fake_mmc

    with mock.patch.object(figure_analyzer, "_call_figure_skill",
                            side_effect=fake_skill), \
         mock.patch.dict(sys.modules, {"dashscope": fake_dashscope}):
        # 默认 via_skill=False, 不应触发 skill
        result = figure_analyzer.analyze_figure_with_vision_llm(
            fake_image, paper_context="x"
        )
    assert skill_called["flag"] is False, "默认行为不应调 skill"


# ============================================================
# Test 4: 环境变量触发 skill 路径
# ============================================================

def test_via_skill_env_var_triggered(fake_image, monkeypatch):
    """JSR_USE_SKILL_FIGURE=1 时走 subprocess (mock)。"""
    monkeypatch.setenv("JSR_USE_SKILL_FIGURE", "1")

    from src import figure_analyzer

    fake_analysis = {
        "figure_type": "architecture",
        "layout_direction": "left-to-right",
        "components": [{"name": "A"}],
        "connections": [],
        "data_flow": "", "key_innovation": "innov",
        "animation_suggestion": "", "has_neural_network": False,
        "nn_layers": [], "source": "vision_skill",
        "has_precise_bbox": False,
    }

    skill_called = {"flag": False}

    def fake_skill(image_path, paper_context="", timeout=600):
        skill_called["flag"] = True
        return fake_analysis

    with mock.patch.object(figure_analyzer, "_call_figure_skill",
                            side_effect=fake_skill):
        result = figure_analyzer.analyze_figure_with_vision_llm(
            fake_image, paper_context="x"
        )
    assert skill_called["flag"] is True, "环境变量应触发 skill"
    assert result is not None
    assert result["source"] == "vision_skill"
    assert result["key_innovation"] == "innov"


# ============================================================
# Test 5: skill 失败 fallback 到 Qwen-VL
# ============================================================

def test_skill_failure_falls_back_to_qwen_vl(fake_image, monkeypatch):
    """skill 抛 TimeoutExpired (返回 None) 时, 不应抛异常, 走 Qwen-VL fallback 分支。"""
    monkeypatch.setenv("JSR_USE_SKILL_FIGURE", "1")

    from src import figure_analyzer

    # mock skill 返回 None (模拟 TimeoutExpired 后 _call_figure_skill 已 catch)
    skill_called = {"n": 0}

    def fake_skill(image_path, paper_context="", timeout=600):
        skill_called["n"] += 1
        return None

    # mock Qwen-VL 路径: 让 dashscope import 后 .call() 立刻失败,
    # 关键点: 函数应优雅返回 None 而不是抛异常给上层
    fake_dashscope = mock.MagicMock()
    fake_mmc = mock.MagicMock()
    fake_mmc.call.side_effect = RuntimeError("simulated qwen failure")
    fake_dashscope.MultiModalConversation = fake_mmc

    with mock.patch.object(figure_analyzer, "_call_figure_skill",
                            side_effect=fake_skill), \
         mock.patch.dict(sys.modules,
                          {"dashscope": fake_dashscope}):
        # 不应抛异常
        result = figure_analyzer.analyze_figure_with_vision_llm(
            fake_image, paper_context="x", max_retries=1
        )
    assert skill_called["n"] == 1, "skill 应被调一次"
    # Qwen-VL 也失败时, 函数返回 None (而不是抛)
    assert result is None


# ============================================================
# Test 6 (额外): subprocess TimeoutExpired 真触发 _call_figure_skill 的 except 分支
# ============================================================

def test_call_figure_skill_handles_timeout(fake_image):
    """_call_figure_skill 在 subprocess 超时时应返回 None, 不抛异常。"""
    from src import figure_analyzer

    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=["opencode"], timeout=1)

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = figure_analyzer._call_figure_skill(fake_image, paper_context="x",
                                                     timeout=1)
    assert result is None
