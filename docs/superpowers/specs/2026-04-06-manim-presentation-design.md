---
title: Manim 演示视频生成功能设计
date: 2026-04-06
status: approved
---

# Manim 演示视频生成功能

## 概述

为 JushenRenji 项目新增基于 ManimCE 的动画演示功能。从现有流水线生成的视频脚本（structured_plan）中识别公式、模型架构、算法流程等内容，回溯原始论文提取 LaTeX 公式和结构细节，由 LLM 自动生成 ManimCE 代码并渲染为动画视频。

## 目标

- **阶段 B（优先）**：独立的 Manim 演示生成，通过 `--manim` 参数触发
- **阶段 C（后续）**：将 Manim 片段集成到现有 Ken Burns 流水线中

## 架构

```
论文输入 (arXiv ID / PDF)
        │
        ▼
  PDF 处理 (复用 pdf_processor.py)
        │
        ▼
  生成 structured_plan (复用现有流程)
        │
        ▼
  ManimEngine.analyze_script()
  ├── LLM 扫描脚本，定位公式/模型/流程描述
  └── 回溯原始 PDF 文本提取 LaTeX 公式
        │
        ▼
  场景映射 JSON: [{section, type, latex/description, manim_code}, ...]
        │
        ▼
  ManimEngine.render_scene() × N
  ├── 写入临时 .py 文件
  ├── manim render 执行
  └── 失败时：错误反馈 LLM → 重试（最多 3 次）
        │
        ▼
  ManimEngine.compose()
  ├── moviepy 拼接所有场景视频
  ├── 可选：合并 TTS 音频
  └── 可选：导出 GIF
        │
        ▼
  输出：mp4（默认）/ gif（可选）
```

## 场景类型与映射规则

| 脚本内容 | 识别特征 | Manim 场景类型 |
|---------|---------|--------------|
| 数学公式 | LaTeX 表达式、"公式"、"定义为" | FormulaScene — 公式推导动画 |
| 模型结构描述 | "网络结构"、"编码器/解码器"、层名称 | ArchitectureScene — 架构图动画 |
| 算法步骤/流程 | "步骤"、"首先...然后..."、"pipeline" | FlowScene — 流程动画 |
| 开场/总结 | 脚本首尾段 | TitleScene — 标题/总结动画 |

场景与 structured_plan 的 section（opening/intro/method/results）一一对应。

## 核心模块：ManimEngine

```python
class ManimEngine:
    def __init__(self, paper_text, structured_plan=None, output_dir="./output/manim")
    def analyze_script(self) -> list[dict]        # 分析脚本，生成场景映射
    def generate_manim_code(self, scene_info) -> str  # LLM 生成 Manim 代码
    def render_scene(self, code, scene_name, quality="medium", fmt="mp4", max_retries=3) -> str
    def compose(self, scene_videos, tts_audio=None) -> str  # 拼接视频
    def run(self, tts=False, fmt="mp4") -> str     # 主入口
```

### 渲染质量
- low (480p) — 快速预览
- medium (720p) — 默认
- high (1080p) — 最终输出

### 重试机制
render 失败 → 捕获 stderr → LLM 修复代码 → 再次 render（最多 3 次）

## CLI 参数

```bash
python src/main.py --filename "paper" --manim                    # 基本用法
python src/main.py --filename "paper" --manim --manim-tts        # 带 TTS
python src/main.py --filename "paper" --manim --manim-fmt gif    # 输出 GIF
python src/main.py --filename "paper" --manim --manim-quality high  # 高质量
```

## 新增 Prompts

| Key | 用途 |
|-----|------|
| manim_analyze_script | 扫描脚本+原文，输出场景映射 JSON |
| manim_generate_formula | FormulaScene 代码生成 |
| manim_generate_architecture | ArchitectureScene 代码生成 |
| manim_generate_flow | FlowScene 代码生成 |
| manim_generate_title | TitleScene 代码生成 |
| manim_fix_code | 渲染失败时修复代码 |

## 文件变更

### 新增
- `src/manim_engine.py` — 核心引擎

### 修改
- `src/main.py` — 新增 --manim 系列参数
- `src/llm_tools/prompts.py` — 新增 6 个 prompt
- `requirements.txt` — 新增 manim 依赖

## 依赖

- `manim` (ManimCE)
- `texlive-latex-extra` + `texlive-fonts-extra`（LaTeX 公式渲染）
