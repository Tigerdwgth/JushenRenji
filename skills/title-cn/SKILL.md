---
name: title-cn
description: 多轮 reasoning 把英文论文标题翻译为"具身人机"频道风格的中文标题(≤20 字, 保留专有名词, 突出动词)。当需要为 paper2video 视频片段生成中文封面 / 投稿标题时使用。
---

# Title CN (P4)

## Overview

本 skill 把 `JushenRenji.src.llm_tools.llm_agent:generate_video_title` 的"英文标题中文化"步骤抽出来,
用 **opencode 多轮 reasoning** 替代原有的 LLM 单次问到底。

| 维度       | 单次 (旧)                           | 多轮 (本 skill)                       |
|------------|-------------------------------------|---------------------------------------|
| 候选生成   | 一次问 1 个,差就差了                 | 第 1 轮基于英文标题 + abstract 出 3-5 候选 |
| 自检       | 无                                  | 第 2 轮自检字数 / 专有名词 / 动词 / 历史去重 |
| 决策       | 直接抓 LLM 输出                     | 第 3 轮选 top 1 + 输出理由             |

LESSONS 已记: 单轮翻译容易堆术语 (典型反例: "基于跨模态注意力机制的视触觉融合
Transformer"), 而频道风格要求 "{专有名词} {核心动作或卖点}", ≤20 字, 突出动词。
多轮 reasoning + 自检 + 历史范例约束, 大幅降低术语堆砌概率。

## 频道风格约束 ("具身人机")

观察 cache/published_papers.json 历史 250+ 条标题, 总结风格如下:

1. **≤ 20 字** (硬约束)
2. **突出动词 / 动作**: "拆解" / "做" / "学" / "看一遍就会" / "重塑" / "做灵巧操作"
3. **保留英文专有名词**: ViTacFormer / LARY / VistaBot / BESTRO / π0 / RoboMamba
4. **避免堆术语**: 不要 "基于跨模态注意力机制的视触觉融合 Transformer" 这种
5. **典型句式**: `<英文专有名词>: <核心动作或卖点>`

### 历史范例 (从 cache/published_papers.json 真实数据抽取)

好示例:

| 中文标题                                | 评注 |
|----------------------------------------|------|
| `ViTacFormer: 手眼触觉融合做灵巧操作`     | 保留专有名词, 动词"做", 17 字 |
| `VistaBot: 视角鲁棒机器人操控新方法`      | 保留专有名词, 突出"鲁棒新方法", 16 字 |
| `BESTRO: 拆解对手反应学习多人博弈`        | 动词"拆解 / 学习", 15 字       |
| `FAST π0: 高效机器人动作字元`             | 保留 π0 + 概念创新词           |
| `π0: 视觉语言动作流模型重塑通用机器人控制` | 动词"重塑", 略偏长 (注意控制) |
| `MAXMI: 最大互信息准则引领机器人操控概念发现` | 动词"引领",18 字              |

坏示例 (堆术语 / 直译 / 过长):

| 反例                                                       | 问题 |
|-----------------------------------------------------------|------|
| `基于跨模态注意力机制的视触觉融合 Transformer`              | 堆术语,无英文专有名词 |
| `像素级联合嵌入预测架构的端到端世界模型解读`                | 直译, 无动词,28 字     |
| `突破!首次实现机器人多模态融合的革命性新进展`               | 夸张宣传词违禁         |

## Cross-conda invocation pattern

必须先激活 `paperagent` 环境:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate paperagent
cd ~/Projects/VlogCutter/JushenRenji
python -m src.llm_tools.cli title-cn \
    --en-title "ViTacFormer: Learning Cross-Modal Representation for Visuo-Tactile Dexterous Manipulation" \
    --abstract "We propose ViTacFormer, a cross-modal transformer that fuses visual and tactile inputs..." \
    --out /tmp/title_cn.json \
    --max-len 20
```

## Tool: title-cn

多轮决策把英文论文标题翻译为频道风格中文标题。

### 输入字段

| Flag                | Type   | Default | Description |
|---------------------|--------|---------|-------------|
| `--en-title`        | string | (required) | 论文英文原标题 |
| `--abstract`        | string | (空)    | 论文 abstract (可选,用于决定卖点 / 核心动作) |
| `--out`             | string | (required) | 输出 JSON 路径 |
| `--opencode-model`  | string | (空)    | opencode 模型,缺省读 `config.yaml: opencode_model` (`deepseek/deepseek-v4-pro`) |
| `--max-len`         | int    | 20      | 中文标题最大字数 (硬约束) |

### 输出 JSON schema

```json
{
  "cn_title": "ViTacFormer: 手眼触觉融合做灵巧操作",
  "candidates": [
    "ViTacFormer: 手眼触觉融合做灵巧操作",
    "ViTacFormer: 视触觉融合驱动灵巧操作",
    "ViTacFormer: 跨模态融合机器人手眼协调"
  ],
  "reason": "保留 ViTacFormer 专有名词 + 突出'做灵巧操作'动作; 19 字符合预算",
  "char_count": 19
}
```

字段说明:

- `cn_title`: 最终中文标题, 必含英文专有名词 + 中文动作短语, ≤ `max_len` 字
- `candidates`: 第 1 轮生成的 3-5 个候选 (供调用方调试 / 人工 fallback)
- `reason`: 选出 top 1 的理由 (1 句, 中文)
- `char_count`: cn_title 字符数 (含英文 + 中文; 不含首尾空白)

### CLI stdout (JSON contract)

成功:
```json
{"ok": true, "cn_title": "ViTacFormer: 手眼触觉融合做灵巧操作", "len": 19}
```

失败 (退码 1):
```json
{"ok": false, "error": "en_title cannot be empty"}
```

## 多轮决策流程 (CLI 内部)

`_generate_cn_title_via_opencode` 通过 prompt 让 opencode 内部依次完成 3 轮:

1. **Round 1 - 候选生成**: 基于英文标题 + abstract 摘要, 生成 3-5 个候选中文标题
2. **Round 2 - 自检**: 每个候选——
   - 字数是否 ≤ `max_len`?
   - 是否保留了论文方法的专有名词 (CamelCase / ALLCAPS / 带连字符)?
   - 是否有动词 ("做 / 拆解 / 学 / 重塑 / 让 / 看一遍就会" 等)?
   - 是否堆术语 (避免 "基于...的...融合 Transformer")?
3. **Round 3 - 决策**: 从候选中挑 top 1, 输出 cn_title + reason

每一轮失败优雅降级:
- opencode 全挂 → plain LLM 单次兜底
- plain LLM 也挂 → 用启发式规则: 取英文专有名词 + 通用兜底动作短语 (例如
  "ViTacFormer: 论文要点解读")

## 硬约束 (CLI 双重保险)

| 约束                                                       | 实现位置 |
|------------------------------------------------------------|----------|
| `cn_title` 字数 ≤ `max_len` (默认 20)                        | prompt + `_enforce_max_len` 代码层截断 |
| 必须保留英文专有名词 (若英文标题中有 CamelCase/ALLCAPS)      | prompt + `_extract_proper_noun` 后兜底插入 |
| 不得包含夸张宣传词 ("首次", "突破", "震撼", "颠覆" 等)       | `sanitize_generated_title` 共享工具(已有) |
| 缺少冒号分隔 → 自动在英文专有名词后插冒号                    | 与 `generate_video_title` 同样规则 |

## Bash 调用示例

```bash
JSR_NETWORK_PROFILE=gsjts python -m src.llm_tools.cli title-cn \
    --en-title "ViTacFormer: Learning Cross-Modal Representation for Visuo-Tactile Dexterous Manipulation" \
    --abstract "We propose ViTacFormer, a cross-modal transformer..." \
    --out /tmp/title.json \
    --max-len 20
```

期望输出:

```
{"ok": true, "cn_title": "ViTacFormer: 手眼触觉融合做灵巧操作", "len": 19}
```

## 程序化调用 (Python)

`src.llm_tools.llm_agent.generate_video_title()` 已新增 `via_skill` kwarg:

```python
from src.llm_tools.llm_agent import generate_video_title

# 默认走原 LLM 单次 (兼容老调用方)
cn_title = generate_video_title(text)

# 显式走 skill (新)
cn_title = generate_video_title(text, via_skill=True,
                                  paper_title="ViTacFormer: ...",
                                  paper_abstract="We propose...")
```

或环境变量级开关:

```bash
JSR_USE_SKILL_TITLE_CN=1 python src/main.py --paper-link https://arxiv.org/abs/2506.15953
```

skill 失败 (subprocess 超时 / opencode 上游 404 / JSON 解析全错) 自动 fallback 到原 LLM 单次,
不会让主流程挂掉。返回值始终是 `str` (legacy API 兼容)。

## Error handling

CLI 在所有失败路径都输出合法 JSON 到 stdout:

```json
{"ok": false, "error": "en_title cannot be empty"}
```

logging 全走 stderr, 不污染 stdout。

## Limitations

- 多轮决策需要 ~30-60s opencode 推理时间; subprocess 超时上限 240s。
- 若英文标题不含明显专有名词 (例如纯描述性标题 "Learning to Manipulate ..."),
  CLI 会启发式拼一个大写缩写; 质量取决于 abstract 内容。
- `max_len` 是字符数 (英文字符 + 中文字符 + 标点), 默认 20。极端情况下英文专有名词
  本身就可能 > 8 字符, 留给中文部分的空间会被压缩。
