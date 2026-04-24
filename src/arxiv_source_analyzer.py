"""arxiv LaTeX 源码直读路径（feature: arxiv_source_analyzer）。

给定 arxiv_id, 下载 tarball -> 解压 -> 识别主 tex -> 展开 \\input/\\include 与用户宏
-> 提取 \\begin{figure} 环境 -> 解析 TikZ / 或走 raster + pdflatex 兜底
-> 输出与 figure_analyzer._merge_analyses 同 schema 的 dict。

对外唯一入口: `try_structured_figure(arxiv_id, method_image_path, cache_root, paper_context)`
任何错误都返回 None（不抛异常），由上游 front-door 回退到 SAM3+VL。

环境变量 `JSR_DISABLE_LATEX_SOURCE=1` 可在 `analyze_and_prepare` 前禁用 front-door。

缓存布局:
    {cache_root}/arxiv_src/<aid>.tar.gz
    {cache_root}/arxiv_src/<aid>/
        main.tex, figs/, sections/
        .compiled.pdf (可选, pdflatex 产物)
        .manifest.json
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# 单个图 tarball 最大解压大小（防 zip-bomb）
DEFAULT_MAX_MB = 50
# pdflatex 编译超时
DEFAULT_COMPILE_TIMEOUT = 120
# 主入口超时（用于 fetch）
DEFAULT_FETCH_TIMEOUT = 60


class SizeLimitError(Exception):
    """tarball 解压后超过 size 阈值。"""


# ============================================================
# S1: 下载 & 解压
# ============================================================

def fetch_source(aid: str, cache_root: str, timeout: int = DEFAULT_FETCH_TIMEOUT) -> str:
    """从 arxiv e-print 接口拉取 tarball, 存到 {cache_root}/arxiv_src/<aid>.tar.gz。

    D3: 锁定 latest, 不传 version。

    命中缓存直接返回路径;  不去做 304 / If-Modified-Since。
    """
    import requests

    aid = _strip_version(aid)
    src_root = os.path.join(cache_root, "arxiv_src")
    os.makedirs(src_root, exist_ok=True)
    tarball = os.path.join(src_root, f"{aid}.tar.gz")
    if os.path.exists(tarball) and os.path.getsize(tarball) > 0:
        logger.info("[arxiv_src] cache hit: %s", tarball)
        return tarball

    url = f"https://arxiv.org/e-print/{aid}"
    logger.info("[arxiv_src] fetching: %s", url)
    resp = requests.get(url, timeout=timeout, stream=True,
                        headers={"User-Agent": "JushenRenji/1.0 arxiv_source_analyzer"})
    resp.raise_for_status()

    tmp_path = tarball + ".partial"
    with open(tmp_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    os.replace(tmp_path, tarball)
    logger.info("[arxiv_src] saved: %s (%.1f KB)", tarball, os.path.getsize(tarball) / 1024)
    return tarball


def _strip_version(aid: str) -> str:
    """去除形如 v2 的版本后缀。"""
    return re.sub(r"v\d+$", "", aid.strip())


def extract_source(tarball_path: str, dst_dir: str, max_mb: int = DEFAULT_MAX_MB) -> str:
    """安全解压 tarball 到 dst_dir。

    - path traversal 防护 (检查 realpath 是否在 dst_dir 下)
    - size-limit 防护 (累计 member.size)
    - 支持 .tar.gz / .tar / 单个 .tex 裸文件 (arxiv 有时直接返回裸 tex)
    """
    os.makedirs(dst_dir, exist_ok=True)
    max_bytes = max_mb * 1024 * 1024

    # arxiv 有时 e-print 直接是裸 tex (不是 tarball), 先试 gzip+tar
    if not tarfile.is_tarfile(tarball_path):
        # 可能是 gzipped-single-file 或 raw tex
        try:
            import gzip
            with gzip.open(tarball_path, "rb") as gz:
                data = gz.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SizeLimitError(f"uncompressed size exceeds {max_mb} MB")
            # 猜测 tex 文件名
            target = os.path.join(dst_dir, "main.tex")
            with open(target, "wb") as f:
                f.write(data)
            logger.info("[arxiv_src] extracted single-file gzip -> %s", target)
            return dst_dir
        except Exception:
            # 最后尝试当作裸 tex 直接复制
            target = os.path.join(dst_dir, "main.tex")
            shutil.copy(tarball_path, target)
            logger.info("[arxiv_src] treated as raw tex -> %s", target)
            return dst_dir

    total = 0
    dst_real = os.path.realpath(dst_dir)
    with tarfile.open(tarball_path, "r:*") as tar:
        for member in tar.getmembers():
            # path traversal 检查: 解析目标实际路径, 必须在 dst_real 下
            member_target = os.path.realpath(os.path.join(dst_dir, member.name))
            if not (member_target == dst_real or member_target.startswith(dst_real + os.sep)):
                raise ValueError(
                    f"path traversal attempt: {member.name} -> {member_target}"
                )
            if member.isdir():
                continue
            total += max(0, member.size)
            if total > max_bytes:
                raise SizeLimitError(
                    f"tarball extracted size {total} > {max_bytes} ({max_mb} MB)"
                )
            tar.extract(member, dst_dir)
    logger.info("[arxiv_src] extracted: %s -> %s (%.1f KB)", tarball_path,
                dst_dir, total / 1024)
    return dst_dir


# ============================================================
# S2: 识别主 tex + resolve includes + 展开宏
# ============================================================

_DOCCLASS_RE = re.compile(r"\\documentclass\b")
_BEGIN_DOC_RE = re.compile(r"\\begin\s*\{\s*document\s*\}")

# 候选主文件名（按优先级排序）
_MAIN_TEX_CANDIDATES = (
    "main.tex", "paper.tex", "ms.tex", "manuscript.tex",
    "acl2024.tex", "arxiv.tex",
)


def find_main_tex(src_dir: str) -> Optional[str]:
    """识别主 tex 文件。

    策略（优先级从高到低）:
    1. 候选文件名命中（main.tex / paper.tex / ms.tex ...）
    2. 含 \\documentclass 且含 \\begin{document} 的唯一文件
    3. 只含 \\documentclass 的文件中, 体积最大的
    """
    if not os.path.isdir(src_dir):
        return None

    # 收集所有 .tex 文件
    tex_files = []
    for root, _, files in os.walk(src_dir):
        for fn in files:
            if fn.endswith(".tex"):
                tex_files.append(os.path.join(root, fn))
    if not tex_files:
        return None

    # 策略 1: 候选文件名
    for cand in _MAIN_TEX_CANDIDATES:
        for f in tex_files:
            if os.path.basename(f).lower() == cand:
                return f

    # 读取所有候选以判断 documentclass / begin{document}
    has_docclass = []
    has_begin_doc = []
    for f in tex_files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read(16384)  # 只读前 16KB, 足够判断
        except (OSError, IOError):
            continue
        if _DOCCLASS_RE.search(content):
            has_docclass.append(f)
            if _BEGIN_DOC_RE.search(content):
                has_begin_doc.append(f)

    # 策略 2: 唯一含 \documentclass + \begin{document}
    if len(has_begin_doc) == 1:
        return has_begin_doc[0]

    # 策略 3: 体积最大的含 documentclass 的文件
    if has_docclass:
        has_docclass.sort(key=lambda p: os.path.getsize(p), reverse=True)
        return has_docclass[0]

    # 最后兜底: 第一个 .tex
    return tex_files[0] if tex_files else None


_INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
_COMMENT_RE = re.compile(r"(?<!\\)%.*?$", re.MULTILINE)


def resolve_includes(main_tex_path: str, src_dir: str, depth: int = 5) -> str:
    """递归展开 \\input{...} \\include{...}。

    - 去除行注释（以 % 开头, 且 % 未被转义）
    - 循环引用深度截断（防 a.tex \\input{b}, b.tex \\input{a} 死循环）
    """
    if not os.path.exists(main_tex_path):
        return ""

    visited = set()

    def _expand(tex_path: str, cur_depth: int) -> str:
        if cur_depth <= 0:
            return ""
        real = os.path.realpath(tex_path)
        if real in visited:
            return ""
        visited.add(real)
        try:
            with open(tex_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (OSError, IOError):
            return ""

        # 去掉行注释
        content = _COMMENT_RE.sub("", content)

        def _sub(m):
            raw = m.group(1).strip()
            # \input{foo} 或 \input{foo.tex}
            candidates = [raw, raw + ".tex"]
            for c in candidates:
                p = os.path.normpath(os.path.join(src_dir, c))
                if os.path.exists(p):
                    return _expand(p, cur_depth - 1)
                # 也试相对 main_tex 所在目录
                p2 = os.path.normpath(os.path.join(os.path.dirname(tex_path), c))
                if os.path.exists(p2):
                    return _expand(p2, cur_depth - 1)
            # 找不到: 保留原指令
            return m.group(0)

        return _INPUT_RE.sub(_sub, content)

    return _expand(main_tex_path, depth)


# 用户宏: \newcommand{\foo}{body}  /  \def\foo{body}  (仅无参数版本)
_NEWCMD_RE = re.compile(
    r"\\(?:new|renew|provide)command\s*\*?\s*\{?\s*\\(\w+)\s*\}?\s*(?:\[\d+\])?\s*\{([^{}]*?)\}"
)
_DEF_RE = re.compile(r"\\def\s*\\(\w+)\s*\{([^{}]*?)\}")


def expand_user_macros(tex_str: str, max_iter: int = 5) -> str:
    """展开 \\newcommand 定义的无参数宏（简单版, 不处理带参数宏）。

    固定点迭代, 最多 max_iter 轮。
    """
    if not tex_str:
        return tex_str

    # 抽取所有宏定义
    macros = {}
    for m in _NEWCMD_RE.finditer(tex_str):
        macros[m.group(1)] = m.group(2)
    for m in _DEF_RE.finditer(tex_str):
        macros.setdefault(m.group(1), m.group(2))

    if not macros:
        return tex_str

    out = tex_str
    for _ in range(max_iter):
        changed = False
        for name, body in macros.items():
            # 匹配 \name 后接非字母字符（避免 \foo 匹配 \foobar）
            pat = re.compile(r"\\" + re.escape(name) + r"(?=[^a-zA-Z]|$)")
            new_out = pat.sub(lambda _m, _b=body: _b, out)
            if new_out != out:
                out = new_out
                changed = True
        if not changed:
            break
    return out


# ============================================================
# S3: 抽取 figure 环境
# ============================================================

_FIGURE_RE = re.compile(
    r"\\begin\s*\{\s*figure\*?\s*\}(.*?)\\end\s*\{\s*figure\*?\s*\}",
    re.DOTALL,
)
_CAPTION_RE = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*\{(.+?)\}\s*(?=\\|$)", re.DOTALL)
_LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")
_TIKZ_BEGIN_RE = re.compile(r"\\begin\s*\{\s*tikzpicture\s*\}", re.IGNORECASE)
_PGFPLOTS_BEGIN_RE = re.compile(r"\\begin\s*\{\s*axis\s*\}", re.IGNORECASE)
_INCLUDEGRAPHICS_RE = re.compile(
    r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
)


def extract_figure_envs(tex_str: str, src_dir: str) -> List[dict]:
    """从展开后的 tex 字符串里抽取所有 figure 环境。

    返回 list of dict:
        {
            "body": "<figure 内 raw body>",
            "caption": "<caption 文本>",
            "label": "<label>",
            "kind": "tikz" | "pgfplots" | "raster_pdf" | "raster_png" | "raster_eps",
            "source_path": "<若为 raster, 指向实际文件路径>"
        }
    """
    out = []
    for fig_match in _FIGURE_RE.finditer(tex_str):
        body = fig_match.group(1)
        cap_m = _CAPTION_RE.search(body)
        caption = _clean_text(cap_m.group(1)) if cap_m else ""
        label_m = _LABEL_RE.search(body)
        label = label_m.group(1).strip() if label_m else ""

        kind = None
        source_path = None

        if _TIKZ_BEGIN_RE.search(body):
            kind = "tikz"
        elif _PGFPLOTS_BEGIN_RE.search(body):
            kind = "pgfplots"
        else:
            # raster: 解 \includegraphics
            ig = _INCLUDEGRAPHICS_RE.search(body)
            if ig:
                raw_path = ig.group(1).strip()
                resolved = _resolve_graphics(raw_path, src_dir)
                if resolved:
                    ext = os.path.splitext(resolved)[1].lower()
                    if ext == ".pdf":
                        kind = "raster_pdf"
                    elif ext in (".png", ".jpg", ".jpeg"):
                        kind = "raster_png"
                    elif ext == ".eps":
                        kind = "raster_eps"
                    else:
                        kind = "raster_png"  # 默认当位图
                    source_path = resolved
                else:
                    # 找不到文件, 仍登记为 raster_pdf 让后续路径 B 尝试
                    kind = "raster_pdf"
                    source_path = raw_path

        if kind is None:
            # 图环境里既没 TikZ 也没 includegraphics, 跳过
            continue

        out.append({
            "body": body,
            "caption": caption,
            "label": label,
            "kind": kind,
            "source_path": source_path,
        })
    return out


def _clean_text(s: str) -> str:
    """去掉 LaTeX 命令, 保留普通文本（粗略版, 用于 caption 字符串）。"""
    # 去 \foo{...} / \foo -> 保留 ... 或丢弃
    s = re.sub(r"\\(?:label|cite|ref|cref|footnote)\s*\{[^}]*\}", "", s)
    s = re.sub(r"\\(?:textbf|textit|emph|texttt|textsc)\s*\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\s*\*?", "", s)  # 剩余命令
    s = re.sub(r"[{}]", "", s)
    return s.strip()


def _resolve_graphics(raw: str, src_dir: str) -> Optional[str]:
    """解析 \\includegraphics 路径到实际文件。

    尝试扩展名 .pdf / .png / .jpg / .jpeg / .eps, 以及相对 src_dir 子目录。
    """
    candidates = [raw, raw + ".pdf", raw + ".png", raw + ".jpg",
                  raw + ".jpeg", raw + ".eps"]
    # 直接路径
    for c in candidates:
        p = os.path.normpath(os.path.join(src_dir, c))
        if os.path.isfile(p):
            return p
    # 深搜 src_dir
    name_base = os.path.basename(raw)
    for root, _, files in os.walk(src_dir):
        for fn in files:
            if fn == name_base or fn.startswith(name_base + "."):
                return os.path.join(root, fn)
    return None


# ============================================================
# S3b: TikZ 结构解析（轻量, 不跑 pdflatex）
# ============================================================

# \node[options] (id) at (x,y) {label};  (选项、id、位置、label 都可能缺失)
_NODE_RE = re.compile(
    r"\\node\s*(?:\[([^\]]*)\])?\s*(?:\(([^)]+)\))?\s*"
    r"(?:at\s*\(([^)]+)\))?\s*\{(.*?)\}\s*;",
    re.DOTALL,
)
# \draw[options] (a) -> (b);  \draw[options] (a) -- (b);
_DRAW_RE = re.compile(
    r"\\draw\s*(?:\[([^\]]*)\])?\s*\(([^)]+)\)\s*(->|--|-\||<->|--\s*to)\s*\(([^)]+)\)\s*;",
    re.DOTALL,
)

# TikZ 颜色关键词映射
_TIKZ_COLOR_KEYWORDS = (
    "blue", "red", "green", "yellow", "orange", "purple", "cyan",
    "magenta", "gray", "black", "white", "pink", "brown", "olive",
    "violet", "teal",
)


def parse_tikz_structure(body: str, src_dir: str = None) -> Optional[dict]:
    """解析 TikZ body 为结构化组件/连接。

    Returns:
        {
            "components": [{"id","name","bbox_normalized","color","shape","position","size","type"}],
            "connections": [{"from","to","type","label"}],
            "canvas_size": [w_px, h_px],
            "layout_direction": "left-to-right" | "top-to-bottom" | "mixed",
        }
        任何异常或无节点时返回 None
    """
    try:
        components = []
        for idx, m in enumerate(_NODE_RE.finditer(body)):
            opts = m.group(1) or ""
            nid = (m.group(2) or f"n{idx}").strip()
            pos_str = (m.group(3) or "").strip()
            label_raw = m.group(4) or ""

            # 解析坐标
            x, y = _parse_tikz_coord(pos_str)

            # 颜色
            color = _extract_tikz_color(opts)
            # 形状
            shape = _extract_tikz_shape(opts)

            components.append({
                "id": nid,
                "raw_label": _clean_text(label_raw),
                "_x_cm": x,
                "_y_cm": y,
                "color": color,
                "shape": shape,
            })

        if not components:
            return None

        # 推导 bounding box（cm）
        xs = [c["_x_cm"] for c in components if c["_x_cm"] is not None]
        ys = [c["_y_cm"] for c in components if c["_y_cm"] is not None]
        if not xs or not ys:
            return None

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # 为了避免除 0, 加最小 span
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        # padding
        pad_x = span_x * 0.1 + 0.5
        pad_y = span_y * 0.1 + 0.5
        canvas_w_cm = span_x + 2 * pad_x
        canvas_h_cm = span_y + 2 * pad_y
        # cm -> px (72 px/cm 约定; 1 cm ≈ 72 px for our render)
        canvas_w_px = int(round(canvas_w_cm * 72))
        canvas_h_px = int(round(canvas_h_cm * 72))

        # 为每个 node 估算 bbox（默认方块大小 1.5cm x 0.8cm, 以 node 坐标为中心）
        for c in components:
            cx_cm = c["_x_cm"] if c["_x_cm"] is not None else (min_x + max_x) / 2
            cy_cm = c["_y_cm"] if c["_y_cm"] is not None else (min_y + max_y) / 2
            # 翻转 y（TikZ y 向上, bbox_normalized 约定 y 向下 [0,1]）
            # 注意: figure_analyzer 里 bbox_normalized 的 y 来自 EB 的 canvas 像素坐标
            # (y 向下); 这里保持同约定 -> y 向下归一化
            half_w_cm, half_h_cm = 0.75, 0.4
            x1 = (cx_cm - half_w_cm - (min_x - pad_x)) / canvas_w_cm
            x2 = (cx_cm + half_w_cm - (min_x - pad_x)) / canvas_w_cm
            # y 翻转: cy_cm 对应画布顶部偏下
            top_cm = max_y + pad_y
            y1 = (top_cm - cy_cm - half_h_cm) / canvas_h_cm
            y2 = (top_cm - cy_cm + half_h_cm) / canvas_h_cm
            c["bbox_normalized"] = [
                round(max(0.0, min(1.0, x1)), 3),
                round(max(0.0, min(1.0, y1)), 3),
                round(max(0.0, min(1.0, x2)), 3),
                round(max(0.0, min(1.0, y2)), 3),
            ]

        # connections
        connections = []
        for m in _DRAW_RE.finditer(body):
            _opts = m.group(1) or ""
            src = m.group(2).strip().split(".")[0].strip()
            arrow = m.group(3).strip()
            dst = m.group(4).strip().split(".")[0].strip()
            ctype = "arrow" if "->" in arrow or "to" in arrow else "line"
            if "<->" in arrow:
                ctype = "bidirectional"
            connections.append({
                "from": src,
                "to": dst,
                "type": ctype,
                "label": "",
                "description": "",
            })

        # 布局推断
        x_spread = max_x - min_x
        y_spread = max_y - min_y
        if x_spread > y_spread * 1.3:
            layout = "left-to-right"
        elif y_spread > x_spread * 1.3:
            layout = "top-to-bottom"
        else:
            layout = "mixed"

        return {
            "components": components,
            "connections": connections,
            "canvas_size": [canvas_w_px, canvas_h_px],
            "layout_direction": layout,
            "_canvas_cm": [canvas_w_cm, canvas_h_cm],
            "_bounds_cm": [min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y],
        }
    except Exception as e:
        logger.warning("parse_tikz_structure 失败: %s", e)
        return None


def _parse_tikz_coord(s: str) -> Tuple[Optional[float], Optional[float]]:
    """解析 TikZ 坐标字符串如 "0,0" / "1cm, 2cm" / "-2, 0.5"。"""
    if not s:
        return None, None
    # 去掉单位
    s = re.sub(r"(cm|mm|pt|em|ex|in)\b", "", s).strip()
    parts = s.split(",")
    if len(parts) < 2:
        return None, None
    try:
        x = float(parts[0].strip())
        y = float(parts[1].strip())
        return x, y
    except ValueError:
        return None, None


def _extract_tikz_color(opts: str) -> str:
    """从 TikZ 选项字符串提取颜色。支持 fill=blue!30, draw=red, color=green 等。"""
    if not opts:
        return "blue"
    m = re.search(r"(?:fill|draw|color)\s*=\s*(\w+)", opts)
    if m:
        name = m.group(1).lower()
        if name in _TIKZ_COLOR_KEYWORDS:
            return name
    # 单独出现的颜色关键词
    for kw in _TIKZ_COLOR_KEYWORDS:
        if re.search(rf"\b{kw}\b", opts):
            return kw
    return "blue"


def _extract_tikz_shape(opts: str) -> str:
    """从 TikZ 选项提取 shape。"""
    if not opts:
        return "rectangle"
    m = re.search(r"shape\s*=\s*(\w+)", opts)
    if m:
        raw = m.group(1).lower()
    else:
        raw = opts.lower()
    if "rounded" in raw or "rounded corners" in opts:
        return "rounded_rect"
    if "diamond" in raw:
        return "diamond"
    if "circle" in raw or "ellipse" in raw:
        return "circle"
    if "rectangle" in raw or "draw" in raw:
        return "rectangle"
    return "rectangle"


# ============================================================
# S4: 多图选择 —— LLM 按 caption 打分
# ============================================================

_SELECT_FIGURE_PROMPT = """你是学术论文分析专家。下面列出了一篇论文中所有 figure 环境的 caption。
请选出最能代表"论文方法/架构"的那一张（method figure）。
严格返回 JSON: {{"index": <0-based-int>, "reason": "<简短理由>"}}。

论文上下文（可选）:
{ctx}

Captions:
{caps}
"""


def select_main_figure_by_caption(specs: List[dict],
                                   paper_context: str = "") -> Optional[dict]:
    """从 figure specs 里选出最能代表"方法/架构"的一张。

    - 仅 1 个: 直接返回
    - >1: 调用 LLM (sdkish: dashscope.Generation 或 llm_agent) 返回 index
    - LLM 失败: 启发式兜底（选 caption 最长 / 含 "architecture/overview/framework/pipeline" 的）
    - 空列表: None
    """
    if not specs:
        return None
    if len(specs) == 1:
        return specs[0]

    caps = "\n".join(
        f"[{i}] {s.get('caption', '')[:240]}" for i, s in enumerate(specs)
    )
    ctx = (paper_context or "")[:1000]
    prompt = _SELECT_FIGURE_PROMPT.format(ctx=ctx, caps=caps)

    idx = None
    try:
        idx = _llm_select_figure_index(prompt, num_candidates=len(specs))
    except Exception as e:
        logger.warning("[arxiv_src] LLM 选图失败, 走启发式兜底: %s", e)

    if idx is None:
        idx = _heuristic_select_figure_index(specs)

    if idx is not None and 0 <= idx < len(specs):
        return specs[idx]
    return specs[0]


def _llm_select_figure_index(prompt: str, num_candidates: int) -> Optional[int]:
    """用 DashScope Generation 选 index。任何异常抛出由上层 catch。"""
    import dashscope
    from dashscope import Generation

    # 复用 figure_analyzer 配置
    try:
        from src.figure_analyzer import _get_config
    except ImportError:
        from figure_analyzer import _get_config  # type: ignore
    cfg = _get_config()
    api_key = cfg.get("dashscope_api_key", "")
    if api_key:
        dashscope.api_key = api_key

    resp = Generation.call(
        model="qwen-plus",
        messages=[{"role": "user", "content": prompt}],
        result_format="message",
    )
    if not resp or not getattr(resp, "output", None):
        return None
    text = resp.output.choices[0].message.content
    if isinstance(text, list):
        text = text[0].get("text", "") if text else ""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    try:
        obj = json.loads(text)
        idx = int(obj.get("index", -1))
        if 0 <= idx < num_candidates:
            return idx
    except (json.JSONDecodeError, ValueError, TypeError):
        # 宽松: 直接搜 index
        m = re.search(r'"index"\s*:\s*(\d+)', text)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < num_candidates:
                return idx
    return None


_ARCH_KEYWORDS = (
    "architecture", "framework", "pipeline", "overview", "model",
    "structure", "workflow", "method", "system",
    # 中文关键词
    "架构", "框架", "流水线", "概览", "方法", "模型"
)


def _heuristic_select_figure_index(specs: List[dict]) -> int:
    """启发式: 含"architecture/overview/framework..." 关键词优先, 否则第一张。"""
    scored = []
    for i, s in enumerate(specs):
        cap = (s.get("caption") or "").lower()
        score = 0
        for kw in _ARCH_KEYWORDS:
            if kw.lower() in cap:
                score += 3
        # caption 较长的通常是主图
        score += min(len(cap) / 50, 3)
        # tikz 优先（raster 次之）
        if s.get("kind") == "tikz":
            score += 2
        scored.append((score, i))
    scored.sort(reverse=True)
    return scored[0][1] if scored else 0


# ============================================================
# S5: pdflatex 兜底 + pymupdf 矢量抽取 (路径 A / B)
# ============================================================

def compile_tex_to_pdf(src_dir: str, main_tex: str,
                       timeout: int = DEFAULT_COMPILE_TIMEOUT) -> Optional[str]:
    """路径 B: 在 src_dir 下跑 pdflatex 重编译主文件。

    Returns:
        生成的 .pdf 路径, 失败返回 None

    不看 returncode（许多 warning 也会返回非 0）, 只检查产物 .pdf 是否存在。
    所有中间产物（.aux/.log/.out）留在 src_dir 下, 清理由缓存目录生命周期管理。
    """
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        logger.warning("[arxiv_src] pdflatex not found in PATH")
        return None
    if not os.path.isfile(main_tex):
        return None

    main_rel = os.path.relpath(main_tex, src_dir)
    out_base = os.path.splitext(main_rel)[0]
    expected_pdf = os.path.join(src_dir, out_base + ".pdf")

    # 若已有缓存产物（且比 tex 新）直接复用
    if (os.path.exists(expected_pdf)
            and os.path.getmtime(expected_pdf) >= os.path.getmtime(main_tex)):
        logger.info("[arxiv_src] compile cache hit: %s", expected_pdf)
        return expected_pdf

    cmd = [
        pdflatex,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        main_rel,
    ]
    try:
        # 2 次编译, 交叉引用稳定（但 timeout 平分）
        per_timeout = max(timeout // 2, 20)
        for _run in range(2):
            subprocess.run(
                cmd, cwd=src_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=per_timeout,
                check=False,
            )
            if not os.path.exists(expected_pdf):
                # 第一遍失败也继续（第二遍可能补齐）
                continue
    except subprocess.TimeoutExpired:
        logger.warning("[arxiv_src] pdflatex timeout after %ds", timeout)
    except Exception as e:
        logger.warning("[arxiv_src] pdflatex run error: %s", e)

    if os.path.exists(expected_pdf):
        # 额外落盘到 .compiled.pdf 作为稳定引用
        compiled = os.path.join(src_dir, ".compiled.pdf")
        try:
            shutil.copy2(expected_pdf, compiled)
        except Exception:
            pass
        return expected_pdf
    logger.warning("[arxiv_src] compile_tex_to_pdf 未产出 pdf")
    return None


def extract_vectors_from_pdf(pdf_path: str, page_num: int = 1) -> dict:
    """用 pymupdf 读 page.get_drawings() + get_text_words() 的矢量对象。

    page_num 1-based。返回 {components, connections, canvas_size, layout_direction}
    兼容 parse_tikz_structure 的返回结构。
    """
    import pymupdf

    components = []
    connections = []

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        logger.warning("[arxiv_src] pymupdf open 失败: %s", e)
        return {"components": [], "connections": [], "canvas_size": [0, 0],
                "layout_direction": "mixed"}

    try:
        if page_num < 1 or page_num > doc.page_count:
            page_num = 1
        page = doc[page_num - 1]
        page_rect = page.rect
        canvas_w = int(round(page_rect.width))
        canvas_h = int(round(page_rect.height))

        # 矢量对象: get_drawings() 返回 list of dict
        try:
            drawings = page.get_drawings()
        except Exception as e:
            logger.warning("[arxiv_src] get_drawings 失败: %s", e)
            drawings = []

        # 文本 words
        try:
            words = page.get_text("words")  # list of (x0, y0, x1, y1, word, ...)
        except Exception:
            words = []

        # 按 bbox 合并文本到最近的 drawing rect
        for idx, d in enumerate(drawings):
            rect = d.get("rect")
            if rect is None:
                continue
            # rect: pymupdf.Rect-like (x0, y0, x1, y1)
            x0, y0, x1, y1 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
            if (x1 - x0) < 3 or (y1 - y0) < 3:
                continue

            # 颜色 (fill 优先)
            fill = d.get("fill")
            stroke = d.get("stroke") or d.get("color")
            color_rgb = fill or stroke or None
            color_name = _pymupdf_color_to_name(color_rgb)

            # 形状猜测（pymupdf 的 drawing type: f=fill, s=stroke, 复合 path）
            shape = "rectangle"
            dtype = d.get("type", "")
            items = d.get("items", [])
            if items:
                # 若含曲线, 当圆
                curve_cnt = sum(1 for it in items if it and it[0] in ("c", "qu"))
                if curve_cnt >= 2:
                    shape = "circle"

            # 文本 label: 在此 rect 内的 words
            label_parts = []
            for w in words:
                wx0, wy0, wx1, wy1 = w[0], w[1], w[2], w[3]
                wcx = (wx0 + wx1) / 2
                wcy = (wy0 + wy1) / 2
                if x0 <= wcx <= x1 and y0 <= wcy <= y1:
                    label_parts.append(w[4])
            label = " ".join(label_parts).strip()

            # PDF 坐标 y 向下, 与 figure_analyzer bbox_normalized 约定一致
            components.append({
                "id": f"pdf_node_{idx}",
                "raw_label": label,
                "_x_cm": (x0 + x1) / 2 / 72.0 * 2.54,  # pt -> cm (72 pt = 1 inch = 2.54 cm)
                "_y_cm": (y0 + y1) / 2 / 72.0 * 2.54,
                "color": color_name,
                "shape": shape,
                "bbox_normalized": [
                    round(max(0.0, x0 / canvas_w), 3),
                    round(max(0.0, y0 / canvas_h), 3),
                    round(min(1.0, x1 / canvas_w), 3),
                    round(min(1.0, y1 / canvas_h), 3),
                ],
            })

        # 布局推断
        if components:
            cxs = [(c["bbox_normalized"][0] + c["bbox_normalized"][2]) / 2 for c in components]
            cys = [(c["bbox_normalized"][1] + c["bbox_normalized"][3]) / 2 for c in components]
            x_spread = max(cxs) - min(cxs)
            y_spread = max(cys) - min(cys)
            if x_spread > y_spread * 1.3:
                layout = "left-to-right"
            elif y_spread > x_spread * 1.3:
                layout = "top-to-bottom"
            else:
                layout = "mixed"
        else:
            layout = "mixed"

        return {
            "components": components,
            "connections": connections,
            "canvas_size": [canvas_w, canvas_h],
            "layout_direction": layout,
        }
    finally:
        doc.close()


def _pymupdf_color_to_name(rgb) -> str:
    """pymupdf drawing 返回的 rgb (r,g,b in [0,1]) 转 Manim 语义色名。"""
    if rgb is None:
        return "blue"
    try:
        r, g, b = rgb[0], rgb[1], rgb[2]
    except (TypeError, IndexError):
        return "blue"
    # 缩放到 0-255
    r, g, b = int(r * 255), int(g * 255), int(b * 255)
    # 复用 figure_analyzer._hex_to_manim_color（避免阈值漂移）
    try:
        try:
            from src.figure_analyzer import _hex_to_manim_color
        except ImportError:
            from figure_analyzer import _hex_to_manim_color  # type: ignore
        return _hex_to_manim_color(f"{r:02x}{g:02x}{b:02x}")
    except ImportError:
        # 最小兜底
        if r > 180 and g < 100 and b < 100:
            return "red"
        if g > 180 and r < 100 and b < 100:
            return "green"
        if b > 180 and r < 100 and g < 100:
            return "blue"
        return "blue"


# ============================================================
# S6: schema 对齐 —— 转换为 figure_analyzer._merge_analyses 同 schema
# ============================================================


def to_figure_analysis_dict(spec: dict,
                             canvas_wh: Tuple[int, int],
                             source: str) -> dict:
    """把内部 TikZ/PDF 解析结果转为与 figure_analyzer._merge_analyses 同 schema 的 dict。

    Args:
        spec: parse_tikz_structure / extract_vectors_from_pdf 的返回 dict
        canvas_wh: (w_px, h_px)
        source: "arxiv_latex_tikz" / "arxiv_latex_pdf" / "arxiv_latex"

    输出 schema (字段对齐 figure_analyzer._merge_analyses):
        figure_type, layout_direction, key_innovation, data_flow, animation_suggestion,
        has_neural_network, nn_layers, components[...], connections[...], canvas_size,
        has_precise_bbox=True, eb_element_count, source
    """
    try:
        try:
            from src.figure_analyzer import _bbox_to_position, _hex_to_manim_color
        except ImportError:
            from figure_analyzer import _bbox_to_position, _hex_to_manim_color  # type: ignore
    except Exception:
        _bbox_to_position = None
        _hex_to_manim_color = None

    raw_comps = spec.get("components", []) or []
    canvas_w, canvas_h = canvas_wh
    total_area = max(canvas_w * canvas_h, 1)

    components = []
    for c in raw_comps:
        bb = c.get("bbox_normalized") or [0.0, 0.0, 1.0, 1.0]
        # position: 用模块级 _bbox_to_position (若可用), 否则就近落一个 center
        if _bbox_to_position is not None:
            # bbox_normalized 是 [0,1], 复用需要 pixel, 给个 1x1 虚拟画布
            bbox_px = [bb[0] * canvas_w, bb[1] * canvas_h,
                       bb[2] * canvas_w, bb[3] * canvas_h]
            position = _bbox_to_position(bbox_px, canvas_w, canvas_h)
        else:
            cx = (bb[0] + bb[2]) / 2
            cy = (bb[1] + bb[3]) / 2
            position = _fallback_position(cx, cy)

        # size: bbox 面积 / canvas 面积
        area_ratio = (bb[2] - bb[0]) * (bb[3] - bb[1])
        if area_ratio > 0.05:
            size = "large"
        elif area_ratio > 0.01:
            size = "medium"
        else:
            size = "small"

        # color: 直接用 parse 得到的 color name（已是 manim 语义色）
        color = c.get("color", "blue") or "blue"

        components.append({
            "name": c.get("raw_label") or c.get("id") or f"Node_{len(components)}",
            "chinese_name": "",
            "type": "module",
            "position": position,
            "color": color,
            "shape": c.get("shape", "rectangle"),
            "size": size,
            "children": [],
            "description": "",
            "bbox_normalized": [round(float(v), 3) for v in bb],
        })

    # connections（from/to 可能指向 TikZ id, 与 components.name 对不上）
    # 把 tikz-id 映射到 name
    id_to_name = {}
    for i, c in enumerate(raw_comps):
        nid = c.get("id")
        if nid:
            id_to_name[nid] = components[i]["name"] if i < len(components) else nid

    conns_out = []
    for conn in (spec.get("connections", []) or []):
        fr = conn.get("from", "?")
        to = conn.get("to", "?")
        conns_out.append({
            "from": id_to_name.get(fr, fr),
            "to": id_to_name.get(to, to),
            "label": conn.get("label", ""),
            "type": conn.get("type", "arrow"),
            "description": conn.get("description", ""),
        })

    return {
        "figure_type": "architecture",
        "layout_direction": spec.get("layout_direction", "mixed"),
        "components": components,
        "connections": conns_out,
        "data_flow": "",
        "key_innovation": "",
        "has_neural_network": False,
        "nn_layers": [],
        "animation_suggestion": "",
        "has_precise_bbox": True,
        "eb_element_count": len(components),
        "canvas_size": [canvas_w, canvas_h],
        "source": source,
    }


def _fallback_position(cx: float, cy: float) -> str:
    h = "left" if cx < 0.33 else ("right" if cx > 0.66 else "center")
    v = "top" if cy < 0.33 else ("bottom" if cy > 0.66 else "")
    return (v + "-" + h).strip("-") if v else h


def to_eb_elements(analysis: dict) -> str:
    """把 analysis dict 转为 manim 元素列表字符串（与 eb_elements_to_manim_element_list 同格式）。

    复用 figure_analyzer 的同名函数不现实（它吃 EB ProcessingContext）, 这里就地实现。
    """
    components = analysis.get("components", []) or []
    connections = analysis.get("connections", []) or []
    canvas_size = analysis.get("canvas_size", [1, 1])
    canvas_w, canvas_h = canvas_size if len(canvas_size) >= 2 else (1, 1)

    # bbox_normalized [0,1] -> Manim 坐标 [-7,7] x [4,-4]
    def bb_to_manim(bb):
        cx01 = (bb[0] + bb[2]) / 2
        cy01 = (bb[1] + bb[3]) / 2
        mx = round(cx01 * 14 - 7, 2)
        my = round(-(cy01 * 8 - 4), 2)
        w = round((bb[2] - bb[0]) * 14, 2)
        h = round((bb[3] - bb[1]) * 8, 2)
        return mx, my, w, h

    lines = []
    lines.append("# arxiv LaTeX 源码精确元素数据（Manim 坐标系）")
    lines.append(f"# 画布: {canvas_w}x{canvas_h} px -> Manim X[-7,7] Y[-4,4]")
    lines.append("")
    lines.append(f"## 模块组（{len(components)} 个）:")
    for i, c in enumerate(components):
        bb = c.get("bbox_normalized") or [0, 0, 1, 1]
        mx, my, w, h = bb_to_manim(bb)
        shape = _shape_to_manim(c.get("shape", "rectangle"))
        color = (c.get("color") or "blue").upper()
        label = c.get("name") or c.get("chinese_name") or ""
        lines.append(
            f"  组{i+1}: {shape}(width={max(w, 0.3)}, height={max(h, 0.3)})"
            f".move_to([{mx}, {my}, 0]), color={color}, 标注={label[:30]}"
        )
    lines.append("")
    lines.append(f"## 箭头连接（{len(connections)} 条）:")
    for c in connections:
        lines.append(f"  Arrow: {c.get('from', '?')} -> {c.get('to', '?')} "
                     f"[{c.get('type', 'arrow')}] {c.get('label', '')}")
    return "\n".join(lines)


def _shape_to_manim(shape: str) -> str:
    mapping = {
        "rectangle": "Rectangle",
        "rounded_rect": "RoundedRectangle",
        "diamond": "Square",  # Manim 没有 Diamond, 用 Square 旋转代替
        "circle": "Circle",
    }
    return mapping.get(shape, "Rectangle")


# ============================================================
# 对外唯一入口: try_structured_figure
# ============================================================

COVERAGE_MIN_COMPONENTS = 2


def try_structured_figure(arxiv_id: str,
                           method_image_path: str,
                           cache_root: str,
                           paper_context: str = "") -> Optional[dict]:
    """arxiv LaTeX 源码直读 front-door 入口。

    流程:
        1. fetch tarball -> 解压 -> find main.tex
        2. resolve \\input + expand macros -> extract_figure_envs
        3. 多图时 LLM 按 caption 选主图
        4. kind==tikz: parse_tikz_structure
        5. kind==raster_pdf 且源文件是 PDF: extract_vectors_from_pdf
        6. kind==tikz 解析失败 或 kind==其它: pdflatex 兜底
        7. 结果合成为 figure_analysis dict 并返回

    任何异常都返回 None, 不抛。
    """
    try:
        aid = _strip_version(arxiv_id)
        src_root = os.path.join(cache_root, "arxiv_src")
        src_dir = os.path.join(src_root, aid)
        os.makedirs(src_root, exist_ok=True)

        # Step 1: fetch + extract
        if not os.path.isdir(src_dir) or not _has_manifest(src_dir):
            tarball = fetch_source(aid, cache_root)
            try:
                extract_source(tarball, src_dir)
            except (SizeLimitError, ValueError, tarfile.TarError) as e:
                logger.warning("[arxiv_src] extract 失败: %s", e)
                return None
            _write_manifest(src_dir, {"fetched_at": _iso_now(), "version": "v2"})

        main_tex = find_main_tex(src_dir)
        if not main_tex:
            logger.info("[arxiv_src] 找不到主 tex 文件 for %s", aid)
            return None

        # 更新 manifest 里的 main_tex 引用
        _update_manifest(src_dir, {"main_tex": os.path.relpath(main_tex, src_dir)})

        # Step 2: resolve includes + expand macros + extract figures
        full_tex = resolve_includes(main_tex, src_dir)
        full_tex = expand_user_macros(full_tex)
        specs = extract_figure_envs(full_tex, src_dir)
        if not specs:
            logger.info("[arxiv_src] 未提取到 figure 环境 for %s", aid)
            return None

        # Step 3: select main figure
        spec = select_main_figure_by_caption(specs, paper_context)
        if not spec:
            return None

        logger.info("[arxiv_src] 选中 figure: kind=%s, caption=%s",
                    spec.get("kind"), (spec.get("caption") or "")[:80])

        # Step 4/5/6: 解析结构
        struct = None
        source_tag = None

        if spec["kind"] in ("tikz", "pgfplots"):
            struct = parse_tikz_structure(spec["body"], src_dir)
            if struct and len(struct.get("components", [])) >= COVERAGE_MIN_COMPONENTS:
                source_tag = "arxiv_latex_tikz"
            else:
                struct = None

        if struct is None and spec["kind"] == "raster_pdf" and spec.get("source_path"):
            sp = spec["source_path"]
            if os.path.isfile(sp) and sp.lower().endswith(".pdf"):
                # 路径 A: tarball 已含 PDF 图, 直接抽矢量
                struct = extract_vectors_from_pdf(sp, page_num=1)
                if struct and len(struct.get("components", [])) >= COVERAGE_MIN_COMPONENTS:
                    source_tag = "arxiv_latex_pdf_vector"
                else:
                    struct = None

        if struct is None:
            # 路径 B: pdflatex 兜底
            pdf_path = compile_tex_to_pdf(src_dir, main_tex)
            if pdf_path:
                # 定位 figure 所在 page（简化: 先用 page 1, 高级可用 figure label 查 aux）
                page_num = _find_figure_page(src_dir, main_tex, spec.get("label"))
                struct = extract_vectors_from_pdf(pdf_path, page_num=page_num)
                if struct and len(struct.get("components", [])) >= COVERAGE_MIN_COMPONENTS:
                    source_tag = "arxiv_latex_pdflatex"
                else:
                    struct = None

        if struct is None or not source_tag:
            logger.info("[arxiv_src] 所有路径覆盖不足 for %s", aid)
            return None

        # Step 7: 合成输出
        canvas_wh = tuple(struct.get("canvas_size", [1000, 700]))
        analysis = to_figure_analysis_dict(struct, canvas_wh, source_tag)
        # 缺省 source 为 arxiv_latex（更高层）
        analysis["source"] = analysis.get("source", source_tag) or "arxiv_latex"
        analysis.setdefault("_caption", spec.get("caption", ""))
        return analysis

    except Exception as e:
        logger.warning("[arxiv_src] try_structured_figure 异常: %s", e)
        return None


def _has_manifest(src_dir: str) -> bool:
    return os.path.exists(os.path.join(src_dir, ".manifest.json"))


def _write_manifest(src_dir: str, data: dict) -> None:
    path = os.path.join(src_dir, ".manifest.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, IOError):
        pass


def _update_manifest(src_dir: str, patch: dict) -> None:
    path = os.path.join(src_dir, ".manifest.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, IOError, json.JSONDecodeError):
            data = {}
    data.update(patch)
    _write_manifest(src_dir, data)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _find_figure_page(src_dir: str, main_tex: str, label: Optional[str]) -> int:
    """从 pdflatex 生成的 .aux / .log 查找 figure label 对应的页码。

    失败默认 1。
    """
    if not label:
        return 1
    aux_path = os.path.splitext(main_tex)[0] + ".aux"
    if not os.path.exists(aux_path):
        return 1
    try:
        with open(aux_path, "r", encoding="utf-8", errors="ignore") as f:
            aux = f.read()
        # \newlabel{lbl}{{ref}{page}{...}}
        m = re.search(r"\\newlabel\{" + re.escape(label) + r"\}\{\{[^}]*\}\{(\d+)\}",
                      aux)
        if m:
            return int(m.group(1))
    except (OSError, IOError):
        pass
    return 1
