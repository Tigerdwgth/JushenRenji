"""``src.llm_tools.cli`` — opencode skill 的 LLM 命令行入口（P1 + P3）。

子命令：
- ``generate-plan``  把 paper_meta JSON 生成 5 段式视频脚本 JSON（P1: video-plan）
- ``rate-images``    给候选图片批量打分(0-10) + 推荐 section（P3: image-rating）

统一 JSON 输出契约（stdout）::

    成功(generate-plan): {"ok": true, "out": "<path>", "sections": ["opening", ...]}
    成功(rate-images):   {"ok": true, "scored": <n>, "above_5": <n>}
    失败:                {"ok": false, "error": "<msg>"}

stderr 仅写日志（WARNING+），不污染 stdout JSON 契约。

调用前自动 ``apply_network_workarounds()``（幂等，``JSR_NETWORK_PROFILE``
环境变量决定是否启用）。

CLI 内部用 pipe 模式调 ``opencode run -m <model> -``（避免长 prompt 在 shell
命令行展开卡死，LESSONS 已记）；opencode 失败 / 超时时兜底用一次 plain
``create_chat_completion``；仍失败则写空骨架 + ``ok=false`` 返回。

Bash 例子::

    python -m src.llm_tools.cli generate-plan \\
        --paper-meta /tmp/paper_meta.json \\
        --target-duration 300 \\
        --language zh \\
        --out /tmp/plan_out.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from typing import Optional


_PLAN_SECTIONS = ("opening", "intro", "method", "results", "conclusion")
_DEFAULT_RATIOS = {
    "opening": 0.10,
    "intro": 0.20,
    "method": 0.40,
    "results": 0.20,
    "conclusion": 0.10,
}


# -----------------------------------------------------------------------------
# 路径 helpers
# -----------------------------------------------------------------------------

def _project_root() -> str:
    """src/llm_tools/cli.py 上两级 = 项目根。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup_logging() -> None:
    """CLI 默认 WARNING 走 stderr，避免污染 stdout JSON。"""
    logging.basicConfig(
        level=logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _print_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _apply_network_workarounds_safe() -> None:
    """幂等调 apply_network_workarounds；失败仅 warning。"""
    try:
        try:
            from src.env_setup import apply_network_workarounds
        except ImportError:
            from env_setup import apply_network_workarounds  # type: ignore
        apply_network_workarounds()
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli] apply_network_workarounds failed: %s", e)


def _resolve_opencode_model(cli_arg: str = "") -> str:
    """优先 CLI 参数，其次 config.yaml.opencode_model，最后空串。"""
    arg = (cli_arg or "").strip()
    if arg:
        return arg
    cfg_path = os.path.join(_project_root(), "config.yaml")
    if not os.path.isfile(cfg_path):
        return ""
    try:
        import yaml
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return (cfg.get("opencode_model") or "").strip()
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli] read config.yaml.opencode_model failed: %s", e)
        return ""


# -----------------------------------------------------------------------------
# Prompt 构造
# -----------------------------------------------------------------------------

def _per_section_durations(target_duration: int) -> dict:
    """按 _DEFAULT_RATIOS 分配每段秒数（取整、确保和 == target）。"""
    out = {}
    remaining = target_duration
    keys = list(_PLAN_SECTIONS)
    for k in keys[:-1]:
        out[k] = max(1, int(round(target_duration * _DEFAULT_RATIOS[k])))
        remaining -= out[k]
    out[keys[-1]] = max(1, remaining)
    return out


def _build_video_plan_prompt(paper_meta: dict, target_duration: int,
                              language: str = "zh") -> str:
    """构造给 opencode 的 prompt 文本。

    JSON 模板里的花括号必须 ``{{`` ``}}`` 转义（LESSONS 已记）。
    本函数内部不用 ``str.format``，所以用普通 ``{`` 即可，但维持一致风格——
    示例 JSON 里直接写普通花括号（因为我们用字符串拼接，不用 format）。
    """
    title = (paper_meta.get("title") or "").strip()
    abstract = (paper_meta.get("abstract") or "").strip()
    authors = paper_meta.get("authors") or []
    if isinstance(authors, list):
        authors_str = ", ".join(str(a) for a in authors[:8])
    else:
        authors_str = str(authors)
    key_points = paper_meta.get("key_points") or []
    if isinstance(key_points, list):
        key_points_str = "\n".join("  - " + str(kp) for kp in key_points[:8])
    else:
        key_points_str = "  - " + str(key_points)
    venue = (paper_meta.get("venue") or "").strip()
    github = (paper_meta.get("github_repo") or "").strip()

    durations = _per_section_durations(target_duration)
    chars_per_sec = 4  # 中文 TTS 约 4 字/秒
    char_budget = {k: durations[k] * chars_per_sec for k in _PLAN_SECTIONS}

    schema_example = (
        '{\n'
        '  "opening":    {"text": "...", "duration_sec": ' + str(durations["opening"]) + ', "key_points": ["...", "..."]},\n'
        '  "intro":      {"text": "...", "duration_sec": ' + str(durations["intro"]) + ', "key_points": ["...", "..."]},\n'
        '  "method":     {"text": "...", "duration_sec": ' + str(durations["method"]) + ', "key_points": ["...", "..."]},\n'
        '  "results":    {"text": "...", "duration_sec": ' + str(durations["results"]) + ', "key_points": ["...", "..."]},\n'
        '  "conclusion": {"text": "...", "duration_sec": ' + str(durations["conclusion"]) + ', "key_points": ["...", "..."]}\n'
        '}'
    )

    lang_note = "中文（口语化、课堂讲解风格）" if language.lower().startswith("zh") else "English"

    parts = []
    parts.append("你是一名顶级科技视频脚本策划。请根据下面的论文 paper_meta 生成严格的 JSON 结构化视频脚本。")
    parts.append("")
    parts.append("【代码生成铁律】")
    parts.append("- 这是一个独立的 JSON 生成任务。不要 read / cat / inspect 工作目录中任何文件；不要调用 file/shell tool。")
    parts.append("- 直接基于下面给定的 paper_meta，从零生成完整的 5 段 JSON。")
    parts.append("- 输出必须是唯一一个 ```json ... ``` markdown 代码块，包含完整 JSON 对象。")
    parts.append("- 严禁输出'已有/查看/已经满足需求/不需要修改'这类描述语。")
    parts.append("")
    parts.append("【输入：paper_meta】")
    parts.append("title: " + title)
    if venue:
        parts.append("venue: " + venue)
    if authors_str:
        parts.append("authors: " + authors_str)
    if github:
        parts.append("github_repo: " + github)
    parts.append("abstract:")
    parts.append(abstract)
    if key_points_str:
        parts.append("")
        parts.append("key_points:")
        parts.append(key_points_str)
    parts.append("")
    parts.append("【输出：5 段 JSON Schema】")
    parts.append("严格 JSON,不要 markdown 之外的任何字符。每段必须包含 text / duration_sec / key_points 三个字段。")
    parts.append(schema_example)
    parts.append("")
    parts.append("【字数预算（按 4 字/秒）】")
    for k in _PLAN_SECTIONS:
        parts.append("- " + k + ": 约 " + str(char_budget[k]) + " 字 (" + str(durations[k]) + "秒)")
    parts.append("")
    parts.append("【风格约束】")
    parts.append("1. 输出语言: " + lang_note)
    parts.append("2. 课堂讲解风格,每段开头有自然衔接(\"今天来聊聊\"、\"我们先看看\"、\"接下来重点讲讲\")")
    parts.append("3. 避免列表式: 禁止 markdown 列表、bullet、编号")
    parts.append("4. 避免堆术语: 英文方法名首次出现时翻译或用类比解释")
    parts.append("5. 避免夸张词: 禁止\"首次\"、\"突破\"、\"震撼\"、\"颠覆\"")
    parts.append("6. 数据真实: 禁止虚构数据,论文未提的数字一律不写")
    parts.append("7. 段间过渡: method → results 用\"那这个方法效果到底如何呢?\"等过渡句")
    parts.append("")
    parts.append("【自检条目（生成时遵守）】")
    parts.append("- opening 段是否有 hook(一句话点出痛点 / 惊人数据 / 反直觉发现)?")
    parts.append("- intro 段是否说清楚 \"为什么这个问题难\"?")
    parts.append("- method 段是否讲清楚 \"做什么 + 怎么做\"?")
    parts.append("- results 段是否有 1-2 个具体实验数字(来自 abstract)?")
    parts.append("- conclusion 段是否给出 \"启发 / 未来方向\"?")
    parts.append("")
    parts.append("仅输出一个 ```json ... ``` 代码块,不加任何前后说明文字。")
    return "\n".join(parts)


# -----------------------------------------------------------------------------
# opencode pipe 调用 + JSON 解析
# -----------------------------------------------------------------------------

def _run_opencode_with_pipe(prompt_text: str, opencode_model: str,
                             timeout_sec: int = 240) -> str:
    """以 pipe 模式调 ``opencode run -m <model> -``。

    抄自 ``paper_discovery._run_opencode_with_pipe``,独立解耦:
    - prompt 写到 cache/_video_plan_prompt.txt
    - wrapper 写到 cache/_video_plan_wrap.sh (cd 到项目根)
    """
    if not opencode_model:
        logging.warning("[llm.cli] opencode_model not configured, skip opencode")
        return ""

    cache_dir = os.path.join(_project_root(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    prompt_file = os.path.join(cache_dir, "_video_plan_prompt.txt")
    wrapper = os.path.join(cache_dir, "_video_plan_wrap.sh")

    try:
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        with open(wrapper, "w", encoding="utf-8") as wf:
            wf.write("#!/bin/bash\n")
            wf.write("export PATH=/usr/local/bin:$PATH\n")
            wf.write('cd "{c}"\n'.format(c=cache_dir))
            wf.write('cat "{p}" | opencode run -m {m} -\n'.format(
                p=prompt_file, m=opencode_model))
        os.chmod(wrapper, 0o755)
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli] write opencode wrapper failed: %s", e)
        return ""

    env = os.environ.copy()
    # 与 manim_engine / paper_discovery 一致: opencode 不走系统代理
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)

    try:
        r = subprocess.run(
            ["bash", wrapper], capture_output=True, text=True,
            timeout=timeout_sec, env=env, cwd=cache_dir,
        )
        out = r.stdout or r.stderr or ""
    except subprocess.TimeoutExpired:
        logging.warning("[llm.cli] opencode timeout after %ds", timeout_sec)
        return ""
    except FileNotFoundError as e:
        logging.warning("[llm.cli] opencode binary not found: %s", e)
        return ""
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli] opencode run failed: %s", e)
        return ""

    out = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out or "")
    return out


def _parse_plan_json(raw: str) -> Optional[dict]:
    """从 opencode/LLM 返回中抽 ```json ... ``` 块或裸 {...},解析为 dict。"""
    if not raw:
        return None
    s = raw.strip()
    m = re.search(r"```json\s*\n(.*?)\n```", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"```\s*\n(.*?)\n```", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _validate_plan(plan: dict) -> bool:
    """5 段 JSON 必须含每段的 text / duration_sec / key_points 字段且 text 非空。"""
    if not isinstance(plan, dict):
        return False
    for sec in _PLAN_SECTIONS:
        v = plan.get(sec)
        if not isinstance(v, dict):
            return False
        text = v.get("text") or v.get("script") or ""
        if not isinstance(text, str) or not text.strip():
            return False
    return True


def _normalize_plan(plan: dict, target_duration: int) -> dict:
    """补齐缺失字段、统一 text/script 命名、补齐 duration_sec / key_points。

    对 partial JSON 友好——只要有 text 就补全。
    """
    if not isinstance(plan, dict):
        plan = {}
    durations = _per_section_durations(target_duration)
    out = {}
    for sec in _PLAN_SECTIONS:
        v = plan.get(sec, {})
        if isinstance(v, str):
            v = {"text": v}
        if not isinstance(v, dict):
            v = {}
        text = v.get("text") or v.get("script") or ""
        kp = v.get("key_points") or []
        if not isinstance(kp, list):
            kp = [str(kp)]
        ds = v.get("duration_sec")
        if not isinstance(ds, int):
            ds = durations[sec]
        out[sec] = {
            "text": str(text or "").strip(),
            "duration_sec": int(ds),
            "key_points": [str(x) for x in kp][:6],
        }
    return out


# -----------------------------------------------------------------------------
# 兜底: plain LLM 单次调用
# -----------------------------------------------------------------------------

def _fallback_plain_llm(prompt_text: str) -> str:
    """opencode 失败时,尝试用 src.llm_tools.llm_agent.create_chat_completion 单次。"""
    try:
        from src.llm_tools.llm_agent import create_chat_completion
        return create_chat_completion(prompt_text, max_tokens=8192) or ""
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli] plain LLM fallback failed: %s", e)
        return ""


# -----------------------------------------------------------------------------
# 主调度: paper_meta -> 5 段 plan
# -----------------------------------------------------------------------------

def _generate_plan_via_opencode(paper_meta: dict, target_duration: int,
                                 language: str, opencode_model: str) -> dict:
    """主流程: 先 opencode pipe → 失败兜底 plain LLM → 再失败返回空骨架。

    返回 5 段 JSON dict (经 _normalize_plan 规整)。永不抛异常。
    """
    prompt = _build_video_plan_prompt(paper_meta, target_duration, language)

    # 第 1 路: opencode skill
    raw = _run_opencode_with_pipe(prompt, opencode_model)
    parsed = _parse_plan_json(raw)
    if parsed and _validate_plan(parsed):
        return _normalize_plan(parsed, target_duration)
    if parsed:
        # 部分有效 - 也补齐返回
        normalized = _normalize_plan(parsed, target_duration)
        if _validate_plan(normalized):
            return normalized
    logging.warning("[llm.cli] opencode path failed or invalid, fallback to plain LLM")

    # 第 2 路: plain LLM
    raw2 = _fallback_plain_llm(prompt)
    parsed2 = _parse_plan_json(raw2)
    if parsed2 and _validate_plan(parsed2):
        return _normalize_plan(parsed2, target_duration)
    if parsed2:
        normalized = _normalize_plan(parsed2, target_duration)
        if _validate_plan(normalized):
            return normalized

    # 第 3 路: 返回空骨架,让上层判断
    logging.error("[llm.cli] both opencode and plain LLM failed, return empty skeleton")
    return _normalize_plan({}, target_duration)


# -----------------------------------------------------------------------------
# CLI argparse 入口
# -----------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-cli",
        description="LLM CLI: 视频脚本生成等子命令(JSON stdout 契约)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "generate-plan",
        help="把 paper_meta JSON 生成 5 段式视频脚本 JSON",
    )
    p.add_argument("--paper-meta", required=True,
                   help="paper_meta JSON 文件路径(含 title / abstract / authors / key_points)")
    p.add_argument("--target-duration", type=int, default=300,
                   help="目标视频总时长(秒,默认 300)")
    p.add_argument("--language", default="zh",
                   help="输出语言(默认 zh,目前仅支持 zh)")
    p.add_argument("--out", required=True,
                   help="输出 plan JSON 文件路径")
    p.add_argument("--opencode-model", default="",
                   help="opencode 模型名(空则从 config.yaml.opencode_model 读)")

    # P3: rate-images
    p3 = sub.add_parser(
        "rate-images",
        help="给候选图片批量打分(0-10) + 推荐 section",
    )
    p3.add_argument("--candidates", required=True,
                    help="候选图片 JSON 文件: list of {image_index, caption, figure_role, paper_context}")
    p3.add_argument("--out", required=True,
                    help="输出 score JSON 文件路径")
    p3.add_argument("--opencode-model", default="",
                    help="opencode 模型名(空则从 config.yaml.opencode_model 读)")
    p3.add_argument("--target-count", type=int, default=8,
                    help="期望保留多少张图(默认 8)")

    return parser


def _run_generate_plan(args) -> int:
    # 读 paper_meta
    if not os.path.isfile(args.paper_meta):
        _print_json({"ok": False, "error": "paper_meta file not found: %s" % args.paper_meta})
        return 1
    try:
        with open(args.paper_meta, "r", encoding="utf-8") as f:
            paper_meta = json.load(f)
    except Exception as e:  # noqa: BLE001
        _print_json({"ok": False, "error": "paper_meta parse failed: %s: %s" % (type(e).__name__, e)})
        return 1

    # 必填校验
    title = (paper_meta.get("title") or "").strip() if isinstance(paper_meta, dict) else ""
    abstract = (paper_meta.get("abstract") or "").strip() if isinstance(paper_meta, dict) else ""
    if not title or not abstract:
        _print_json({"ok": False, "error": "paper_meta must contain non-empty 'title' and 'abstract'"})
        return 1

    target_duration = int(args.target_duration or 300)
    language = (args.language or "zh").strip()
    opencode_model = _resolve_opencode_model(args.opencode_model)

    plan = _generate_plan_via_opencode(paper_meta, target_duration, language, opencode_model)

    # 写出
    out_path = args.out
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        _print_json({"ok": False, "error": "write out failed: %s: %s" % (type(e).__name__, e)})
        return 1

    ok = _validate_plan(plan)
    payload = {
        "ok": bool(ok),
        "out": os.path.abspath(out_path),
        "sections": list(plan.keys()),
    }
    if not ok:
        payload["error"] = "plan validation failed: empty or missing sections"
    _print_json(payload)
    return 0 if ok else 1


# =============================================================================
# P3: rate-images 子命令 — 多轮决策为论文图片打分
# =============================================================================

# 公式图关键词（中英），匹配则硬约束 score ≤ 3
_FORMULA_KEYWORDS = (
    "公式", "方程", "等式",
    "目标函数", "损失函数", "约束条件", "约束",
    "定理", "引理", "推论", "证明",
    "equation", "formula", "loss", "objective",
    "theorem", "lemma", "proof", "constraint",
)

_VALID_SECTIONS = ("opening", "intro", "method", "results", "none")


def _is_formula_caption(caption: str) -> bool:
    """根据 caption 判断是否公式/约束截图(命中关键词即降权)。"""
    if not caption:
        return False
    s = str(caption).lower()
    for kw in _FORMULA_KEYWORDS:
        if kw.lower() in s:
            return True
    return False


def _build_rate_images_prompt(candidates: list, target_count: int) -> str:
    """构造给 opencode 的多轮决策 prompt。

    JSON 模板里的花括号必须 ``{{`` ``}}`` 转义(LESSONS 已记)；
    本函数用字符串拼接而不用 ``str.format``,所以普通 ``{`` ``}`` 即可。
    """
    n = len(candidates)
    lines = []
    lines.append("你是一名顶级科技视频图片选材专家。我会给你一组论文候选图(captions + 角色 + 上下文)，")
    lines.append("请为每张图打 0-10 分,并推荐放在视频哪一段(opening/intro/method/results/none)。")
    lines.append("")
    lines.append("【代码生成铁律】")
    lines.append("- 这是独立的 JSON 评分任务,不要 read / cat 工作目录中任何文件,不要调用 file/shell tool。")
    lines.append("- 直接基于下面给定的候选 captions 推理,从零生成完整 JSON。")
    lines.append("- 输出必须是唯一一个 ```json ... ``` 代码块,内容为长度恰好 " + str(n) + " 的 JSON 数组。")
    lines.append("")
    lines.append("【多轮决策(必须内部依次执行)】")
    lines.append("- 第 1 轮: 基于 caption / figure_role / paper_context 给每张图打初步分(0-10)。")
    lines.append("- 第 2 轮: 自检——")
    lines.append("    a) 视觉化效果差吗?(纯公式/纯文字截图扣分)")
    lines.append("    b) 跟其他高分图重复吗?(同一架构图不同视角扣分,保留信息密度更高的)")
    lines.append("    c) caption 是否对应论文核心贡献(method 架构 / results 主指标 ≥ 6 分)?")
    lines.append("- 第 3 轮: 给最终分数 + 推荐 section + 一句话理由。")
    lines.append("")
    lines.append("【硬约束(必须遵守)】")
    lines.append("1. 公式/方程/约束/损失函数/定理截图 → 分数必须 ≤ 3 且 recommended_section=\"none\"。")
    lines.append("   关键词: 公式 / 方程 / 等式 / 目标函数 / 损失函数 / 约束 / 定理 / 引理 / 证明 /")
    lines.append("           equation / formula / loss / objective / theorem / lemma / proof / constraint。")
    lines.append("2. 总览图 / 方法架构图 → 通常 7-9 分,放 method。")
    lines.append("3. 核心实验主表 / 主曲线 → 通常 6-8 分,放 results。")
    lines.append("4. 消融实验 / 次要分析 → 通常 4-6 分,放 results 或 none。")
    lines.append("5. 期望最终保留 " + str(int(target_count)) + " 张评分 ≥ 5 的图(不强求,但努力贴近)。")
    lines.append("")
    lines.append("【候选图列表(共 " + str(n) + " 张)】")
    for c in candidates:
        if not isinstance(c, dict):
            c = {}
        idx = c.get("image_index", 0)
        cap = (c.get("caption") or "").strip().replace("\n", " ")[:300]
        role = (c.get("figure_role") or "").strip()
        ctx = (c.get("paper_context") or "").strip().replace("\n", " ")[:200]
        lines.append("- image_index=" + str(idx)
                     + " | role=" + (role or "?")
                     + " | caption: " + (cap or "(empty)")
                     + (" | context: " + ctx if ctx else ""))
    lines.append("")
    lines.append("【输出 JSON Schema(严格遵守)】")
    lines.append('[')
    lines.append('  {')
    lines.append('    "image_index": 0,')
    lines.append('    "caption": "原 caption(可截断)",')
    lines.append('    "score": 8.5,')
    lines.append('    "reason": "一句话理由(中文)",')
    lines.append('    "recommended_section": "method",')
    lines.append('    "rejected": false')
    lines.append('  },')
    lines.append('  ...(必须恰好 ' + str(n) + ' 项,且 image_index 与输入一一对应)')
    lines.append(']')
    lines.append("")
    lines.append("【字段说明】")
    lines.append("- score: 0-10 浮点(保留 1 位小数即可)。低于 5 视为可被裁掉。")
    lines.append("- reason: 中文一句话(≤ 30 字)。")
    lines.append("- recommended_section: opening / intro / method / results / none 五选一。")
    lines.append("- rejected: 是否裁掉(score < 5 或公式图请置 true)。")
    lines.append("")
    lines.append("仅输出一个 ```json ... ``` 代码块,不加任何前后说明文字。")
    return "\n".join(lines)


def _run_opencode_rate(prompt_text: str, opencode_model: str,
                       timeout_sec: int = 240) -> str:
    """调 ``opencode run -m <model> -`` (pipe 模式) — P3 wrapper。

    LESSONS 2026-04-27: 必须显式 ``cd cache_dir + export PATH=/usr/local/bin:$PATH``,
    防 conda env 老 node 污染。prompt 走 stdin pipe (避免 ``$(cat)`` 命令行展开)。
    失败 / timeout / FileNotFound 一律返回空串,不抛异常。
    """
    if not opencode_model:
        logging.warning("[llm.cli/rate-images] opencode_model 未配置,跳过")
        return ""

    cache_dir = os.path.join(_project_root(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    prompt_file = os.path.join(cache_dir, "_image_rating_prompt.txt")
    wrapper = os.path.join(cache_dir, "_image_rating_wrap.sh")

    try:
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        with open(wrapper, "w", encoding="utf-8") as wf:
            wf.write("#!/bin/bash\n")
            wf.write("export PATH=/usr/local/bin:$PATH\n")
            wf.write('cd "{c}"\n'.format(c=cache_dir))
            wf.write('cat "{p}" | opencode run -m {m} -\n'.format(
                p=prompt_file, m=opencode_model))
        os.chmod(wrapper, 0o755)
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli/rate-images] 写 wrapper 失败: %s", e)
        return ""

    env = os.environ.copy()
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)

    try:
        r = subprocess.run(
            ["bash", wrapper], capture_output=True, text=True,
            timeout=timeout_sec, env=env, cwd=cache_dir,
        )
        out = r.stdout or r.stderr or ""
    except subprocess.TimeoutExpired:
        logging.warning("[llm.cli/rate-images] opencode timeout after %ds", timeout_sec)
        return ""
    except FileNotFoundError as e:
        logging.warning("[llm.cli/rate-images] opencode 找不到: %s", e)
        return ""
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli/rate-images] opencode run 失败: %s", e)
        return ""

    out = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out or "")
    return out


def _parse_rate_images_json(raw: str) -> Optional[list]:
    """从 opencode/LLM 输出中抽 JSON 数组,失败返回 None。"""
    if not raw:
        return None
    s = raw.strip()
    # 先围栏 json 块
    m = re.search(r"```json\s*\n(.*?)\n```", s, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, list):
                return obj
        except json.JSONDecodeError:
            pass
    # 再普通围栏
    m = re.search(r"```\s*\n(.*?)\n```", s, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, list):
                return obj
        except json.JSONDecodeError:
            pass
    # 最后裸 [...]
    m = re.search(r"\[\s*\{.*?\}\s*\]", s, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group())
            if isinstance(obj, list):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _normalize_score_record(rec: dict, candidate: dict) -> dict:
    """把单条 score 记录规整为标准 schema(补缺省字段、夹钳分数到 0-10)。

    candidate 用于 fallback caption / image_index。
    """
    if not isinstance(rec, dict):
        rec = {}
    if not isinstance(candidate, dict):
        candidate = {}
    idx = rec.get("image_index")
    if not isinstance(idx, int):
        idx = candidate.get("image_index")
    if not isinstance(idx, int):
        try:
            idx = int(idx)
        except Exception:
            idx = 0
    cap = rec.get("caption") or candidate.get("caption") or ""
    try:
        score = float(rec.get("score", 5))
    except Exception:
        score = 5.0
    score = max(0.0, min(10.0, score))
    sec = (rec.get("recommended_section") or "method").strip().lower()
    if sec not in _VALID_SECTIONS:
        sec = "method"
    reason = str(rec.get("reason") or "").strip()
    rejected = bool(rec.get("rejected", score < 5))
    return {
        "image_index": int(idx),
        "caption": str(cap)[:500],
        "score": round(float(score), 2),
        "reason": reason[:200],
        "recommended_section": sec,
        "rejected": bool(rejected),
    }


def _enforce_formula_constraint(record: dict, candidate: dict) -> dict:
    """硬约束: caption 命中公式关键词 → score ≤ 3, section=none, rejected=True。

    双重保险(prompt + 代码层都 enforce, LESSONS 教训)。
    """
    cap_pool = " ".join([
        str(record.get("caption") or ""),
        str(candidate.get("caption") or "") if isinstance(candidate, dict) else "",
    ])
    if _is_formula_caption(cap_pool):
        if record.get("score", 0) > 3:
            record["score"] = 3.0
        record["recommended_section"] = "none"
        record["rejected"] = True
        if not record.get("reason"):
            record["reason"] = "公式/约束截图,不适合长时间画面展示"
    return record


def _fallback_default_scores(candidates: list) -> list:
    """opencode/LLM 全失败时,返回每张图固定 5 分 + 按 figure_role 简单分流。"""
    out = []
    for c in candidates:
        if not isinstance(c, dict):
            c = {}
        cap = c.get("caption") or ""
        role = (c.get("figure_role") or "").strip().lower()
        if role in ("opening",):
            sec = "opening"
        elif role in ("intro", "background", "motivation"):
            sec = "intro"
        elif role in ("method", "architecture", "framework"):
            sec = "method"
        elif role in ("results", "experiments", "ablation"):
            sec = "results"
        else:
            sec = "method"
        rec = {
            "image_index": c.get("image_index", 0),
            "caption": cap,
            "score": 5.0,
            "reason": "fallback default(opencode/LLM 不可用)",
            "recommended_section": sec,
            "rejected": False,
        }
        out.append(_enforce_formula_constraint(rec, c))
    return out


def _fallback_plain_llm_rate(prompt_text: str) -> str:
    """opencode 失败时,尝试用 plain LLM 单次调用。"""
    try:
        from src.llm_tools.llm_agent import create_chat_completion
        return create_chat_completion(prompt_text, max_tokens=4096) or ""
    except Exception as e:  # noqa: BLE001
        logging.warning("[llm.cli/rate-images] plain LLM fallback 失败: %s", e)
        return ""


def _rate_images_via_opencode(candidates: list, target_count: int,
                              opencode_model: str) -> list:
    """主流程: 先 opencode pipe → 失败兜底 plain LLM → 最后默认 5 分骨架。

    返回与 candidates 等长的 score 记录列表;永不抛异常。
    公式图硬约束在所有路径上都 enforce(双重保险)。
    """
    if not isinstance(candidates, list) or not candidates:
        return []

    prompt = _build_rate_images_prompt(candidates, int(target_count or len(candidates)))

    parsed: Optional[list] = None
    raw1 = _run_opencode_rate(prompt, opencode_model)
    parsed = _parse_rate_images_json(raw1)
    if not isinstance(parsed, list) or not parsed:
        logging.warning("[llm.cli/rate-images] opencode path 失败,fallback to plain LLM")
        raw2 = _fallback_plain_llm_rate(prompt)
        parsed = _parse_rate_images_json(raw2)

    # 转 dict 索引方便对齐
    by_idx = {}
    if isinstance(parsed, list):
        for r in parsed:
            if not isinstance(r, dict):
                continue
            try:
                by_idx[int(r.get("image_index", -1))] = r
            except Exception:
                continue

    out = []
    for c in candidates:
        if not isinstance(c, dict):
            c = {}
        idx = c.get("image_index", 0)
        try:
            idx_int = int(idx)
        except Exception:
            idx_int = 0
        rec = by_idx.get(idx_int) or {}
        normalized = _normalize_score_record(rec, c)
        # caption 缺失时用 candidate 的填补
        if not normalized.get("caption"):
            normalized["caption"] = c.get("caption") or ""
        normalized = _enforce_formula_constraint(normalized, c)
        out.append(normalized)

    # 如果完全没拿到任何评分(全部 fallback 5 分),走更保守的默认骨架
    if not by_idx:
        logging.error("[llm.cli/rate-images] opencode + plain LLM 均失败,使用默认骨架")
        return _fallback_default_scores(candidates)

    return out


def _run_rate_images(args) -> int:
    if not os.path.isfile(args.candidates):
        _print_json({"ok": False, "error": "candidates file not found: %s" % args.candidates})
        return 1
    try:
        with open(args.candidates, "r", encoding="utf-8") as f:
            candidates = json.load(f)
    except Exception as e:  # noqa: BLE001
        _print_json({"ok": False, "error": "candidates parse failed: %s: %s" % (type(e).__name__, e)})
        return 1
    if not isinstance(candidates, list):
        _print_json({"ok": False, "error": "candidates must be JSON list"})
        return 1
    if not candidates:
        # 空列表也算成功(写空数组)
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            _print_json({"ok": False, "error": "write out failed: %s: %s" % (type(e).__name__, e)})
            return 1
        _print_json({"ok": True, "scored": 0, "above_5": 0})
        return 0

    target_count = int(args.target_count or 8)
    opencode_model = _resolve_opencode_model(args.opencode_model)

    scores = _rate_images_via_opencode(candidates, target_count, opencode_model)

    out_path = args.out
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        _print_json({"ok": False, "error": "write out failed: %s: %s" % (type(e).__name__, e)})
        return 1

    above_5 = sum(1 for s in scores if isinstance(s, dict) and float(s.get("score", 0)) >= 5)
    _print_json({"ok": True, "scored": len(scores), "above_5": int(above_5)})
    return 0


_DISPATCH = {
    "generate-plan": _run_generate_plan,
    "rate-images": _run_rate_images,
}


def main(argv: Optional[list] = None) -> int:
    _setup_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    _apply_network_workarounds_safe()

    handler = _DISPATCH.get(args.cmd)
    if handler is None:
        _print_json({"ok": False, "error": "unknown cmd: %s" % args.cmd})
        return 1
    try:
        return handler(args)
    except Exception as e:  # noqa: BLE001
        logging.exception("[llm.cli] %s crashed", args.cmd)
        _print_json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
