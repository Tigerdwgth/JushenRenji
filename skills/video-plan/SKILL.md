---
name: video-plan
description: 为论文生成 5 段式结构化视频讲解脚本（opening/intro/method/results/conclusion），中文、课堂讲解风格、目标 5 分钟。输入是 paper_meta JSON（含 title/abstract/authors/key_points），输出是 5 段 JSON（含 text/duration_sec/key_points 字段）。
---

# Video Plan

## Overview

把论文摘要转成 5 段式视频脚本，给后续 TTS / 字幕 / 视频合成消费。目标：

- 形式：5 段（opening / intro / method / results / conclusion）
- 风格：中文课堂讲解（像老师在讲台上对学生讲），口语化、避免列表式、避免堆术语
- 时长：默认 5 分钟（300 秒），按比例分配每段：
  - opening 30s（10%） — 一句 hook 抛出问题或惊人数据，引出主题
  - intro 60s（20%） — 背景、为什么难、前人怎么做
  - method 120s（40%） — 论文的核心方法，拆解、类比、通俗
  - results 60s（20%） — 关键实验结果与意义
  - conclusion 30s（10%） — 总结 + 启发 + 展望

## 输入：paper_meta JSON

期望字段（缺失时 best-effort）：

```json
{
  "title": "论文英文标题",
  "abstract": "论文 abstract 全文",
  "authors": ["First Last", "..."],
  "key_points": ["亮点 1（可选）", "亮点 2"],
  "venue": "ICRA2025（可选）",
  "github_repo": "https://github.com/foo/bar（可选）"
}
```

只有 `title` 与 `abstract` 是强制；其他都可缺省。

## 输出：5 段 JSON

```json
{
  "opening":    {"text": "...", "duration_sec": 30,  "key_points": ["..."]},
  "intro":      {"text": "...", "duration_sec": 60,  "key_points": ["..."]},
  "method":     {"text": "...", "duration_sec": 120, "key_points": ["..."]},
  "results":    {"text": "...", "duration_sec": 60,  "key_points": ["..."]},
  "conclusion": {"text": "...", "duration_sec": 30,  "key_points": ["..."]}
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | string | 该段连贯的中文讲稿，适合朗读，不含 markdown / 列表 / 公式符号 |
| `duration_sec` | int | 该段目标时长（秒）— 与字数成正比，约 4 字/秒 |
| `key_points` | list[string] | 2-4 条该段要点（自然语言短句） |

## 调用方式（Bash）

跨 conda env 调用必须先激活 `paperagent`：

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate paperagent
cd ~/Projects/VlogCutter/JushenRenji

# 准备 paper_meta JSON
cat > /tmp/paper_meta.json <<'EOF'
{
  "title": "ViTacFormer",
  "abstract": "Cross-modal transformer for visuo-tactile manipulation...",
  "authors": ["...", "..."]
}
EOF

# 跑 skill
python -m src.llm_tools.cli generate-plan \
    --paper-meta /tmp/paper_meta.json \
    --target-duration 300 \
    --language zh \
    --out /tmp/plan_out.json
```

输出 `stdout`（成功）：

```json
{"ok": true, "out": "/tmp/plan_out.json", "sections": ["opening","intro","method","results","conclusion"]}
```

`/tmp/plan_out.json` 内是完整 5 段 JSON。失败时 `{"ok": false, "error": "..."}`，exit code 1，stdout 仍是合法 JSON。

CLI 会自动 `apply_network_workarounds()`；从 GSJts 跑设 `export JSR_NETWORK_PROFILE=gsjts` 即可。

### CLI 参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--paper-meta` | path | (required) | 输入 paper_meta JSON 文件 |
| `--target-duration` | int | 300 | 目标视频总时长（秒）|
| `--language` | string | `zh` | 输出语言（当前仅支持 zh） |
| `--out` | path | (required) | 输出 plan JSON 文件路径 |
| `--opencode-model` | string | `""` | 空则从 `config.yaml.opencode_model` 读 |

## 风格约束（生成脚本时严格执行）

1. 课堂讲解风格：每段开头有自然衔接（"今天来聊聊"、"我们先看看"、"接下来重点讲讲"）
2. 避免列表式：禁止 markdown 列表、bullet、编号
3. 避免堆术语：英文方法名首次出现时翻译或用类比解释
4. 避免夸张词：禁止"首次"、"突破"、"震撼"、"颠覆"
5. 数据真实：禁止虚构数据；论文未提的数字一律不写
6. 段间过渡：method → results 用"那这个方法效果到底如何呢？"等过渡句

## 自检条目（生成后应满足）

- [ ] opening 段是否有 hook（一句话点出痛点 / 惊人数据 / 反直觉发现）？
- [ ] intro 段是否说清楚 "为什么这个问题难"？
- [ ] method 段是否讲清楚 "做什么 + 怎么做"，而非堆论文原文？
- [ ] results 段是否有 1-2 个具体实验数字（来自 abstract）？
- [ ] conclusion 段是否给出 "启发 / 未来方向"，而非只是复读结论？
- [ ] 5 段总字数是否接近 `target_duration * 4`（约 1200 字 @ 5 分钟）？
- [ ] 各段 `text` 字段非空？

## 技术细节（实现注意，给维护者看）

- prompt 模板里的 JSON 花括号必须 `{{` `}}` 转义，否则 `str.format` 报 KeyError（LESSONS 已记）。
- 长 prompt（>5KB）必须用 pipe 模式（`cat prompt | opencode run -m <model> -`），不要 `$(cat file)`，否则 shell 命令行展开会卡死（LESSONS 已记）。
- 失败时 CLI 兜底：opencode 失败 → 调一次 plain `create_chat_completion` → 仍失败 → 写 fallback 5 段空骨架 + `ok=false`。
- 默认 Python 路径（`generate_structured_video_plan(via_skill=False)`）保持单次 DeepSeek 调用，不破坏现有调用方。

## 错误处理

| 错误 | 行为 |
|---|---|
| `--paper-meta` 文件不存在 | exit 1, `{"ok":false,"error":"file not found"}` |
| paper_meta 缺 title/abstract | exit 1, `{"ok":false,"error":"missing required fields"}` |
| opencode 超时 / 不可用 | fallback 到 plain LLM 单次调用 |
| 所有路径均失败 | exit 1, stdout 仍是合法 JSON |

## 与原 Python 路径的关系

- 默认走原 DeepSeek API 单次（`generate_structured_video_plan(via_skill=False)`），向后兼容
- 设 `JSR_USE_SKILL_VIDEO_PLAN=1` 后，`generate_structured_video_plan()` 内部 subprocess 调本 CLI
- skill 路径失败时**自动 fallback** 到原 Python 路径，不抛
