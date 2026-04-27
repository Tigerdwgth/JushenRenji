---
name: image-rating
description: 多轮决策为论文图片批量打分(0-10) + 推荐放置 section(opening/intro/method/results/none),用于视频图片筛选;公式/约束截图自动降权 ≤ 3 分。当需要从一组论文图候选中挑出适合视频展示的图片并推荐放在哪一段时使用。
---

# Image Rating (P3)

## Overview

本 skill 把 `JushenRenji.src.llm_tools.llm_agent:rate_image_importance` 的"图片重要性打分"步骤抽出来,
用 **opencode 多轮决策** 替代原有的 LLM 单次打分。

| 维度       | 单次 (旧)                       | 多轮 (本 skill)                  |
|------------|---------------------------------|----------------------------------|
| 打分依据   | 一次问一组 caption,易粗放      | 第 1 轮基于元数据初步分          |
| 自检       | 无                              | 第 2 轮自检视觉化效果 + 重复检测 |
| 落位       | 不输出 section                  | 第 3 轮给最终分 + 推荐 section   |
| 公式图     | prompt 提示但容易给高分(LESSONS Bug1) | prompt + 代码层双重硬约束 ≤ 3 |

LESSONS 2026-04-15 Bug1 记过——某次公式图被 LLM 给到 0.92 高分,导致视频里出现长时间公式截图。
本 skill 在 prompt 里写明"公式/约束 ≤ 3 分,section=none",在 CLI 代码层 (`_enforce_formula_constraint`)
**再 enforce 一遍**作为双重保险。

## Cross-conda invocation pattern

必须先激活 `paperagent` 环境:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate paperagent
cd ~/Projects/VlogCutter/JushenRenji
python -m src.llm_tools.cli rate-images \
    --candidates cache/test_image_candidates.json \
    --target-count 5 \
    --out /tmp/scores.json
```

## Tool: rate-images

多轮决策为候选图片打分 + 推荐 section,输出 score JSON。

### Input candidates JSON schema

候选图片文件,JSON 数组,每项:

| 字段             | 类型   | 说明 |
|------------------|--------|------|
| `image_index`    | int    | 候选图序号(下游对齐用) |
| `caption`        | string | 图片题注 / 描述 |
| `figure_role`    | string | 角色: opening/intro/method/results/architecture/ablation 等(可空) |
| `paper_context`  | string | 论文上下文(标题/abstract/method 段落,可空) |

示例:

```json
[
  {
    "image_index": 0,
    "caption": "Figure 1: Overall architecture of ViTacFormer",
    "figure_role": "method",
    "paper_context": "ViTacFormer: cross-modal transformer..."
  },
  {
    "image_index": 1,
    "caption": "Equation 3: Cross-attention loss function L_attn = ...",
    "figure_role": "method",
    "paper_context": "ViTacFormer..."
  }
]
```

### CLI flags

| Flag                | Type   | Default | Description |
|---------------------|--------|---------|-------------|
| `--candidates`      | string | (required) | 候选 JSON 文件路径 |
| `--out`             | string | (required) | 输出 score JSON 路径 |
| `--opencode-model`  | string | (空)    | opencode 模型,缺省读 `config.yaml: opencode_model` (`deepseek/deepseek-v4-pro`) |
| `--target-count`    | int    | 8       | 期望保留多少张评分 ≥ 5 的图(软目标,不强求) |

### 输出 JSON schema

每张候选图对应一条记录,长度与输入相同:

```json
[
  {
    "image_index": 0,
    "caption": "Figure 1: Overall architecture of ViTacFormer",
    "score": 8.5,
    "reason": "高层架构图,核心方法可视化",
    "recommended_section": "method",
    "rejected": false
  },
  {
    "image_index": 1,
    "caption": "Equation 3: Cross-attention loss...",
    "score": 3.0,
    "reason": "公式/约束截图,不适合长时间画面展示",
    "recommended_section": "none",
    "rejected": true
  }
]
```

### CLI stdout (JSON contract)

成功:
```json
{"ok": true, "scored": 5, "above_5": 3}
```

失败 (退码 1):
```json
{"ok": false, "error": "candidates file not found: /tmp/x.json"}
```

## 评分维度

1. **视觉化效果**: 架构图 / 流程图 / 对比图 > 公式图 / 纯文字截图
2. **信息密度**: 总览图 > 局部细节图;单图能讲一个故事 > 多个零碎子图
3. **与脚本对应**: 跟视频段落主题强相关的图分高(method 段配架构图 8 分;放配公式 3 分)
4. **重复检测**: 同主题多图保留信息密度最高的,其余降权(避免视频里反复看同一架构)

## 硬约束

| 约束                                                          | 实现位置 |
|---------------------------------------------------------------|----------|
| 公式/方程/约束/损失/定理截图 → score ≤ 3, section="none"      | prompt + `_enforce_formula_constraint` 双重保险 |
| recommended_section 必须 ∈ {opening, intro, method, results, none} | `_normalize_score_record` 做白名单兜底 |
| score 夹钳到 0-10 浮点                                          | `_normalize_score_record` |
| 输出列表长度 = 输入候选长度                                     | `_rate_images_via_opencode` 用 image_index 对齐 |

## Bash 调用示例

```bash
cat > /tmp/cands.json <<'EOF'
[
  {"image_index": 0, "caption": "Figure 1: Overall architecture", "figure_role": "method", "paper_context": "ViTacFormer"},
  {"image_index": 1, "caption": "Equation 3: Loss function", "figure_role": "method", "paper_context": "ViTacFormer"},
  {"image_index": 2, "caption": "Figure 4: Quantitative comparison", "figure_role": "results", "paper_context": "ViTacFormer"}
]
EOF

JSR_NETWORK_PROFILE=gsjts python -m src.llm_tools.cli rate-images \
    --candidates /tmp/cands.json \
    --target-count 3 \
    --out /tmp/scores.json
```

期望输出:

```
{"ok": true, "scored": 3, "above_5": 2}
```

`/tmp/scores.json` 里 idx=0 (architecture) ≈ 8 分 method, idx=1 (equation) ≤ 3 分 none, idx=2 (quantitative) ≈ 7 分 results。

## 程序化调用 (Python)

`src.llm_tools.llm_agent.rate_image_importance()` 已新增 `via_skill` kwarg:

```python
from src.llm_tools.llm_agent import rate_image_importance

# 默认走原 LLM 单次(行为不变)
scores = rate_image_importance(captions)

# 显式走 skill
scores = rate_image_importance(captions, via_skill=True)
```

或环境变量级开关:

```bash
JSR_USE_SKILL_RATE_IMAGES=1 python src/main.py --paper-link https://arxiv.org/abs/2506.15953
```

skill 失败 (subprocess 超时 / opencode 上游 404 / JSON 解析全错) 自动 fallback 到原 LLM 单次,
不会让主流程挂掉。返回值始终是 `list[int]` (legacy API 兼容)。

## 多轮决策流程 (CLI 内部)

`_rate_images_via_opencode` 通过 prompt 让 opencode 内部依次完成 3 轮:

1. **Round 1 — 初步分**: 基于 caption / figure_role / paper_context 给每张图打 0-10 分。
2. **Round 2 — 自检**: 视觉化效果差吗?跟其他高分图重复吗?caption 是否对应论文核心贡献?
3. **Round 3 — 最终分 + section**: 输出 score / recommended_section / reason / rejected。

每一轮失败都会优雅降级:
- opencode 全挂 → plain LLM 单次兜底
- plain LLM 也挂 → `_fallback_default_scores` 给每张图固定 5 分 + 按 figure_role 简单分流
- 全程公式图硬约束都 enforce(双重保险)

## Error handling

CLI 在所有失败路径都输出合法 JSON 到 stdout:

```json
{"ok": false, "error": "candidates must be JSON list"}
```

logging 全走 stderr,不污染 stdout。

## Limitations

- opencode 当前主力模型不支持图片直输; 本 skill 是基于 caption + figure_role + paper_context
  的**文本推理**。caption 越详细 → 评分越准。
- target_count 是软目标(不强求),实际保留张数取决于打分分布。
- subprocess 一次最多 240s timeout(opencode 路径); 超时自动走 plain LLM fallback。
