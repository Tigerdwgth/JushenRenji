"""集成测试: 核心公式讲解 + 自适应 scene 编排（feature: formula pipeline）。

只测编排层纯逻辑, 不真跑 opencode / latex 渲染:
  - scene 自适应: ManimEngine._build_scene_defs 在 0/1/2/3 公式下分别产出 4/5/6/6 个 scene,
    FormulaScene 落在 Method 与 Results 之间。
  - narration 对齐: narrations 与 scene_defs 等长, FormulaScene 对应其公式 narration。
  - 降级: validate_latex 返回 False 的公式在 plan 层 (_extract_core_formulas)
    被丢弃, 不进 plan["formulas"]/scene（manim 层不再 double-check）。
  - kill switch: JSR_DISABLE_FORMULA=1 → 公式提取返回 [] → 4 scene。
  - 老链路不变: structured_plan 无 formulas 字段 → 4 scene 原顺序。

ManimEngine._build_scene_defs 是 run() 真正使用的编排函数（抽出便于单测），
因此测的是真实逻辑而非复制品。validate_latex 默认走 JSR_DISABLE_LATEX_VALIDATE
跳过子进程编译, 只在 plan 层降级用例里 monkeypatch 成 False。manim 层 (_build_scene_defs)
信任 plan 层已过滤的 formulas, 不再重复 validate_latex。
"""
import os
import sys
from unittest.mock import patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
for p in (ROOT, SRC):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------- fixtures ----------------

@pytest.fixture(autouse=True)
def _skip_real_latex(monkeypatch):
    """默认不真编译 latex（信任输入）; 降级用例自行 monkeypatch validate_latex。"""
    monkeypatch.setenv("JSR_DISABLE_LATEX_VALIDATE", "1")


@pytest.fixture
def engine(tmp_path):
    """构造一个轻量 ManimEngine（__init__ 仅建临时目录, 不渲染）。"""
    from src.manim_engine import ManimEngine
    return ManimEngine(
        paper_text="fake paper text",
        structured_plan={},
        output_dir=str(tmp_path / "manim"),
    )


def _plan_scripts():
    return {"opening": "开场", "intro": "引言", "method": "方法", "results": "结果"}


def _formula(latex, narration, highlights=None):
    return {"latex": latex, "narration": narration, "highlights": highlights or []}


def _names(defs):
    return [d["scene_name"] for d in defs]


def _set_formulas(engine, formulas):
    engine.structured_plan = {"formulas": formulas}


# ---------------- scene 自适应 ----------------

def test_zero_formula_keeps_four_scenes(engine):
    """0 公式 → 仍 4 个 scene, 原顺序。"""
    _set_formulas(engine, [])
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    assert _names(defs) == ["TitleScene", "IntroScene", "MethodScene", "ResultsScene"]
    assert len(narrs) == 4


def test_one_formula_yields_five_scenes(engine):
    """1 公式 → 5 个 scene, FormulaScene1 在 Method 与 Results 之间。"""
    _set_formulas(engine, [_formula(r"L = \sum_i (y_i - \hat{y}_i)^2", "讲解一")])
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    names = _names(defs)
    assert len(defs) == 5
    assert names == ["TitleScene", "IntroScene", "MethodScene", "FormulaScene1", "ResultsScene"]
    assert names.index("MethodScene") < names.index("FormulaScene1") < names.index("ResultsScene")
    assert len(narrs) == 5


def test_two_formulas_yield_six_scenes_between_method_and_results(engine):
    """2 公式 → 6 个 scene, 两个 FormulaScene 顺序落在 Method 与 Results 之间。"""
    _set_formulas(engine, [
        _formula(r"L = \sum_i (y_i - \hat{y}_i)^2", "讲解一", ["a", "b"]),
        _formula(r"p(x) = \frac{1}{Z} e^{-E(x)}", "讲解二", ["c"]),
    ])
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    names = _names(defs)
    assert len(defs) == 6
    assert names == ["TitleScene", "IntroScene", "MethodScene",
                     "FormulaScene1", "FormulaScene2", "ResultsScene"]
    mi, ri = names.index("MethodScene"), names.index("ResultsScene")
    f1, f2 = names.index("FormulaScene1"), names.index("FormulaScene2")
    assert mi < f1 < f2 < ri
    assert len(narrs) == 6


def test_three_formulas_truncated_to_two(engine):
    """3 公式 → 截断到 2 → 6 个 scene, 无 FormulaScene3。"""
    _set_formulas(engine, [
        _formula(r"L = \sum_i (y_i - \hat{y}_i)^2", "讲解一"),
        _formula(r"p(x) = \frac{1}{Z} e^{-E(x)}", "讲解二"),
        _formula(r"E = mc^2", "讲解三"),
    ])
    defs, _ = engine._build_scene_defs(_plan_scripts())
    names = _names(defs)
    assert len(defs) == 6
    assert "FormulaScene3" not in names
    assert names == ["TitleScene", "IntroScene", "MethodScene",
                     "FormulaScene1", "FormulaScene2", "ResultsScene"]


# ---------------- narration 对齐 ----------------

def test_narration_alignment_with_formula_scenes(engine):
    """narration 列表与 scene 列表等长, 每个 FormulaScene 对应其公式 narration。"""
    _set_formulas(engine, [
        _formula(r"L = \sum_i (y_i - \hat{y}_i)^2", "公式讲解甲"),
        _formula(r"p(x) = \frac{1}{Z} e^{-E(x)}", "公式讲解乙"),
    ])
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    assert len(narrs) == len(defs)
    names = _names(defs)
    assert narrs[names.index("FormulaScene1")] == "公式讲解甲"
    assert narrs[names.index("FormulaScene2")] == "公式讲解乙"
    # 固定段旁白仍来自 plan_scripts
    assert narrs[names.index("MethodScene")] == "方法"
    assert narrs[names.index("ResultsScene")] == "结果"


# ---------------- 降级 ----------------

def test_invalid_latex_dropped(engine, monkeypatch):
    """非法 latex 在 plan 层 (_extract_core_formulas) 被丢弃 → 不进 scene。

    Bug#6 后 manim 层 (_build_scene_defs) 不再 double-check validate_latex，
    信任 plan 层已过滤的 formulas。这里端到端验证：plan 层喂坏+好两条，坏的
    校验不过被丢，过滤后只剩好公式，_build_scene_defs 只产出 1 个 FormulaScene。
    """
    import json as _json
    bad = r"\frac{a"
    good = r"L = \sum_i x_i"
    llm_out = _json.dumps({"formulas": [
        {"latex": bad, "narration": "坏公式", "highlights": ["x"]},
        {"latex": good, "narration": "好公式", "highlights": ["y"]},
    ]})

    def fake_validate(latex, timeout=15):
        return latex.strip() == good

    # plan 层降级：关掉全局跳过，patch validate_latex 丢坏公式
    monkeypatch.delenv("JSR_DISABLE_LATEX_VALIDATE", raising=False)
    monkeypatch.setattr("src.latex_utils.validate_latex", fake_validate)
    with patch("src.llm_tools.llm_agent.create_chat_completion", return_value=llm_out):
        from src.llm_tools.llm_agent import _extract_core_formulas
        formulas = _extract_core_formulas("论文正文文本", arxiv_id=None)
    assert len(formulas) == 1 and formulas[0]["narration"] == "好公式"

    # 过滤后的 formulas 喂给 manim 层编排：只剩 1 个有效公式 → 5 个 scene
    _set_formulas(engine, formulas)
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    names = _names(defs)
    assert len(defs) == 5
    assert names.count("FormulaScene1") == 1 and "FormulaScene2" not in names
    assert narrs[names.index("FormulaScene1")] == "好公式"
    assert "坏公式" not in narrs


def test_formula_missing_fields_dropped(engine):
    """缺 latex 或 narration 的公式条目被丢弃。"""
    _set_formulas(engine, [
        {"latex": "", "narration": "无公式体"},
        {"latex": r"x = y", "narration": ""},
        _formula(r"z = w", "合法"),
    ])
    defs, _ = engine._build_scene_defs(_plan_scripts())
    assert len(defs) == 5  # 仅 1 条合法


# ---------------- kill switch（plan 层）----------------

def test_kill_switch_disables_formula_extraction(monkeypatch):
    """JSR_DISABLE_FORMULA=1 → _extract_core_formulas 直接返回 []。"""
    monkeypatch.setenv("JSR_DISABLE_FORMULA", "1")
    from src.llm_tools.llm_agent import _extract_core_formulas
    assert _extract_core_formulas("任意论文文本", arxiv_id="1234.5678") == []


def test_kill_switch_then_four_scenes(engine, monkeypatch):
    """kill switch 下 plan 不含 formulas → 编排回到 4 scene。"""
    monkeypatch.setenv("JSR_DISABLE_FORMULA", "1")
    from src.llm_tools.llm_agent import _extract_core_formulas
    formulas = _extract_core_formulas("论文文本", arxiv_id="1234.5678")
    _set_formulas(engine, formulas)
    defs, _ = engine._build_scene_defs(_plan_scripts())
    assert len(defs) == 4


# ---------------- 老链路不变 ----------------

def test_legacy_plan_without_formulas_field(engine):
    """plan 完全无 formulas 字段 → 4 scene 原顺序（老链路字节级一致）。"""
    engine.structured_plan = {
        "opening": {"script": "开场"}, "intro": {"script": "引言"},
        "method": {"script": "方法"}, "results": {"script": "结果"},
    }
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    assert _names(defs) == ["TitleScene", "IntroScene", "MethodScene", "ResultsScene"]
    assert len(narrs) == 4


# ---------------- plan 层降级（LLM mock）----------------

def test_plan_layer_drops_invalid_latex(monkeypatch):
    """_extract_core_formulas: LLM 返回两条公式, 一条非法 latex 被丢弃。"""
    import json as _json
    llm_out = _json.dumps({"formulas": [
        {"latex": r"\frac{a", "narration": "坏", "highlights": ["x"]},
        {"latex": r"L = \sum_i x_i", "narration": "好", "highlights": ["y"]},
    ]})
    # 无 arxiv_id → 走文本兜底路径, 不抓 tex 源码
    with patch("src.llm_tools.llm_agent.create_chat_completion", return_value=llm_out):
        # 只接受已知合法公式; 坏公式校验不过, 修复返回的 JSON 串也不会被接受 → 丢弃。
        def fake_validate(latex, timeout=15):
            return latex.strip() == r"L = \sum_i x_i"
        monkeypatch.setattr("src.latex_utils.validate_latex", fake_validate)
        # 关掉全局跳过, 让降级真生效
        monkeypatch.delenv("JSR_DISABLE_LATEX_VALIDATE", raising=False)
        from src.llm_tools.llm_agent import _extract_core_formulas
        formulas = _extract_core_formulas("论文正文文本", arxiv_id=None)
    assert len(formulas) == 1
    assert formulas[0]["narration"] == "好"
