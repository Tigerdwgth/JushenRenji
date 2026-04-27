---
name: figure-analysis
description: 多轮 reasoning 分析论文方法图，输出 components/connections/key_innovation/layout_direction 等结构化 JSON，用于 Manim 架构场景生成。当需要把论文方法图转成 Manim 可渲染的语义结构时使用。
---

# Figure Analysis (P2)

## Overview

本 skill 把 `JushenRenji.src.figure_analyzer:analyze_figure_with_vision_llm`
的"图像语义分析"步骤抽出来，用 **opencode 多轮 reasoning** 替代 Qwen-VL
单次问到底的方式：

| 维度       | 单次 (旧)                  | 多轮 (本 skill)                  |
|------------|----------------------------|----------------------------------|
| 模块识别   | 一次问 5-10 个易遗漏       | 第 1 轮专注"列模块"             |
| 连接关系   | 一次问 + 模块 + 标注混杂   | 第 2 轮基于已识别模块再问连线   |
| 高层语义   | 容易丢字段                 | 第 3 轮单独问 figure_type / key_innovation / layout_direction |

opencode 的 deepseek-v4-pro 等当前主力模型 **不支持图像直输** (实测 2026-04-24)，
但可以基于 `paper_context` (caption / abstract / method paragraph) + 仓库内 LaTeX 源码
路径做多轮文本推理。这正是本 skill 的核心价值——**把单次 VLM call 拆成 3 次专注问答**，
让结果更全面、更稳定，覆盖率明显提升。

输出 JSON 与 `figure_analyzer._merge_analyses` schema **完全兼容**，
精确 bbox 仍由 EditBanana / SAM3 / arxiv_latex 等下游路径补 (`has_precise_bbox=False`,
`source="vision_skill"`)。

## Cross-conda invocation pattern

必须先激活 `paperagent` 环境：

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate paperagent
cd ~/Projects/VlogCutter/JushenRenji
python -m src.figure_cli analyze-figure \
  --image cache/arxiv_src/2506.15953/img/arch.png \
  --paper-context "ViTacFormer cross-modal transformer for visuo-tactile manipulation" \
  --out /tmp/figure_analysis.json
```

## Tool: analyze-figure

3 轮 reasoning 分析方法图，输出 figure_analyzer 兼容 JSON。

### Input

| Flag                | Type   | Default | Description |
|---------------------|--------|---------|-------------|
| `--image`           | string | (required) | 图片文件路径 (绝对或相对仓库根) |
| `--paper-context`   | string | `""`    | 论文上下文 (caption / abstract / method paragraph)，强烈建议给 |
| `--out`             | string | (required) | 输出 JSON 路径 |
| `--opencode-model`  | string | (空)    | opencode 模型，缺省读 `config.yaml: opencode_model` (`deepseek/deepseek-v4-pro`) |
| `--round-timeout`   | int    | 180     | 单轮 opencode 超时 (秒) |

### 输出 JSON schema

```json
{
  "figure_type": "architecture",
  "layout_direction": "left-to-right",
  "components": [
    {
      "name": "VisualEncoder",
      "chinese_name": "视觉编码器",
      "type": "module",
      "position": "center",
      "color": "blue",
      "shape": "rectangle",
      "size": "medium",
      "children": [],
      "description": "提取 RGB 特征"
    }
  ],
  "connections": [
    {
      "from": "VisualEncoder",
      "to": "Transformer",
      "label": "feat",
      "type": "arrow",
      "description": "视觉特征送入 Transformer"
    }
  ],
  "data_flow": "RGB + tactile 输入 -> 双 Encoder -> CrossAttention -> Decoder -> action",
  "key_innovation": "视觉触觉跨模态 Transformer，预测未来触觉信号驱动动作",
  "animation_suggestion": "依次淡入 Encoders -> CrossAttention -> Decoder -> Action",
  "has_neural_network": true,
  "nn_layers": ["transformer", "attention"],
  "source": "vision_skill",
  "has_precise_bbox": false
}
```

### CLI stdout (JSON contract)

成功：
```json
{"ok": true, "out": "/tmp/figure_analysis.json", "components": 7, "connections": 6}
```

失败 (退码 1)：
```json
{"ok": false, "error": "image not found: /nonexistent.png"}
```

## 3-Round Reasoning Flow

CLI 内部 `_analyze_via_opencode()` 做如下 3 次独立 opencode 调用：

1. **Round 1 — components**：给 image_path + paper_context，问"列出 5-10 个核心模块 (name / chinese_name / type / description)"，要求严格 JSON 数组。
2. **Round 2 — connections**：把 round 1 的模块名列表注入 prompt，问"这些模块之间的数据流向 (from / to / label / type / description)"，要求严格 JSON 数组。
3. **Round 3 — high-level**：问"figure_type / layout_direction / key_innovation / data_flow / animation_suggestion / has_neural_network / nn_layers"，要求严格 JSON 对象。

每一轮失败都会优雅降级 (round 1 失败用 3 个占位组件兜底，round 2/3 失败用空列表 / 默认值)，
不抛异常给上游。失败到底也输出至少 3 个组件的合理 JSON。

## 与 figure_analyzer / SAM3 / arxiv_latex 的关系

```
                               ┌─ arxiv_latex front-door (TikZ/PDF 矢量) ─→ 精确 bbox
analyze_figure_with_vision_llm ┤
                               ├─ Qwen-VL 单次 (默认)  ─────────────────→ 语义 only
                               └─ JSR_USE_SKILL_FIGURE=1 → 本 skill 多轮 → 语义 only
                                                                        ↓
                                                  EditBanana SAM3 后续补 bbox
```

本 skill 只补**语义** (components 名称/描述/连接/创新点)，**不出 bbox** (`has_precise_bbox=False`)。
精确空间信息仍由 EditBanana 下游补；与 `_merge_analyses` / `_merge_latex_and_vision` 配合无缝。

## 程序化调用 (Python)

`src.figure_analyzer.analyze_figure_with_vision_llm()` 已新增 `via_skill` kwarg：

```python
from src.figure_analyzer import analyze_figure_with_vision_llm

# 默认走 Qwen-VL (行为不变)
analysis = analyze_figure_with_vision_llm("path/to/arch.png", paper_context="...")

# 显式走 skill
analysis = analyze_figure_with_vision_llm("path/to/arch.png", paper_context="...",
                                           via_skill=True)
```

或环境变量级开关：

```bash
JSR_USE_SKILL_FIGURE=1 python src/main.py --paper-link https://arxiv.org/abs/2506.15953
```

skill 失败 (subprocess 超时 / opencode 上游 404 / JSON 解析全错) 自动 fallback 到 Qwen-VL，
不会让主流程挂掉。

## Error handling

CLI 在所有失败路径都输出合法 JSON 到 stdout：

```json
{"ok": false, "error": "image not found: /tmp/x.png"}
```

logging 全走 stderr，不污染 stdout。

## Limitations

- opencode 当前主力模型 (deepseek/deepseek-v4-pro 等) 不支持图片直输；
  本 skill 是基于 paper_context + LaTeX 源码路径的 **文本推理 fallback**。
  如果未来 opencode 支持多模态，可在 `_run_opencode_round()` 里补 `--file` 附件。
- 每轮 180s timeout，3 轮串行最多 9 分钟。实测 deepseek-v4-pro 第一轮 (列模块) 在大图 + 长 paper_context 下需要 200-300s, 推荐 `--round-timeout 360`。
- bbox 不出 (`has_precise_bbox=False`)；下游 SAM3 / arxiv_latex / EditBanana 配合用。
- `paper_context` 越详细 (caption + abstract + method 段落) 召回越准；空 context 退化为
  通用占位组件。
