# CLAUDE.md
本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

# 全局规则

- 全程使用中文交流
- 遇到不知道的接口必须要上网搜索或者问我
- 每次更新代码也要更新readme
- 每次更新代码要创建对应的单元测试代码
- 所有prompt 必须要更新在./src/llm_tools/prompts.py 便于随时更改
- mcp使用node v
## 项目概述

论文转视频流水线：从 arXiv 或本地 PDF 提取文本和图片，使用 LLM 生成脚本，通过 DashScope TTS 合成语音，最后使用 moviepy 合成视频。支持上传到 Bilibili 等平台。

## 常用命令

```bash
# 环境搭建
conda create -n paperagent python=3.10
conda activate paperagent
pip install -r requirements.txt
pip install -e .

# 单篇论文转视频
python src/main.py --filename "{论文名或arxiv查询}"

# 生成每日 arXiv 论文总结视频
python src/main.py --filename "cs.RO" --output_language "zh"

# 完整选项
python src/main.py --filename "{query}" --video_length "long" --output_language "zh"

# 控制视频时长（默认300秒）
python src/main.py --filename "{query}" --target_duration 180 --platforms none
```

**前置要求：**
- 安装 [tesseract-ocr](https://tesseract-ocr.github.io/tessdoc/Installation.html)（OCR 功能需要）
- 在 `config.yaml` 中配置 API 密钥 (`llm_api_key`, `dashscope_api_key`)

## 架构

```
src/
├── main.py                 # CLI 入口；解析参数，调用 generate_daily_arxiv_summary
├── paperagent_workflow.py  # 核心流水线编排
│   ├── run_pdf_to_video_pipeline()    # 单篇论文 -> 视频
│   ├── generate_daily_arxiv_summary() # 多篇论文 -> 合并视频
│   └── VideoCreator 类    # moviepy + DashScope TTS 视频合成
├── pdf_processor.py        # PyMuPDF/fitz 封装，提取 PDF 文本和图片
├── llm_tools/
│   ├── llm_agent.py       # LLM 客户端 (qwen/deepseek)；`create_chat_completion()`
│   └── prompts.py         # 提示词字典，key 为函数名（如 generate_summary）
├── distribution/
│   ├── bilibili.py        # 视频上传（使用 cookies）
│   ├── douyin.py
│   └── rednote.py
├── video_creator.py       # 旧版视频创建（可能已弃用）
├── config.py              # 加载 config.yaml；导出 CACHE_DIR、FONT_PATH 等
└── utils/
    └── audio_helpers.py    # TTS/音频处理工具
```

### 数据流程
1. `main.py` → `paperagent_workflow.generate_daily_arxiv_summary()`
2. 从 arXiv 获取论文 → 通过 `get_arxiv_latest.py` 下载 PDF
3. `PDFProcessor` 提取文本和图片（存入 `./pic`）
4. `ImageAgent` (Qwen-VL) 解释图片；结果缓存到 `./cache/image_explanations.json`
5. `llm_agent` 调用 LLM 生成摘要和标题
6. `VideoCreator` 合并图片 + DashScope TTS 音频 → moviepy 视频
7. `auto_upload_bilibili` 上传最终视频

## 关键模式

### 提示词组织
- 在 `src/llm_tools/prompts.py` 中添加提示词，key 为函数名（如 `"generate_summary"`）
- LLM 包装函数（如 `generate_summary()`）使用 `inspect.currentframe().f_code.co_name` 查找对应提示词
- 语言后缀根据 `OUTPUT_LANGUAGE` 配置自动追加

### 图片提取
- `llm_agent.py` 中的 `MANUALLY_EXTRACT_IMAGES` 控制：
  - `False`（默认）：从 PDF 提取图片到 `./pic/`
  - `True`：从 `./pic/` 加载预先准备好的图片

### 配置
- `config.yaml`（根目录）：API 密钥、路径 (`cache_dir`, `pic_dir`, `output_dir`)、`font_path`、`output_language`
- `src/config.py`：加载 YAML；导出大写全局变量（如 `FONT_PATH`, `DASHSCOPE_API_KEY`）

### 日志
- 所有日志写入根目录的 `app.log`
- 中间产物查看 `./cache/`（图片解释 JSON、缓存 PDF）
- 生成视频在 `./output/`，图片在 `./pic/`

## 外部依赖

| 服务 | 用途 | 配置项 |
|------|------|--------|
| DashScope | TTS (cosyvoice-v1, voice=longxiaochun) | `dashscope_api_key` |
| DeepSeek/Qwen | LLM 生成摘要/标题 | `llm_api_key` |
| Bilibili | 视频上传 | `bilibili_cookies_file` |
| tesseract-ocr | OCR 备选方案 | `tessdata_prefix` |

## 重要说明

- **没有自动化测试** - 修改后用 `python src/main.py --filename "/path/to/sample.pdf"` 本地验证
- `config.yaml` 中的 API 密钥应移至环境变量（共享仓库时）
- `src/prompts.py` 和 `src/llm_tools/prompts.py` 同时存在（遗留 vs 新位置）
