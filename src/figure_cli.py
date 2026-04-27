"""Figure analysis CLI — opencode skill 的命令行入口 (P2)。

子命令:
- ``analyze-figure``  对论文方法图做多轮 reasoning, 输出 figure_analyzer 兼容 JSON。

opencode 的 deepseek-v4-pro 不支持图像直输, 但 opencode 可以多轮拆解维度。
本 CLI 通过传入 ``--paper-context`` (caption/abstract) + 三轮分维度 reasoning,
让 opencode 推断方法图结构, 输出与 ``src.figure_analyzer`` schema 兼容的 JSON,
后续由 ``EditBanana / SAM3 / arxiv_latex`` 路径补 bbox/坐标。

统一 JSON 输出: ``{"ok": bool, "out": str, "components": int, "connections": int}``,
失败 ``ok=False``, exit code 1, 错误摘要写 ``error`` 字段。

调用前自动 ``apply_network_workarounds()`` (幂等)。

Bash 例子::

    python -m src.figure_cli analyze-figure \\
        --image cache/arxiv_src/2506.15953/img/arch.png \\
        --paper-context "ViTacFormer cross-modal transformer ..." \\
        --out /tmp/analysis.json \\
        --opencode-model deepseek/deepseek-v4-pro
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


logger = logging.getLogger("figure_cli")


# ============================================================
# opencode 调用工具
# ============================================================

def _resolve_opencode_bin() -> str:
    """返回 opencode 可执行文件路径; 缺失返回 \"opencode\" (PATH 兜底)。"""
    return os.environ.get("OPENCODE_BIN", "opencode")


def _resolve_default_model() -> str:
    """读 config.yaml 的 opencode_model 作为默认; 兜底 deepseek/deepseek-v4-pro。"""
    try:
        import yaml
        cfg_path = os.path.join(_repo_root(), "config.yaml")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            m = data.get("opencode_model") or ""
            if m:
                return str(m)
    except Exception:
        pass
    return "deepseek/deepseek-v4-pro"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_opencode_round(prompt: str, model: str, timeout: int = 180) -> str:
    """单轮 opencode 调用 (pipe 模式 via wrapper bash), 返回 stdout 文本。

    抄自 ``paper_discovery._run_opencode_with_pipe`` 同款 pattern:
    - prompt 写到 ``cache/_figure_skill_prompt.txt`` (避免 ``$(cat)`` 命令行展开卡死)
    - wrapper bash ``cache/_figure_skill_wrap.sh`` 显式 ``export PATH=/usr/local/bin:$PATH``
      规避 conda env 内陈旧 node v6 shadow 系统 v20 的问题。
    - opencode 不走系统 HTTP 代理 (与 manim_engine / paper_discovery 一致)。

    失败 (rc != 0 / timeout / FileNotFound) 抛 RuntimeError, 由调用方 catch。
    """
    cache_dir = os.path.join(_repo_root(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    prompt_file = os.path.join(cache_dir, "_figure_skill_prompt.txt")
    wrapper = os.path.join(cache_dir, "_figure_skill_wrap.sh")

    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt)
    with open(wrapper, "w", encoding="utf-8") as wf:
        wf.write("#!/bin/bash\n")
        wf.write("export PATH=/usr/local/bin:$PATH\n")
        wf.write('cat "{p}" | opencode run -m {m} -\n'.format(
            p=prompt_file, m=model))
    os.chmod(wrapper, 0o755)

    env = os.environ.copy()
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)

    try:
        proc = subprocess.run(
            ["bash", wrapper],
            capture_output=True, text=True,
            timeout=timeout, env=env, cwd=_repo_root(),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("opencode timeout after %ds" % timeout)

    if proc.returncode != 0:
        raise RuntimeError(
            "opencode rc=%d stderr=%s" % (proc.returncode, (proc.stderr or "")[:200])
        )

    # 去 ANSI 控制符 (opencode 输出含彩色)
    out = proc.stdout or ""
    out = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out)
    return out


# ============================================================
# JSON 提取
# ============================================================

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(\{.*?\}|\[.*?\])\s*\n?```", re.DOTALL)
_BARE_OBJ_RE = re.compile(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", re.DOTALL)


def _extract_json(text: str) -> Optional[object]:
    """从 opencode 输出中提取 JSON object/array; 找不到返回 None。"""
    if not text:
        return None
    # 优先围栏块
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 回退裸 JSON: 尝试找最长 {...} 或 [...]
    # 数组优先
    for opener, closer in [("[", "]"), ("{", "}")]:
        s = text.find(opener)
        e = text.rfind(closer)
        if s >= 0 and e > s:
            try:
                return json.loads(text[s : e + 1])
            except json.JSONDecodeError:
                continue
    return None


# ============================================================
# 三轮 reasoning prompts
# ============================================================

# 注: prompt 里的 JSON 花括号必须双写, 因为后面会用 .format(...) 注入 paper_context;
# 如果改用 f-string 或 字符串拼接, 就不需要双写。这里我们用拼接, 保持单花括号即可。

def _build_round1_prompt(image_path: str, paper_context: str) -> str:
    """第 1 轮: 列出主要模块。"""
    rel = os.path.relpath(image_path, _repo_root())
    return (
        "你是学术论文图像分析专家。我无法直接给你看图,\n"
        "但你可以参考论文上下文 + 图片路径来推断这张方法/架构图里的主要模块。\n\n"
        "图片路径 (相对仓库根): " + rel + "\n"
        "论文背景:\n" + (paper_context or "(无)")[:2000] + "\n\n"
        "请基于论文方法描述, 列出该方法图最可能包含的 5-10 个核心模块。\n"
        "对每个模块给出:\n"
        "- name: 英文短名 (CamelCase 或全大写, 与论文术语一致)\n"
        "- chinese_name: 中文短名 (≤ 8 字)\n"
        "- type: module / layer / block / input / output / loss / data / operation 之一\n"
        "- description: 1 句话功能说明 (≤ 30 字)\n\n"
        "严格输出 JSON 数组 (允许 markdown 代码块包裹), 例如:\n"
        "```json\n"
        "[\n"
        "  {\"name\": \"VisualEncoder\", \"chinese_name\": \"视觉编码器\",\n"
        "   \"type\": \"module\", \"description\": \"提取 RGB 特征\"}\n"
        "]\n"
        "```\n"
        "禁止输出其他解释。"
    )


def _build_round2_prompt(image_path: str, paper_context: str,
                          components: list) -> str:
    """第 2 轮: 推断模块之间的连接 / 数据流向。"""
    names = [str(c.get("name", "")) for c in components if c.get("name")]
    rel = os.path.relpath(image_path, _repo_root())
    return (
        "继续分析这张方法图。已识别的模块:\n"
        + ", ".join(names) + "\n\n"
        "图片路径 (相对仓库根): " + rel + "\n"
        "论文背景:\n" + (paper_context or "(无)")[:1200] + "\n\n"
        "请列出模块之间的连接关系 (数据流, 箭头), 每条给出:\n"
        "- from: 起始模块 name (必须在已识别列表中)\n"
        "- to:   目标模块 name (必须在已识别列表中)\n"
        "- label: 连接上的标注 (如 \"z\" / \"action\" / \"\" 空字符串都行)\n"
        "- type: arrow / bidirectional / dashed / data_flow 之一\n"
        "- description: 该连接含义 (≤ 25 字)\n\n"
        "严格输出 JSON 数组, 例如:\n"
        "```json\n"
        "[\n"
        "  {\"from\": \"Encoder\", \"to\": \"Decoder\", \"label\": \"z\",\n"
        "   \"type\": \"arrow\", \"description\": \"潜变量传递\"}\n"
        "]\n"
        "```\n"
        "禁止输出其他解释。"
    )


def _build_round3_prompt(image_path: str, paper_context: str,
                          components: list, connections: list) -> str:
    """第 3 轮: 推断 high-level 字段 (核心创新 / 数据流描述 / 动画顺序)。"""
    n_c = len(components)
    n_conn = len(connections)
    return (
        "继续分析这张方法图。已得到 " + str(n_c) + " 个模块, "
        + str(n_conn) + " 条连接。\n\n"
        "论文背景:\n" + (paper_context or "(无)")[:1200] + "\n\n"
        "请补全方法图的高层字段, 严格输出 JSON 对象:\n"
        "```json\n"
        "{\n"
        "  \"figure_type\": \"architecture\",\n"
        "  \"layout_direction\": \"left-to-right\",\n"
        "  \"key_innovation\": \"该图核心创新点 (1-2 句, ≤ 60 字)\",\n"
        "  \"data_flow\": \"图中数据整体流向 (2-3 句, ≤ 100 字)\",\n"
        "  \"animation_suggestion\": \"建议的 manim 动画顺序 (按数据流逐步展示)\",\n"
        "  \"has_neural_network\": true,\n"
        "  \"nn_layers\": [\"transformer\", \"attention\"]\n"
        "}\n"
        "```\n"
        "字段说明:\n"
        "- figure_type: architecture / pipeline / flowchart / network / comparison / results\n"
        "- layout_direction: left-to-right / top-to-bottom / mixed / radial\n"
        "- has_neural_network: true / false\n"
        "- nn_layers: 仅在 has_neural_network=true 时给, 列出层类型: conv/fc/attention/transformer/mlp/embedding/pooling/norm\n\n"
        "禁止输出其他解释。"
    )


# ============================================================
# 三轮编排
# ============================================================

def _analyze_via_opencode(image_path: str, paper_context: str,
                           opencode_model: str = "",
                           round_timeout: int = 180) -> dict:
    """3 轮 reasoning, 合并为 figure_analyzer 兼容 schema。"""
    model = opencode_model or _resolve_default_model()

    # Round 1: components
    components: list = []
    try:
        out1 = _run_opencode_round(_build_round1_prompt(image_path, paper_context),
                                   model=model, timeout=round_timeout)
        parsed = _extract_json(out1)
        if isinstance(parsed, list):
            components = [c for c in parsed if isinstance(c, dict)]
    except Exception as e:
        logger.warning("[figure_cli] round1 失败: %s", e)

    # 兜底默认
    if not components:
        components = [
            {"name": "Input", "chinese_name": "输入", "type": "input",
             "description": "输入数据"},
            {"name": "MainModule", "chinese_name": "主模块", "type": "module",
             "description": "核心计算"},
            {"name": "Output", "chinese_name": "输出", "type": "output",
             "description": "输出结果"},
        ]

    # 标准化 component 字段 (补 position / color / shape 兜底)
    for c in components:
        c.setdefault("position", "center")
        c.setdefault("color", "blue")
        c.setdefault("shape", "rectangle")
        c.setdefault("size", "medium")
        c.setdefault("children", [])
        c.setdefault("description", "")
        c.setdefault("chinese_name", c.get("name", ""))
        c.setdefault("type", "module")

    # Round 2: connections
    connections: list = []
    try:
        out2 = _run_opencode_round(
            _build_round2_prompt(image_path, paper_context, components),
            model=model, timeout=round_timeout,
        )
        parsed = _extract_json(out2)
        if isinstance(parsed, list):
            connections = [c for c in parsed if isinstance(c, dict)]
    except Exception as e:
        logger.warning("[figure_cli] round2 失败: %s", e)

    # 标准化 connection 字段
    valid_names = {c.get("name", "") for c in components}
    cleaned_conn = []
    for c in connections:
        fr = str(c.get("from", "") or "")
        to = str(c.get("to", "") or "")
        if not fr or not to:
            continue
        # 容错: 不在 components 中也保留, 不强校验
        c.setdefault("label", "")
        c.setdefault("type", "arrow")
        c.setdefault("description", "")
        cleaned_conn.append(c)
    connections = cleaned_conn

    # Round 3: high-level 字段
    high: dict = {}
    try:
        out3 = _run_opencode_round(
            _build_round3_prompt(image_path, paper_context, components, connections),
            model=model, timeout=round_timeout,
        )
        parsed = _extract_json(out3)
        if isinstance(parsed, dict):
            high = parsed
    except Exception as e:
        logger.warning("[figure_cli] round3 失败: %s", e)

    # 合并 (与 figure_analyzer schema 兼容)
    analysis = {
        "figure_type": str(high.get("figure_type", "architecture") or "architecture"),
        "layout_direction": str(high.get("layout_direction", "left-to-right") or "left-to-right"),
        "components": components,
        "connections": connections,
        "data_flow": str(high.get("data_flow", "") or ""),
        "key_innovation": str(high.get("key_innovation", "") or ""),
        "animation_suggestion": str(high.get("animation_suggestion", "") or ""),
        "has_neural_network": bool(high.get("has_neural_network", False)),
        "nn_layers": list(high.get("nn_layers", []) or []),
        "source": "vision_skill",
        "has_precise_bbox": False,
    }
    return analysis


# ============================================================
# CLI 入口
# ============================================================

def _print_json(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _setup_logging() -> None:
    """CLI 默认 WARNING 走 stderr, 避免污染 stdout JSON。"""
    logging.basicConfig(
        level=logging.WARNING,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _apply_network_workarounds_safe() -> None:
    try:
        try:
            from src.env_setup import apply_network_workarounds
        except ImportError:
            from env_setup import apply_network_workarounds  # type: ignore
        apply_network_workarounds()
    except Exception as e:
        logging.warning("[figure_cli] apply_network_workarounds failed: %s", e)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="figure-cli",
        description="Figure analysis CLI: 3-round opencode reasoning -> JSON",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "analyze-figure",
        help="3 轮 reasoning 分析方法图, 输出 figure_analyzer 兼容 JSON",
    )
    p.add_argument("--image", required=True, help="图片文件路径 (绝对或相对仓库根)")
    p.add_argument("--paper-context", default="",
                   help="论文上下文 (caption / abstract / method paragraph)")
    p.add_argument("--out", required=True, help="输出 JSON 路径")
    p.add_argument("--opencode-model", default="",
                   help="opencode 模型, 缺省读 config.yaml: opencode_model")
    p.add_argument("--round-timeout", type=int, default=180,
                   help="单轮 opencode 超时 (秒, 默认 180)")
    return parser


def main(argv: Optional[list] = None) -> int:
    _setup_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    _apply_network_workarounds_safe()

    if args.cmd != "analyze-figure":
        _print_json({"ok": False, "error": "unknown cmd: %s" % args.cmd})
        return 1

    image_path = args.image
    if not os.path.isabs(image_path):
        image_path = os.path.abspath(os.path.join(os.getcwd(), image_path))

    if not os.path.exists(image_path):
        _print_json({"ok": False,
                     "error": "image not found: %s" % image_path})
        return 1

    try:
        analysis = _analyze_via_opencode(
            image_path=image_path,
            paper_context=args.paper_context or "",
            opencode_model=args.opencode_model or "",
            round_timeout=int(args.round_timeout),
        )
    except Exception as e:
        logger.exception("[figure_cli] analyze failed")
        _print_json({"ok": False,
                     "error": "%s: %s" % (type(e).__name__, e)})
        return 1

    out_path = args.out
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _print_json({"ok": False,
                     "error": "write out failed: %s" % e})
        return 1

    payload = {
        "ok": True,
        "out": out_path,
        "components": len(analysis.get("components", []) or []),
        "connections": len(analysis.get("connections", []) or []),
    }
    _print_json(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
