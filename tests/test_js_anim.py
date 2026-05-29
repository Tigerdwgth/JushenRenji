"""集成测试: JS/Web 示意动画 + 自适应 scene 编排（feature: js_anim pipeline）。

只测**编排层**纯逻辑, 不真跑 opencode / playwright / ffmpeg:
  - scene 自适应: ManimEngine._build_scene_defs 按 structured_plan["animations"]
    在正确位置插入 AnimScene（intro_after 在 IntroScene 后 / method 在 method 区末尾）;
  - 总预算 clamp: 固定 4 + 额外（公式 + 示意）<= 3、总 <= 7, 公式优先占额度;
  - narration 对齐: narrations 与 scene_defs 等长, AnimScene 旁白即其 scene_desc;
  - 渲染失败降级: apply_anim_render_results 把渲染失败的 js_anim scene 干净丢弃,
    剩余 scene/narration 索引不错乱, _blog_scene_assignments 不含被丢弃 idx;
  - kill switch: JSR_DISABLE_JS_ANIM=1 → plan animations 为 [] → 4 scene。

_build_scene_defs / apply_anim_render_results 都是 run() 真正使用的函数（抽出便于
单测），测的是真实逻辑而非复制品。区别于 tests/test_js_anim_engine.py（那测渲染底座）。
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
for p in (ROOT, SRC):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------- fixtures ----------------

@pytest.fixture(autouse=True)
def _skip_real_latex(monkeypatch):
    """公式 double-check 走环境跳过, 不真编译 latex（公式只作占额度用）。"""
    monkeypatch.setenv("JSR_DISABLE_LATEX_VALIDATE", "1")


@pytest.fixture(autouse=True)
def _anim_enabled(monkeypatch):
    """默认确保 kill switch 关着（除非用例显式开启）。"""
    monkeypatch.delenv("JSR_DISABLE_JS_ANIM", raising=False)


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


def _names(defs):
    return [d["scene_name"] for d in defs]


def _anim(scene_desc, target_seconds=7, kind="abstract", position="method",
          prefer_real_demo=False):
    return {
        "scene_desc": scene_desc,
        "target_seconds": target_seconds,
        "kind": kind,
        "position": position,
        "prefer_real_demo": prefer_real_demo,
    }


def _formula(latex, narration, highlights=None):
    return {"latex": latex, "narration": narration, "highlights": highlights or []}


# ---------------- 1. scene 自适应（公式0 + 示意2）----------------

def test_anim_scene_adaptive(engine):
    """公式 0 + 示意 2（intro_after 1 / method 1） → 6 scene,
    AnimScene 落在正确位置, narration 等长对齐。"""
    engine.structured_plan = {
        "formulas": [],
        "animations": [
            _anim("机械臂抓取布料的任务示意", kind="concrete", position="intro_after"),
            _anim("策略网络数据流的抽象机制", kind="abstract", position="method"),
        ],
    }
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    names = _names(defs)
    assert len(defs) == 6
    # 两个 AnimScene 都在
    assert names.count("AnimScene1") == 1 and names.count("AnimScene2") == 1
    # intro_after 的 AnimScene1 紧跟 IntroScene、在 MethodScene 之前
    i_intro = names.index("IntroScene")
    i_method = names.index("MethodScene")
    i_a1 = names.index("AnimScene1")
    assert i_intro < i_a1 < i_method
    # method 的 AnimScene2 在 MethodScene 之后、ResultsScene 之前
    i_results = names.index("ResultsScene")
    i_a2 = names.index("AnimScene2")
    assert i_method < i_a2 < i_results
    # narration 等长对齐, AnimScene 旁白即 scene_desc
    assert len(narrs) == len(defs)
    assert narrs[i_a1] == "机械臂抓取布料的任务示意"
    assert narrs[i_a2] == "策略网络数据流的抽象机制"
    # 固定段旁白仍来自 plan_scripts
    assert narrs[names.index("MethodScene")] == "方法"
    assert narrs[names.index("ResultsScene")] == "结果"


# ---------------- 2. 预算 clamp（公式优先）----------------

def test_budget_clamp_formula_priority(engine):
    """公式 2 + 示意 2 → 额外额度 clamp 到 3, 公式优先占 2, 示意只剩 1 →
    示意被截到 1, 总 7 scene。"""
    engine.structured_plan = {
        "formulas": [
            _formula(r"L = \sum_i (y_i - \hat{y}_i)^2", "公式甲"),
            _formula(r"p(x) = \frac{1}{Z} e^{-E(x)}", "公式乙"),
        ],
        "animations": [
            _anim("示意一", position="method"),
            _anim("示意二", position="method"),
        ],
    }
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    names = _names(defs)
    # 4 固定 + 2 公式 + 1 示意 = 7
    assert len(defs) == 7
    assert names.count("FormulaScene1") == 1 and names.count("FormulaScene2") == 1
    assert names.count("AnimScene1") == 1
    assert "AnimScene2" not in names  # 第二个示意被额度截断丢弃
    assert len(narrs) == len(defs)


# ---------------- 3. 老链路不变 ----------------

def test_no_animations_legacy_unchanged(engine):
    """无 animations 字段 / animations=[] → 4 scene 原样（与老链路一致）。"""
    # case A: 完全无 animations 字段
    engine.structured_plan = {}
    defs_a, narrs_a = engine._build_scene_defs(_plan_scripts())
    assert _names(defs_a) == ["TitleScene", "IntroScene", "MethodScene", "ResultsScene"]
    assert len(narrs_a) == 4
    # case B: animations 显式空列表
    engine.structured_plan = {"animations": []}
    defs_b, narrs_b = engine._build_scene_defs(_plan_scripts())
    assert _names(defs_b) == ["TitleScene", "IntroScene", "MethodScene", "ResultsScene"]
    assert len(narrs_b) == 4


# ---------------- 4. 渲染失败降级丢弃 ----------------

def test_js_anim_render_drop_on_failure(engine, monkeypatch):
    """模拟一个 js_anim scene HTML 生成失败（返回 None）→
    apply_anim_render_results 把它干净丢弃: 剩余 scene/narration 索引连续不错乱,
    _blog_scene_assignments 不含被丢弃 idx。"""
    import src.js_anim_engine as js_anim_engine
    from src.manim_engine import apply_anim_render_results

    # monkeypatch 渲染底座: 让 _opencode_generate_html 永远失败（run() 据此判降级）。
    monkeypatch.setattr(js_anim_engine, "_opencode_generate_html",
                        lambda *a, **k: None)
    # 确认降级触发条件成立: HTML 生成返回 None
    assert js_anim_engine._opencode_generate_html("prompt", "AnimScene2", "/tmp") is None

    # 先用编排层造出含 2 个 AnimScene 的 scene_defs（公式 0、示意 2）
    engine.structured_plan = {
        "formulas": [],
        "animations": [
            _anim("示意甲", position="intro_after"),
            _anim("示意乙", position="method"),
        ],
    }
    scene_defs, narrations = engine._build_scene_defs(_plan_scripts())
    assert len(scene_defs) == 6

    # 模拟 run() 渲染分支结果: AnimScene1 成功、AnimScene2 失败被丢弃
    names = _names(scene_defs)
    idx_a1 = names.index("AnimScene1")
    idx_a2 = names.index("AnimScene2")
    anim_mp4_by_idx = {idx_a1: "/fake/AnimScene1.mp4"}
    dropped_idxs = {idx_a2}
    blog_assignments = {}  # 纯 js_anim 路径, blog 为空

    new_defs, new_narrs, new_blog = apply_anim_render_results(
        scene_defs, narrations, blog_assignments, anim_mp4_by_idx, dropped_idxs,
    )

    new_names = _names(new_defs)
    # AnimScene2 被丢弃, 剩 5 scene
    assert len(new_defs) == 5
    assert "AnimScene2" not in new_names
    assert "AnimScene1" in new_names
    # scene 与 narration 仍一一对齐、索引连续
    assert len(new_defs) == len(new_narrs)
    for i, sdef in enumerate(new_defs):
        # AnimScene1 的 narration 仍是它的 scene_desc
        if sdef["scene_name"] == "AnimScene1":
            assert new_narrs[i] == "示意甲"
    # 成功的 AnimScene1 已登记进 blog assignments（用重映射后的新 idx）
    new_idx_a1 = new_names.index("AnimScene1")
    assert new_blog.get(new_idx_a1) == "/fake/AnimScene1.mp4"
    # 被丢弃的旧 idx 不在 blog assignments 里
    assert idx_a2 not in new_blog
    # blog assignments 的 value 不含任何被丢弃 scene 的残留
    assert "/fake/AnimScene1.mp4" in new_blog.values()
    assert all(0 <= k < len(new_defs) for k in new_blog)


# ---------------- 5. kill switch ----------------

def test_kill_switch_no_anim(engine, monkeypatch):
    """JSR_DISABLE_JS_ANIM=1 时 plan 层 animations 为 [] → 编排回到 4 scene。"""
    monkeypatch.setenv("JSR_DISABLE_JS_ANIM", "1")
    from src.llm_tools.llm_agent import _extract_scene_animations
    # kill switch 下提取直接返回 []，不触发 LLM
    animations = _extract_scene_animations("任意论文正文文本", arxiv_id="1234.5678")
    assert animations == []
    engine.structured_plan = {"animations": animations}
    defs, narrs = engine._build_scene_defs(_plan_scripts())
    assert _names(defs) == ["TitleScene", "IntroScene", "MethodScene", "ResultsScene"]
    assert len(narrs) == 4
