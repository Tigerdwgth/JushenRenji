"""论文方法图分析模块。

使用视觉 LLM (Qwen-VL via DashScope) 分析论文中的方法主图，
提取组件、连接关系、布局和数据流信息，输出结构化 JSON。
可选集成 ManimML 生成神经网络架构动画代码片段。
"""

import os
import json
import base64
import logging
import yaml
from typing import Optional

logger = logging.getLogger(__name__)

# ---- 配置 ----
_config_cache = None

def _get_config():
    global _config_cache
    if _config_cache is None:
        config_path = "config.yaml"
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                _config_cache = yaml.safe_load(f) or {}
        else:
            _config_cache = {}
    return _config_cache


def _image_to_base64(image_path: str) -> str:
    """将图片转换为 base64 data URI。"""
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
    mime = mime_map.get(ext, "image/png")
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{data}"


# ============================================================
# 核心分析：使用 Qwen-VL 分析方法图
# ============================================================

_FIGURE_ANALYSIS_PROMPT = """你是学术论文图像分析专家。请仔细分析这张论文方法/架构图，提取以下结构化信息。

请返回严格的 JSON 格式（不要 markdown 代码块标记），字段如下：

{
  "figure_type": "architecture|pipeline|flowchart|network|comparison|results",
  "layout_direction": "left-to-right|top-to-bottom|mixed|radial",
  "components": [
    {
      "name": "组件名称（英文，如图中标注）",
      "chinese_name": "组件中文名（用于展示）",
      "type": "module|layer|block|input|output|loss|data|operation",
      "position": "left|center|right|top|bottom|top-left|...",
      "color": "图中该组件的主色调，如 blue/green/red/purple/orange/gray",
      "shape": "rectangle|rounded_rect|circle|diamond|arrow|trapezoid",
      "size": "large|medium|small",
      "children": ["子组件名称列表（如果有内部结构）"],
      "description": "该组件的功能简述（1句话）"
    }
  ],
  "connections": [
    {
      "from": "起始组件 name",
      "to": "目标组件 name",
      "label": "连接上的标注文字（如果有）",
      "type": "arrow|bidirectional|dashed|data_flow",
      "description": "该连接表示什么（1句话）"
    }
  ],
  "data_flow": "数据在图中的整体流向描述（2-3句话）",
  "key_innovation": "该图展示的核心创新点（1-2句话）",
  "has_neural_network": true/false,
  "nn_layers": ["如果有神经网络，列出识别到的层类型：conv|fc|attention|transformer|mlp|embedding|pooling|norm"],
  "animation_suggestion": "建议的动画展示顺序（按数据流方向逐步展示哪些组件）"
}

注意：
1. 仔细识别图中的所有文字标注，用原文（通常是英文）作为 name
2. 如果组件内有子模块，体现在 children 字段
3. position 基于图中的相对位置
4. 连接关系要完整，包括所有箭头/连线
5. 如果图中有数学公式，在对应 component 的 description 中提及"""


def analyze_figure_with_vision_llm(image_path: str,
                                    paper_context: str = "",
                                    max_retries: int = 2) -> Optional[dict]:
    """使用 Qwen-VL (DashScope) 分析论文方法图。

    Args:
        image_path: 图片文件路径
        paper_context: 论文上下文（标题、摘要等，用于辅助理解）
        max_retries: 最大重试次数

    Returns:
        结构化分析 JSON dict，失败返回 None
    """
    import dashscope
    from dashscope import MultiModalConversation

    config = _get_config()
    api_key = config.get("dashscope_api_key", "")
    if api_key:
        dashscope.api_key = api_key

    if not os.path.exists(image_path):
        logger.error("图片不存在: %s", image_path)
        return None

    # 构建 prompt
    prompt = _FIGURE_ANALYSIS_PROMPT
    if paper_context:
        prompt += f"\n\n论文背景信息：\n{paper_context[:1500]}"

    # 使用 base64 或本地路径
    image_uri = f"file://{os.path.abspath(image_path)}"

    for attempt in range(max_retries):
        try:
            response = MultiModalConversation.call(
                model="qwen-vl-max",
                messages=[{
                    "role": "user",
                    "content": [
                        {"image": image_uri},
                        {"text": prompt}
                    ]
                }]
            )

            if response and response.output:
                text = response.output.choices[0].message.content[0]["text"]
                # 清理 markdown 代码块
                text = text.strip()
                if text.startswith("```"):
                    import re
                    text = re.sub(r"^```\w*\n?", "", text)
                    text = re.sub(r"\n?```$", "", text)
                    text = text.strip()

                result = json.loads(text)
                logger.info("图像分析成功: %s, %d 个组件, %d 个连接",
                           result.get("figure_type", "unknown"),
                           len(result.get("components", [])),
                           len(result.get("connections", [])))
                return result

        except json.JSONDecodeError as e:
            logger.warning("图像分析返回非 JSON (第 %d 次): %s", attempt + 1, str(e)[:200])
        except Exception as e:
            logger.warning("图像分析调用失败 (第 %d 次): %s", attempt + 1, e)

    logger.error("图像分析最终失败")
    return None


# ============================================================
# 将分析结果转换为 Manim 代码生成的上下文
# ============================================================

def analysis_to_manim_context(analysis: dict, has_precise_bbox: bool = False) -> str:
    """将图像分析结果转换为可注入 prompt 的结构化上下文文本。

    has_precise_bbox=True 时 (Edit Banana 已分割), 精确位置由 eb_manim_elements
    单独提供; 本函数仅输出语义信息 (组件名/描述/连接/核心创新), 不再输出
    "位置=center" 这种粗略字段, 避免与精确坐标指令冲突。
    """
    if not analysis:
        return ""

    lines = ["## 论文方法图分析结果（请严格参照此结构生成 Manim 代码）\n"]

    # 图类型和布局
    lines.append(f"图类型: {analysis.get('figure_type', 'unknown')}")
    lines.append(f"布局方向: {analysis.get('layout_direction', 'left-to-right')}")
    lines.append(f"核心创新: {analysis.get('key_innovation', '')}")
    lines.append(f"数据流: {analysis.get('data_flow', '')}")
    lines.append(f"建议动画顺序: {analysis.get('animation_suggestion', '')}")
    lines.append("")

    # 组件列表
    components = analysis.get("components", [])
    if components:
        lines.append(f"### 组件列表（共 {len(components)} 个）:")
        for i, comp in enumerate(components):
            name = comp.get("name", f"Component_{i}")
            ctype = comp.get("type", "module")
            pos = comp.get("position", "center")
            color = comp.get("color", "blue")
            shape = comp.get("shape", "rectangle")
            desc = comp.get("description", "")
            children = comp.get("children", [])
            if has_precise_bbox:
                # 位置/颜色/形状 由 eb_manim_elements 精确提供, 这里只输出语义
                line = f"  {i+1}. [{name}] 类型={ctype}"
            else:
                line = f"  {i+1}. [{name}] 类型={ctype}, 位置={pos}, 颜色={color}, 形状={shape}"
            if desc:
                line += f", 描述: {desc}"
            if children:
                line += f", 子组件: {children}"
            lines.append(line)
        lines.append("")

    # 连接关系
    connections = analysis.get("connections", [])
    if connections:
        lines.append(f"### 连接关系（共 {len(connections)} 条）:")
        for conn in connections:
            fr = conn.get("from", "?")
            to = conn.get("to", "?")
            label = conn.get("label", "")
            ctype = conn.get("type", "arrow")
            desc = conn.get("description", "")
            line = f"  {fr} --[{ctype}]--> {to}"
            if label:
                line += f" (标注: {label})"
            if desc:
                line += f" | {desc}"
            lines.append(line)
        lines.append("")

    # Manim 映射建议（has_precise_bbox 时 eb_manim_elements 已给足坐标，不再重复）
    if not has_precise_bbox:
        lines.append("### Manim 实现建议:")
        layout = analysis.get("layout_direction", "left-to-right")
        if layout == "left-to-right":
            lines.append("  - 组件从左到右排列，用 .arrange(RIGHT, buff=0.5)")
            lines.append("  - 动画按数据流方向逐个 FadeIn")
        elif layout == "top-to-bottom":
            lines.append("  - 组件从上到下排列，用 .arrange(DOWN, buff=0.4)")
            lines.append("  - 动画从顶部开始逐个展示")
        else:
            lines.append("  - 混合布局，手动定位各组件坐标")
            lines.append("  - 按数据流方向分组展示")

        lines.append("  - 每个组件用对应颜色的 Rectangle/RoundedRectangle + Text")
        lines.append("  - 连接用 Arrow，数据流用 Dot 沿路径移动")
        lines.append("  - 核心创新模块用 SurroundingRectangle 高亮")

    return "\n".join(lines)


# ============================================================
# 一站式接口
# ============================================================


# ============================================================
# Edit Banana 集成：SAM3 精确元素分割
# ============================================================

_EDIT_BANANA_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "thirdparty", "edit-banana"
)


def _init_edit_banana():
    """初始化 Edit Banana Pipeline（懒加载）。使用 L20 GPU (GPU 3)。"""
    import sys
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = "3"  # L20 46GB

    # EB 路径必须在最前面，避免 src/prompts.py 遮蔽 EB 的 prompts/ 包
    if _EDIT_BANANA_ROOT in sys.path:
        sys.path.remove(_EDIT_BANANA_ROOT)
    sys.path.insert(0, _EDIT_BANANA_ROOT)

    prev_cwd = os.getcwd()
    os.chdir(_EDIT_BANANA_ROOT)

    # 清除 prompts 模块缓存，避免 src/llm_tools/prompts.py 遮蔽 EB 的 prompts/ 包
    import importlib
    for mod_name in list(sys.modules.keys()):
        if mod_name == "prompts" or mod_name.startswith("prompts."):
            del sys.modules[mod_name]
        if mod_name == "main" and "edit-banana" not in getattr(sys.modules[mod_name], "__file__", ""):
            del sys.modules[mod_name]

    try:
        from main import Pipeline, load_config
        config = load_config()
        pipeline = Pipeline(config)
        logger.info("Edit Banana Pipeline 初始化成功")
        return pipeline
    except Exception as e:
        logger.warning("Edit Banana 初始化失败: %s", e)
        return None
    finally:
        os.chdir(prev_cwd)


_eb_pipeline = None


def analyze_figure_with_edit_banana(image_path: str) -> Optional[dict]:
    """使用 Edit Banana 完整 pipeline 分析论文方法图。

    执行: SAM3 分割 → 形状处理 → OCR 文字 → XML 合并 → DrawIO XML
    然后解析 DrawIO XML 生成 Manim 图表规格。

    Returns:
        结构化分析 dict，含 drawio_spec（可直接喂给 opencode 的 Manim 坐标规格）
    """
    global _eb_pipeline
    if _eb_pipeline is None:
        _eb_pipeline = _init_edit_banana()
    if _eb_pipeline is None:
        return None

    if not os.path.exists(image_path):
        logger.error("图片不存在: %s", image_path)
        return None

    try:
        output_dir = "/tmp/eb_pipeline_output"
        os.makedirs(output_dir, exist_ok=True)

        # 跑完整 pipeline（含 OCR + XML 合并）
        drawio_path = _eb_pipeline.process_image(
            image_path, output_dir=output_dir,
            with_text=True, with_refinement=False
        )

        if not drawio_path or not os.path.exists(drawio_path):
            logger.warning("Edit Banana pipeline 未生成 DrawIO 文件")
            return None

        logger.info("Edit Banana DrawIO 生成: %s", drawio_path)

        # 解析 DrawIO XML → Manim 图表规格
        drawio_spec = parse_drawio_to_diagram_spec(drawio_path)
        logger.info("DrawIO → Manim 图表规格: %d 字符", len(drawio_spec))

        # 同时生成基本分析格式（兼容融合逻辑）
        result = {
            "figure_type": "architecture",
            "layout_direction": "left-to-right",
            "components": [],
            "connections": [],
            "has_neural_network": False,
            "nn_layers": [],
            "source": "edit_banana",
            "drawio_path": drawio_path,
            "drawio_spec": drawio_spec,
        }
        return result

    except Exception as e:
        logger.warning("Edit Banana 分析失败: %s", e)
        import traceback
        traceback.print_exc()
        return None


def _elements_to_analysis(context) -> dict:
    """将 Edit Banana 的 ProcessingContext 转换为标准分析 JSON。"""
    components = []
    connections = []
    canvas_w = context.canvas_width or 1
    canvas_h = context.canvas_height or 1

    # Manim 颜色映射
    def _hex_to_manim_color(hex_color):
        if not hex_color:
            return "blue"
        hex_color = hex_color.lower().lstrip("#")
        color_map = {
            "ff": "red", "00ff": "green", "0000ff": "blue",
            "ff00ff": "purple", "ffff00": "yellow", "ffa500": "orange",
        }
        # 简单映射：看主色调
        if len(hex_color) >= 6:
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            if r > 180 and g < 100 and b < 100:
                return "red"
            elif g > 180 and r < 100 and b < 100:
                return "green"
            elif b > 180 and r < 100 and g < 100:
                return "blue"
            elif r > 150 and g > 150 and b < 100:
                return "yellow"
            elif r > 180 and g > 100 and b < 80:
                return "orange"
            elif r > 100 and b > 100 and g < 80:
                return "purple"
            elif r > 150 and g > 150 and b > 150:
                return "gray"
        return "blue"

    def _bbox_to_position(bbox, canvas_w, canvas_h):
        cx = (bbox.x1 + bbox.x2) / 2 / canvas_w
        cy = (bbox.y1 + bbox.y2) / 2 / canvas_h
        if cx < 0.33:
            h = "left"
        elif cx > 0.66:
            h = "right"
        else:
            h = "center"
        if cy < 0.33:
            v = "top"
        elif cy > 0.66:
            v = "bottom"
        else:
            v = ""
        return (v + "-" + h).strip("-") if v else h

    # 形状映射
    type_shape_map = {
        "rectangle": "rectangle",
        "rounded_rectangle": "rounded_rect",
        "diamond": "diamond",
        "ellipse": "circle",
        "circle": "circle",
        "triangle": "diamond",
    }

    for elem in context.elements:
        etype = elem.element_type
        # 箭头 → 连接
        if etype in ("arrow", "line", "connector"):
            conn = {
                "from": "?",
                "to": "?",
                "label": "",
                "type": "arrow" if etype == "arrow" else "line",
                "description": "",
            }
            # 用箭头起止点匹配最近的组件
            if elem.arrow_start and elem.arrow_end:
                conn["_start"] = list(elem.arrow_start)
                conn["_end"] = list(elem.arrow_end)
            connections.append(conn)
            continue

        # 非箭头 → 组件
        shape = type_shape_map.get(etype, "rectangle")
        pos = _bbox_to_position(elem.bbox, canvas_w, canvas_h)
        color = _hex_to_manim_color(elem.fill_color)
        size = "large" if elem.bbox.area > (canvas_w * canvas_h * 0.05) else (
            "medium" if elem.bbox.area > (canvas_w * canvas_h * 0.01) else "small"
        )

        comp = {
            "name": "Element_%d" % elem.id,
            "chinese_name": "",
            "type": "module",
            "position": pos,
            "color": color,
            "shape": shape,
            "size": size,
            "children": [],
            "description": "",
            "bbox_normalized": [
                round(elem.bbox.x1 / canvas_w, 3),
                round(elem.bbox.y1 / canvas_h, 3),
                round(elem.bbox.x2 / canvas_w, 3),
                round(elem.bbox.y2 / canvas_h, 3),
            ],
        }
        components.append(comp)

    # 匹配箭头的起终点到最近组件
    for conn in connections:
        start = conn.pop("_start", None)
        end = conn.pop("_end", None)
        if start and components:
            best_from = min(components, key=lambda c: abs(
                (c["bbox_normalized"][0] + c["bbox_normalized"][2]) / 2 * canvas_w - start[0]) +
                abs((c["bbox_normalized"][1] + c["bbox_normalized"][3]) / 2 * canvas_h - start[1]))
            conn["from"] = best_from["name"]
        if end and components:
            best_to = min(components, key=lambda c: abs(
                (c["bbox_normalized"][0] + c["bbox_normalized"][2]) / 2 * canvas_w - end[0]) +
                abs((c["bbox_normalized"][1] + c["bbox_normalized"][3]) / 2 * canvas_h - end[1]))
            conn["to"] = best_to["name"]

    # 推断布局方向
    if components:
        xs = [c["bbox_normalized"][0] for c in components]
        ys = [c["bbox_normalized"][1] for c in components]
        x_spread = max(xs) - min(xs) if xs else 0
        y_spread = max(ys) - min(ys) if ys else 0
        layout = "left-to-right" if x_spread > y_spread else "top-to-bottom"
    else:
        layout = "mixed"

    return {
        "figure_type": "architecture",
        "layout_direction": layout,
        "components": components,
        "connections": connections,
        "data_flow": "",
        "key_innovation": "",
        "has_neural_network": False,
        "nn_layers": [],
        "animation_suggestion": "",
        "source": "edit_banana",
        "canvas_size": [canvas_w, canvas_h],
        "element_count": len(context.elements),
    }



def parse_drawio_to_diagram_spec(drawio_path: str, canvas_w: int = 1920, canvas_h: int = 691) -> str:
    """解析 DrawIO XML，提取所有元素，转换为 Manim 坐标系的紧凑图表规格。

    输出格式可直接喂给 opencode 作为上下文，让它按规格生成 Manim 代码。
    """
    import xml.etree.ElementTree as ET
    import re

    tree = ET.parse(drawio_path)
    root = tree.getroot()

    def px_to_manim(x, y):
        mx = round(x / canvas_w * 14 - 7, 1)
        my = round(-(y / canvas_h * 8 - 4), 1)
        return mx, my

    def parse_style(style_str):
        props = {}
        for part in style_str.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                props[k.strip()] = v.strip()
        return props

    def hex_to_manim_color(hex_color):
        if not hex_color or hex_color == "none":
            return None
        h = hex_color.lower().lstrip("#")
        if len(h) < 6:
            return None
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        if r > 200 and g < 120 and b < 120: return "RED"
        if g > 180 and r < 120 and b < 120: return "GREEN"
        if b > 200 and r < 120 and g < 120: return "BLUE"
        if r > 200 and g > 150 and b < 100: return "ORANGE"
        if r > 200 and g > 200 and b < 120: return "YELLOW"
        if r > 130 and b > 130 and g < 100: return "PURPLE"
        if r > 80 and g > 80 and b > 80 and max(r,g,b) - min(r,g,b) < 40: return "GRAY"
        if r > 180 and g > 200 and b > 220: return "LIGHT_BLUE"
        if r > 240 and g > 220 and b > 190: return "LIGHT_BROWN"
        return "WHITE"

    shapes = []  # (id, type, x, y, w, h, color, stroke)
    texts = []   # (text, x, y, font_size)
    arrows = []  # (id, x, y, w, h)

    for cell in root.iter("mxCell"):
        cell_id = cell.get("id", "")
        value = cell.get("value", "")
        style = cell.get("style", "")
        geom = cell.find("mxGeometry")

        if geom is None:
            continue

        x = float(geom.get("x", 0))
        y = float(geom.get("y", 0))
        w = float(geom.get("w", geom.get("width", 0)))
        h = float(geom.get("h", geom.get("height", 0)))

        props = parse_style(style)

        if "text" in style and value:
            # 文字元素
            fs_match = re.search(r"fontSize=(\d+)", style)
            fs = int(fs_match.group(1)) if fs_match else 14
            texts.append({"text": value, "x": x, "y": y, "w": w, "h": h, "fs": fs})
        elif "image" in props.get("shape", ""):
            # 图片（跳过，Manim 用文字替代）
            pass
        elif w > 0 and h > 0:
            fill = props.get("fillColor", "")
            stroke = props.get("strokeColor", "")
            rounded = "1" in props.get("rounded", "0")
            shape_type = "RoundedRectangle" if rounded else "Rectangle"
            shapes.append({
                "id": cell_id, "type": shape_type,
                "x": x, "y": y, "w": w, "h": h,
                "fill": hex_to_manim_color(fill),
                "stroke": hex_to_manim_color(stroke),
            })

    # 把文字匹配到最近的形状（文字在形状内部）
    for t in texts:
        tx_center = t["x"] + t["w"] / 2
        ty_center = t["y"] + t["h"] / 2
        best_shape = None
        best_dist = float("inf")
        for s in shapes:
            # 检查文字中心是否在形状 bbox 内
            if s["x"] <= tx_center <= s["x"] + s["w"] and s["y"] <= ty_center <= s["y"] + s["h"]:
                dist = abs(tx_center - (s["x"] + s["w"]/2)) + abs(ty_center - (s["y"] + s["h"]/2))
                if dist < best_dist:
                    best_dist = dist
                    best_shape = s
        if best_shape:
            if "label" not in best_shape:
                best_shape["label"] = t["text"]
            else:
                best_shape["label"] += " " + t["text"]

    # 过滤太小的形状，按面积排序（大→小）
    shapes = [s for s in shapes if s["w"] > 20 and s["h"] > 15]
    shapes.sort(key=lambda s: s["w"] * s["h"], reverse=True)

    # 生成 Manim 坐标的紧凑规格
    lines = []
    lines.append("# 图表规格（从论文方法图 SAM3+OCR 精确提取）")
    lines.append("# 坐标系: Manim X[-7,7] Y[-4,4], 原图 %dx%d px" % (canvas_w, canvas_h))
    lines.append("# 请严格按以下坐标、尺寸、颜色生成 Manim 代码！")
    lines.append("")

    lines.append("SHAPES = [  # (type, manim_x, manim_y, manim_w, manim_h, fill_color, label)")
    for s in shapes[:25]:  # 限制数量
        mx, my = px_to_manim(s["x"] + s["w"]/2, s["y"] + s["h"]/2)
        mw = round(s["w"] / canvas_w * 14, 2)
        mh = round(s["h"] / canvas_h * 8, 2)
        label = s.get("label", "")
        fill = s.get("fill") or "WHITE"
        lines.append('    ("%s", %s, %s, %s, %s, "%s", "%s"),' % (
            s["type"], mx, my, mw, mh, fill, label[:30]))
    lines.append("]")
    lines.append("")

    # 浮动文字（没匹配到形状的）
    free_texts = [t for t in texts if t["fs"] > 15]
    if free_texts:
        lines.append("FREE_TEXTS = [  # (text, manim_x, manim_y, font_size)")
        for t in free_texts[:15]:
            mx, my = px_to_manim(t["x"], t["y"])
            lines.append('    ("%s", %s, %s, %s),' % (t["text"][:25], mx, my, min(t["fs"], 28)))
        lines.append("]")

    return "\n".join(lines)

def eb_elements_to_manim_element_list(context, vision_analysis=None) -> str:
    """将 Edit Banana 的元素数据转换为 opencode 可直接使用的 Manim 元素描述。

    输出格式：每个元素一行，包含 Manim 坐标、尺寸、颜色、类型，
    opencode 可以直接用这些数据生成 Rectangle/Arrow 代码。
    """
    cw = context.canvas_width or 1
    ch = context.canvas_height or 1

    def px_to_manim(x, y):
        """像素坐标 -> Manim 坐标 (x: [-7,7], y: [4,-4])"""
        mx = x / cw * 14 - 7
        my = -(y / ch * 8 - 4)
        return round(mx, 2), round(my, 2)

    def hex_to_manim_color(hex_color):
        if not hex_color:
            return "WHITE"
        h = hex_color.lower().lstrip("#")
        if len(h) < 6:
            return "WHITE"
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        if r > 200 and g < 120 and b < 120: return "RED"
        if g > 200 and r < 120 and b < 120: return "GREEN"
        if b > 200 and r < 120 and g < 120: return "BLUE"
        if r > 200 and g > 150 and b < 100: return "ORANGE"
        if r > 200 and g > 200 and b < 120: return "YELLOW"
        if r > 130 and b > 130 and g < 100: return "PURPLE"
        if r > 180 and g > 180 and b > 180: return "GRAY_A"
        if r > 220 and g > 200 and b > 180: return "LIGHT_BROWN"
        return "WHITE"

    # 获取 Qwen-VL 的语义名称映射
    v_comps = []
    if vision_analysis:
        v_comps = vision_analysis.get("components", [])

    lines = []
    lines.append("# Edit Banana 精确元素数据（Manim 坐标系）")
    lines.append("# 画布: %dx%d px -> Manim X[-7,7] Y[-4,4]" % (cw, ch))
    lines.append("")

    # 分类收集
    rects = []
    arrows = []
    others = []

    for e in context.elements:
        etype = e.element_type
        x1, y1, x2, y2 = e.bbox.x1, e.bbox.y1, e.bbox.x2, e.bbox.y2
        cx, cy = px_to_manim((x1+x2)/2, (y1+y2)/2)
        w = round((x2-x1) / cw * 14, 2)
        h = round((y2-y1) / ch * 8, 2)
        color = hex_to_manim_color(e.fill_color)

        if etype in ("arrow", "line", "connector"):
            x1, y1, x2, y2 = e.bbox.x1, e.bbox.y1, e.bbox.x2, e.bbox.y2
            if e.arrow_start and e.arrow_end:
                sx, sy = px_to_manim(e.arrow_start[0], e.arrow_start[1])
                ex, ey = px_to_manim(e.arrow_end[0], e.arrow_end[1])
            else:
                # 用 bbox 推断箭头方向（宽>高 → 水平，高>宽 → 垂直）
                bw, bh = x2 - x1, y2 - y1
                if bw > bh:  # 水平箭头
                    sx, sy = px_to_manim(x1, (y1+y2)/2)
                    ex, ey = px_to_manim(x2, (y1+y2)/2)
                else:  # 垂直箭头
                    sx, sy = px_to_manim((x1+x2)/2, y1)
                    ex, ey = px_to_manim((x1+x2)/2, y2)
            arrows.append("Arrow: start=([%s,%s,0]) end=([%s,%s,0])" % (sx, sy, ex, ey))
        elif etype in ("rectangle", "rounded rectangle", "rounded_rectangle"):
            shape = "RoundedRectangle" if "round" in etype else "Rectangle"
            # 过滤太小的元素
            if w < 0.3 and h < 0.3:
                continue
            rects.append({
                "shape": shape, "cx": cx, "cy": cy, "w": w, "h": h,
                "color": color, "id": e.id
            })
        elif etype in ("picture", "icon"):
            others.append("ImageElement: center=(%s,%s) size=(%s,%s) [id=%d]" % (
                cx, cy, w, h, e.id))

    # 按位置排序 rects（从左到右，从上到下）
    rects.sort(key=lambda r: (round(r["cx"]), -r["cy"]))

    # 尝试把语义名称匹配到 rect（按位置接近度）
    for i, rect in enumerate(rects):
        label = ""
        if i < len(v_comps):
            label = v_comps[i].get("name", "")
        rect["label"] = label

    # 合并相似位置的小 rect 为一个大模块
    # （论文架构图中，多个小矩形堆叠通常是 Transformer 层）
    groups = []
    used = set()
    for i, r in enumerate(rects):
        if i in used:
            continue
        group = [r]
        used.add(i)
        for j, r2 in enumerate(rects):
            if j in used:
                continue
            # 同一列 (cx 接近) 且 size 相同
            if abs(r["cx"] - r2["cx"]) < 0.3 and abs(r["w"] - r2["w"]) < 0.2 and abs(r["h"] - r2["h"]) < 0.2:
                group.append(r2)
                used.add(j)
        groups.append(group)

    lines.append("## 模块组（%d 组，从图中分割得到）:" % len(groups))
    for gi, group in enumerate(groups):
        if len(group) > 3:
            # 多层堆叠 -> 描述为一个大模块
            min_y = min(r["cy"] for r in group)
            max_y = max(r["cy"] for r in group)
            cx = group[0]["cx"]
            color = group[0]["color"]
            label = group[0].get("label", "")
            lines.append("  组%d: %d 层堆叠模块, center=(%s, %.1f), 高度范围=[%.1f, %.1f], color=%s, 标注=%s" % (
                gi+1, len(group), cx, (min_y+max_y)/2, min_y, max_y, color, label))
        elif len(group) == 1:
            r = group[0]
            lines.append("  组%d: %s(width=%s, height=%s).move_to([%s, %s, 0]), color=%s, 标注=%s" % (
                gi+1, r["shape"], r["w"], r["h"], r["cx"], r["cy"], r["color"], r.get("label", "")))
        else:
            for r in group:
                lines.append("  组%d: %s(width=%s, height=%s).move_to([%s, %s, 0]), color=%s" % (
                    gi+1, r["shape"], r["w"], r["h"], r["cx"], r["cy"], r["color"]))

    lines.append("")
    lines.append("## 箭头连接（%d 条）:" % len(arrows))
    for a in arrows:
        lines.append("  " + a)

    lines.append("")
    lines.append("## 图片/图标（%d 个）:" % len(others))
    for o in others[:5]:
        lines.append("  " + o)

    return "\n".join(lines)


# ============================================================
# Qwen-VL 结构一致性检查
# ============================================================

_CONSISTENCY_CHECK_PROMPT = """你是学术图表还原质量评审专家。请对比以下两张图：
- 图1（左）：论文原图（方法架构图）
- 图2（右）：Manim 动画渲染的还原图

请从以下维度评分（1-10）并给出具体反馈：

1. **结构完整性** (structure_score): 原图中的主要模块是否都在还原图中出现？缺了哪些？
2. **布局一致性** (layout_score): 模块的相对位置关系是否与原图一致？（左右、上下关系）
3. **连接关系** (connection_score): 箭头/连线是否正确反映了原图的数据流向？
4. **文字标注** (text_score): 关键标注文字是否正确且可读？
5. **总体还原度** (overall_score): 整体看起来像不像原图？

返回严格 JSON：
{
  "structure_score": 8,
  "layout_score": 7,
  "connection_score": 6,
  "text_score": 7,
  "overall_score": 7,
  "missing_components": ["缺失的组件名称列表"],
  "wrong_positions": ["位置错误的描述"],
  "suggestions": ["改进建议，每条一句话"],
  "pass": true/false  (overall_score >= 6 则 pass)
}"""


def check_consistency_with_vision_llm(original_image: str,
                                       rendered_image: str,
                                       max_retries: int = 2) -> Optional[dict]:
    """用 Qwen-VL 对比原图和 Manim 渲染图，检查结构一致性。

    Args:
        original_image: 论文原图路径
        rendered_image: Manim 渲染帧路径

    Returns:
        评分和反馈 dict，失败返回 None
    """
    import dashscope
    from dashscope import MultiModalConversation

    config = _get_config()
    api_key = config.get("dashscope_api_key", "")
    if api_key:
        dashscope.api_key = api_key

    for path in [original_image, rendered_image]:
        if not os.path.exists(path):
            logger.error("图片不存在: %s", path)
            return None

    orig_uri = f"file://{os.path.abspath(original_image)}"
    rend_uri = f"file://{os.path.abspath(rendered_image)}"

    for attempt in range(max_retries):
        try:
            response = MultiModalConversation.call(
                model="qwen-vl-max",
                messages=[{
                    "role": "user",
                    "content": [
                        {"image": orig_uri},
                        {"image": rend_uri},
                        {"text": _CONSISTENCY_CHECK_PROMPT}
                    ]
                }]
            )

            if response and response.output:
                import re
                text = response.output.choices[0].message.content[0]["text"]
                text = text.strip()
                if text.startswith("```"):
                    text = re.sub(r"^```\w*\n?", "", text)
                    text = re.sub(r"\n?```$", "", text)
                    text = text.strip()

                result = json.loads(text)
                logger.info("一致性检查: overall=%s, pass=%s",
                           result.get("overall_score"), result.get("pass"))
                return result

        except json.JSONDecodeError as e:
            logger.warning("一致性检查返回非 JSON (第 %d 次): %s", attempt + 1, str(e)[:100])
        except Exception as e:
            logger.warning("一致性检查失败 (第 %d 次): %s", attempt + 1, e)

    return None


def extract_frame_from_video(video_path: str, time_sec: float = None) -> Optional[str]:
    """从视频中提取一帧作为图片，用于一致性检查。

    默认取 70% 位置的帧（动画基本展示完毕）。
    """
    try:
        from moviepy import VideoFileClip
        clip = VideoFileClip(video_path)
        if time_sec is None:
            time_sec = clip.duration * 0.7
        time_sec = min(time_sec, clip.duration - 0.1)

        frame = clip.get_frame(time_sec)
        clip.close()

        from PIL import Image
        import numpy as np
        img = Image.fromarray(np.uint8(frame))
        frame_path = video_path.replace(".mp4", "_frame.png")
        img.save(frame_path)
        logger.info("提取帧: t=%.1fs -> %s", time_sec, frame_path)
        return frame_path
    except Exception as e:
        logger.warning("提取帧失败: %s", e)
        return None

# ============================================================
# 升级版一站式接口：Edit Banana + Qwen-VL 融合
# ============================================================

def analyze_and_prepare(image_path: str,
                        paper_context: str = "") -> dict:
    """分析图片并准备 Manim 生成所需的全部上下文。

    融合策略：
    1. Qwen-VL 提供语义理解（组件名称、功能描述、核心创新、数据流）
    2. Edit Banana (SAM3) 提供精确空间信息（bbox、颜色、形状）
    3. 两者融合：用 Qwen-VL 的语义 + Edit Banana 的精确坐标

    Returns:
        {
            "analysis": 融合后的分析 JSON,
            "manim_context": 可注入 prompt 的文本,
            "figure_type": 图类型
        }
    """
    result = {
        "analysis": None,
        "manim_context": "",
        "figure_type": "unknown",
    }

    # 1. Qwen-VL 语义分析（必需）
    vision_analysis = analyze_figure_with_vision_llm(image_path, paper_context)

    # 2. Edit Banana 精确分割（可选增强）
    eb_analysis = None
    try:
        eb_analysis = analyze_figure_with_edit_banana(image_path)
        if eb_analysis:
            logger.info("Edit Banana 分割: %d 组件, %d 连接",
                       len(eb_analysis.get("components", [])),
                       len(eb_analysis.get("connections", [])))
    except Exception as e:
        logger.warning("Edit Banana 不可用，仅使用 Qwen-VL: %s", e)

    # 3. 融合
    if vision_analysis and eb_analysis:
        analysis = _merge_analyses(vision_analysis, eb_analysis)
        logger.info("融合分析: Qwen-VL 语义 + Edit Banana 空间 (%d 组件)",
                    len(analysis.get("components", [])))
    elif vision_analysis:
        analysis = vision_analysis
    elif eb_analysis:
        analysis = eb_analysis
    else:
        return result

    result["analysis"] = analysis
    result["figure_type"] = analysis.get("figure_type", "unknown")
    result["manim_context"] = analysis_to_manim_context(analysis, has_precise_bbox=bool(eb_analysis))

    # 4. 如果有 EB 的 DrawIO 图表规格，直接使用
    if eb_analysis and eb_analysis.get("drawio_spec"):
        result["eb_manim_elements"] = eb_analysis["drawio_spec"]
        logger.info("使用 DrawIO 图表规格 (%d 字符)", len(eb_analysis["drawio_spec"]))

    return result


def _merge_analyses(vision: dict, eb: dict) -> dict:
    """融合 Qwen-VL 语义分析和 Edit Banana 空间分析。

    策略：以 Qwen-VL 为主（有语义名称和描述），用 Edit Banana 补充精确坐标和颜色。
    """
    merged = dict(vision)  # 以 vision 为基础

    # 用 EB 的精确组件数更新
    eb_comps = eb.get("components", [])
    v_comps = vision.get("components", [])

    if eb_comps:
        # 为 vision 的组件补充精确 bbox
        for i, vc in enumerate(v_comps):
            if i < len(eb_comps):
                # 用 EB 的精确归一化 bbox 补充
                if "bbox_normalized" in eb_comps[i]:
                    vc["bbox_normalized"] = eb_comps[i]["bbox_normalized"]
                # 如果 vision 没有颜色而 EB 有，用 EB 的
                if not vc.get("color") or vc["color"] == "blue":
                    vc["color"] = eb_comps[i].get("color", vc.get("color", "blue"))

        merged["components"] = v_comps
        # 添加 EB 来源标记
        merged["has_precise_bbox"] = True
        merged["eb_element_count"] = eb.get("element_count", 0)
        merged["canvas_size"] = eb.get("canvas_size", [0, 0])

    return merged
