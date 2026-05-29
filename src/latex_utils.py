"""LaTeX 公式工具模块（feature: latex_utils）。

从 arxiv LaTeX 源码抽取行间公式环境，并在 manim 渲染 MathTex 前做预编译校验，
把语法错误的公式提前拦下来降级，避免炸掉整条讲解视频。

对外两个入口:
    - `extract_equations(tex_source, max_n=8)`: 抽行间公式体，去重保序，最多 max_n 个。
    - `validate_latex(latex, timeout=15)`: 用子进程 latex 试编译一段公式体，
      成功 True / 失败 / 超时一律 False（绝不抛异常）。

校验链路与 manim 一致: latex -> dvi（standalone[preview] + amsmath/amssymb），
而非 pdflatex。

环境变量 `JSR_DISABLE_LATEX_VALIDATE=1` 可跳过 validate_latex 的真编译（信任输入直接 True），
仿照本项目 `JSR_DISABLE_LATEX_SOURCE` 等惯例，便于调试。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from typing import List

logger = logging.getLogger(__name__)


# ============================================================
# S1: 行间公式抽取
# ============================================================

# 需要抽取的行间公式环境名（含带 * 变体）。eqnarray 较老但仍常见。
_EQ_ENV_NAMES = (
    "equation", "align", "gather", "multline", "eqnarray",
)
# \begin{env}...\end{env}，env 取上述名字（可带 *）。命名组 body = 环境内部公式体。
# 用命名组 (?P<env>...) + 反向引用 (?P=env) 绑定 begin/end 必须同名，
# 同理 (?P<star>) + (?P=star) 绑定星号变体一致，
# 防止 \begin{align}...\end{equation} / \begin{align*}...\end{align} 跨名/跨星号误匹配。
# 公式体统一放在命名组 body（最后一个捕获组），下方 finditer 按 m.group(m.re.groups) 取末组。
_EQ_ENV_RE = re.compile(
    r"\\begin\s*\{\s*(?P<env>"
    + "|".join(re.escape(n) for n in _EQ_ENV_NAMES)
    + r")(?P<star>\*?)\s*\}(?P<body>.*?)\\end\s*\{\s*(?P=env)(?P=star)\s*\}",
    re.DOTALL,
)
# \[ ... \] 行间公式。捕获组 1 = 公式体。
_BRACKET_RE = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)
# $$ ... $$ 行间公式。捕获组 1 = 公式体。
_DOLLAR_RE = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)


def extract_equations(tex_source: str, max_n: int = 8) -> List[str]:
    """从 LaTeX 源码抽取行间公式环境，返回 LaTeX 字符串列表（去重、按出现顺序，最多 max_n 个）。

    抽取范围:
      - \\begin{equation}...\\end{equation} 及 equation* / align / align* / gather / gather*
        / multline / multline* / eqnarray / eqnarray*
      - \\[ ... \\] 行间公式
      - $$ ... $$ 行间公式
    不抽取行内 $...$（太碎，噪音大）。

    返回的字符串是环境内部的公式体（去掉 \\begin/\\end 包裹和外层 $$ / \\[ \\]），strip 后的纯公式。
    去重: 内容 strip 后完全相同的只保留第一个。

    Args:
        tex_source: 已展开宏 / \\input 的 LaTeX 源码文本。
        max_n: 最多返回的公式数量。

    Returns:
        公式体字符串列表，按在源码中出现的先后排序，去重，长度 <= max_n。
    """
    if not tex_source:
        return []

    # 收集 (起始偏移, 公式体)，最后统一按偏移排序，保证跨环境/跨语法的整体出现顺序。
    found = []  # type: List[tuple]
    for regex in (_EQ_ENV_RE, _BRACKET_RE, _DOLLAR_RE):
        for m in regex.finditer(tex_source):
            # 公式体统一取该正则的最后一个捕获组：
            # _EQ_ENV_RE 用了 env/star 命名组，body 是末组；另两个正则 body 即组 1。
            body = m.group(m.re.groups).strip()
            if body:
                found.append((m.start(), body))

    found.sort(key=lambda item: item[0])

    seen = set()
    result = []  # type: List[str]
    for _, body in found:
        if body in seen:
            continue
        seen.add(body)
        result.append(body)
        if len(result) >= max_n:
            break
    return result


# ============================================================
# S2: 公式预编译校验
# ============================================================

# 公式体若已自带行间环境，则不再外套 align*，避免环境嵌套报错。
_HAS_ENV_RE = re.compile(
    r"\\begin\s*\{\s*(?:equation|align|gather|multline|eqnarray|array|cases|split|aligned)\s*\*?\s*\}",
    re.IGNORECASE,
)

_PREAMBLE = (
    "\\documentclass[preview]{standalone}\n"
    "\\usepackage{amsmath,amssymb}\n"
)


def _build_document(latex: str) -> str:
    """把公式体包成最小 standalone 文档。

    - 已含行间环境（equation/align/...）: 直接裸放，不外套，避免嵌套。
    - 否则: 包进 \\begin{align*} ... \\end{align*}（manim 同款数学环境）。
    """
    body = latex.strip()
    if _HAS_ENV_RE.search(body):
        content = body
    else:
        content = "\\begin{align*}\n" + body + "\n\\end{align*}"
    return _PREAMBLE + "\\begin{document}\n" + content + "\n\\end{document}\n"


def validate_latex(latex: str, timeout: int = 15) -> bool:
    """把一段公式体写进最小 standalone LaTeX 文档，用子进程 latex 试编译。

    成功返回 True，失败 / 超时 / 任何异常一律返回 False（绝不抛异常）。

    实现要点:
      - kill switch: `JSR_DISABLE_LATEX_VALIDATE=1` 时直接返回 True（信任输入，跳过真编译）。
      - 临时目录用 tempfile.TemporaryDirectory，用完自动清理，不污染项目目录。
      - preamble 与 manim 同款: standalone[preview] + amsmath,amssymb。
        公式体已含 align/equation 等环境则裸放，否则外套 \\begin{align*}...\\end{align*}。
      - 调用 `latex -interaction=nonstopmode -halt-on-error`（走 latex->dvi 链路，
        与 manim 一致，而非 pdflatex），returncode == 0 且生成 .dvi 才算成功。

    Args:
        latex: 待校验的公式体（环境内部的纯公式，如 "E = mc^2"）。
        timeout: 子进程编译超时（秒）。

    Returns:
        编译成功 True；语法错误 / 超时 / latex 不可用 / 其他异常 False。
    """
    if os.environ.get("JSR_DISABLE_LATEX_VALIDATE") == "1":
        return True

    if not latex or not latex.strip():
        return False

    try:
        with tempfile.TemporaryDirectory(prefix="jsr_latex_") as tmp_dir:
            tex_path = os.path.join(tmp_dir, "eq.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(_build_document(latex))

            proc = subprocess.run(
                ["latex", "-interaction=nonstopmode", "-halt-on-error", "eq.tex"],
                cwd=tmp_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            dvi_path = os.path.join(tmp_dir, "eq.dvi")
            ok = proc.returncode == 0 and os.path.exists(dvi_path)
            if not ok:
                logger.info("[latex_utils] validate failed for: %s", latex.strip()[:60])
            return ok
    except subprocess.TimeoutExpired:
        logger.info("[latex_utils] validate timeout for: %s", latex.strip()[:60])
        return False
    except FileNotFoundError:
        logger.info("[latex_utils] latex binary not found; validate -> False")
        return False
    except Exception as exc:  # noqa: BLE001 — 校验失败一律 fallback 不抛
        logger.info("[latex_utils] validate error %r for: %s", exc, latex.strip()[:60])
        return False
