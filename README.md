# Paper2Video App

该项目是一个将PDF文件转换为讲解视频的应用程序。用户可以输入一个PDF文件，应用程序将提取其中的文本和图片，并生成一个引人注目的讲解视频。

## 项目结构
```
├── cache
├── config.yaml
├── font
├── output
├── src
│   ├── distribution          # 多平台上传模块
│   │   ├── __init__.py
│   │   ├── orchestrator.py   # 上传编排（视频优先，图文降级）
│   │   ├── bilibili.py       # B站上传（biliup Cookie）
│   │   └── xiaohongshu.py    # 小红书上传（MCP 视频+图文）
│   ├── llm_tools
│   │   ├── llm_agent.py      # LLM 客户端（延迟初始化）
│   │   ├── prompts.py        # 所有 prompt 统一管理
│   │   └── image_agent.py    # Qwen-VL 图片解释
│   ├── utils
│   │   └── audio_helpers.py  # TTS/音频安全处理
│   ├── main.py
│   ├── env_setup.py               # 网络配置 + arxiv 链接解析 + JSR_NETWORK_PROFILE
│   ├── figure_analyzer.py         # SAM3(Edit Banana) + Qwen-VL 论文主图精确分析
│   ├── website_video_pipeline.py  # 网页顶部视频转发（下载并双平台发布）
│   ├── video_creator.py      # 视频合成（Ken Burns + 转场 + 字幕）
│   ├── manim_engine.py       # Manim 动画演示引擎
│   └── manim_references/     # Manim 参考代码与最佳实践
├── tests                     # pytest 单元测试
│   ├── distribution/
│   └── ...
├── requirements.txt
├── README.md
└── README_EN.md
```

## 功能

1. **PDF处理**：从PDF文件中提取文本和图片。
2. **视频创建**：Ken Burns 动画 + 淡入淡出转场 + 半透明字幕，支持目标时长控制。
3. **图文语义匹配**：基于 structured_plan 和 image_explanations 中的 recommended_section 字段，将摘要句子按语义匹配到对应图片，章节标题使用真实的 figure_role。
4. **LLM脚本生成**：5段式结构化视频脚本（opening→intro→method→results），课堂讲解风格。
5. **多平台上传**：B站视频上传 + 小红书视频/图文自动上传（视频优先，降级图文）。
6. **TTS并发合成**：DashScope cosyvoice-v1，6线程并发加速。
7. **图片智能筛选**：LLM 打分选取最重要的图片，Qwen-VL 生成图片讲解。
8. **Demo 视频下载**：自动从论文项目主页提取并下载演示视频，嵌入最终视频开头。
9. **网页视频转发**：从研究网页提取顶部主视频、封面和页面摘要，直接转发到 B站 与 小红书。
10. **Manim 动画演示** (v3.1)：自动生成论文的 Manim 数学动画演示视频。
    - opencode + DeepSeek-R1 + manim_skill 最佳实践生成 ManimCE 代码
    - 固定 4 场景结构：标题→背景→方法→实验结果
    - TTS 讲解与 structured_plan 脚本同步
    - 动画后自动切换到论文图片，按 caption 智能匹配
    - 自动文本换行（中英文）+ 边界检查防超框
11. **论文主图精确分析**：SAM3(Edit Banana) + Qwen-VL 双路联合分析，用于 MethodScene。
    - Edit Banana 提取精确 bbox_normalized + 十六进制颜色 + 形状先验
    - Qwen-VL-Max 输出语义 JSON（组件/连接/布局/数据流）
    - 双路结果融合后注入 architecture prompt，省去手工描述结构
    - 有精确 bbox 时，manim_context 仅输出语义（避免与精确坐标冲突）
12. **--paper-link 精准入口**：传入 arxiv URL 直接获取论文元数据，跳过关键词搜索和日期过滤。
13. **arxiv LaTeX 源码直读** (v3.2)：给定 arxiv_id 时优先从 arxiv e-print tarball 提取 TikZ/矢量图元做结构化分析。
    - 模块 `src/arxiv_source_analyzer.py`：对外唯一入口 `try_structured_figure(arxiv_id, image_path, cache_root, paper_context)`
    - 路径 A（TikZ）：展开 `\input/\include` + 用户宏 → 抽 `\begin{figure}` → `parse_tikz_structure` 解析 `\node`/`\draw`
    - 路径 B（raster PDF）：tarball 已含 `.pdf` 图时，`pymupdf.get_drawings()` 抽矢量对象
    - 路径 C（pdflatex 兜底）：仅有 `.tex` 时跑 `pdflatex` 重编译 → 按 figure label 定位页码 → pymupdf 抽矢量
    - 多图时用 Qwen 按 caption 打分选主图；LaTeX 成功后仍跑 Qwen-VL 补语义字段（key_innovation/data_flow/animation_suggestion）
    - 缓存在 `cache/arxiv_src/<aid>/`，含 `.manifest.json` +（可选）`.compiled.pdf`（不放 /tmp）
    - Kill switch：设 `JSR_DISABLE_LATEX_SOURCE=1` 即回退到 SAM3+VL 路径
    - 依赖：`pylatexenc`（>=2.10）、`pymupdf`、系统 `pdflatex`（可选，仅路径 C 需要）
    - 透传入口：`ManimEngine(paper_text, structured_plan, arxiv_id=...)` 或在 `main.py --paper-link` 分支自动透传

## 使用说明

### 安装依赖

```bash
conda create -n paperagent python=3.10
conda activate paperagent
pip install -r requirements.txt
pip install biliup  # B站上传
pip3 install torch torchvision torchaudio  # Linux
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126  # Windows
pip install -e .
pip install manim  # Manim 动画引擎
npm install -g opencode-ai  # opencode（Manim 代码生成）
npx skills add adithya-s-k/manim_skill --yes  # ManimCE 最佳实践
```

### 修复tesseract兼容性问题

请修改 `anaconda3/envs/paperagent/lib/site-packages/deepdoctection/extern/tessocr.py`:

```python
# 263行 前加入
if not results:
   return all_results
```

```python
# 181行 删掉文件后缀名
with open(tmp_name, "rb") as output_file:
```

---

# 多平台上传功能

## B站上传（biliup Cookie 方式）

### 1. 安装依赖
```bash
pip install biliup
```

### 2. 配置 Cookie
在浏览器中登录 bilibili.com，打开 DevTools (F12) → Application → Cookies，复制以下 4 个值填入 `config.yaml`：

```yaml
bilibili_cookies:
  sessdata: "<SESSDATA>"
  bili_jct: "<bili_jct>"
  dedeuserid: "<DedeUserID>"
  dedeuserid_ckmd5: "<DedeUserID__ckMd5>"
```

### 3. 使用示例
```python
from src.distribution.bilibili import upload

result = upload(
    video_path="/path/to/video.mp4",
    title="视频标题",
    tags="标签1,标签2",
    desc="视频描述",
    cover_path="/path/to/cover.png",
    tid=188  # 分区ID
)

if result:
    print(f"上传成功! BV号: {result}")
```

### 4. 命令行测试
```bash
python -m src.distribution.bilibili --test-upload --video ./output/video.mp4 --title "测试" --tags "测试"
```

---

## 小红书 MCP 上传方式

### 1. 安装 Go 环境
```bash
# Windows: https://go.dev/dl/
# Linux: conda install -c conda-forge go
```

### 2. 启动 MCP 服务
```bash
# 方式一：Docker（推荐）
docker run -p 18060:18060 xpzouying/xiaohongshu-mcp

# 方式二：源码运行
git clone https://github.com/xpzouying/xiaohongshu-mcp
cd xiaohongshu-mcp
go run .
```

### 3. 安装 MCP Python 库
```bash
pip install mcp requests
```

### 4. 使用示例
```python
from src.distribution.xiaohongshu import upload_to_xiaohongshu

# 图文模式
upload_to_xiaohongshu(
    title="笔记标题（限20字）",
    content="正文内容（限1000字）",
    images=["/path/to/image1.jpg", "/path/to/image2.png"],
    is_video=False
)

# 视频模式
upload_to_xiaohongshu(
    title="视频标题",
    content="视频描述",
    video_path="/path/to/video.mp4",
    cover_path="/path/to/cover.png",
    is_video=True
)
```

### 5. 小红书MCP工具函数
| 函数 | 功能 |
|------|------|
| `check_login_status()` | 检查登录状态 |
| `publish_note()` | 发布图文笔记 |
| `publish_video()` | 发布视频 |
| `search_notes()` | 搜索内容 |
| `get_user_profile()` | 获取用户信息 |

---

## 运行应用程序

```bash
# 默认双平台自动上传（B站 + 小红书图文）
python src/main.py --filename "{papername}"

# 仅上传 B站
python src/main.py --filename "{papername}" --platforms bilibili

# 仅上传小红书图文
python src/main.py --filename "{papername}" --platforms xiaohongshu

# 禁用上传，仅生成本地视频
python src/main.py --filename “{papername}” --platforms none

# 生成 Manim 动画演示视频
python src/main.py --filename "{papername}" --manim --platforms none

# Manim + TTS 语音讲解
python src/main.py --filename "{papername}" --manim --manim-tts --platforms none

# 高质量 1080p
python src/main.py --filename "{papername}" --manim --manim-quality high --platforms none

# 控制视频时长（默认300秒=5分钟）
python src/main.py --filename “{papername}” --target_duration 180 --platforms none

# 通过 arxiv 链接直接生成 + 上传（推荐，绕过关键词搜索）
JSR_NETWORK_PROFILE=gsjts python src/main.py \\
    --paper-link https://arxiv.org/abs/2410.11758 \\
    --manim --manim-tts --target_duration 300 \\
    --platforms bilibili,xiaohongshu

# --discover 自动选题（HF Daily Papers + arxiv recent + opencode 排序）
# 与 --paper-link / --filename 严格三选一互斥
JSR_NETWORK_PROFILE=gsjts python src/main.py \
    --discover "embodied AI" \
    --discover-sources hf,arxiv \
    --manim --manim-tts --target_duration 300 \
    --platforms bilibili,xiaohongshu

# --discover 跳过 opencode (kill switch, 走启发式)
JSR_DISCOVERY_DISABLE_OPENCODE=1 JSR_NETWORK_PROFILE=gsjts python src/main.py \
    --discover "VLA manipulation" --platforms none

# 自定义选题偏好（默认 config/discovery_profile.yaml）
python src/main.py --discover "world model" \
    --discover-profile config/discovery_profile.yaml --platforms none

# --discover 启用 venues 数据源（profile 里 uncomment venues）
# 例：从 RSS 2025 / NeurIPS 2025 接收论文中挑一篇做选题
# 编辑 config/discovery_profile.yaml 解开 venues: 注释，再正常 --discover

# 将研究网页顶部主视频直接转发到 B站 + 小红书
python src/website_video_pipeline.py --url "https://www.pi.website/research/rlt"

# 仅转发到 B站
python src/website_video_pipeline.py --url "https://www.pi.website/research/rlt" --platforms bilibili
```

说明：
- `--platforms` 支持 `bilibili,xiaohongshu` 的逗号组合，默认值为 `bilibili,xiaohongshu`。
- 平台上传采用”部分成功”策略：某一个平台失败不会阻塞另一个平台。
- `--target_duration` 控制目标视频时长（秒），默认300秒。多篇论文时自动均分到每篇。系统通过文字预算、图片筛选和TTS后裁剪三层机制控制时长。

## 网页视频转发 Pipeline

适用场景：你已经有一个研究网页，希望直接抓取网页顶部主视频并发布到 B站、小红书，而不是重新生成讲解视频。

默认行为：
- 自动抓取页面标题、描述、封面图、PDF 链接与顶部主视频地址
- 自动优先生成中文发布标题；若 LLM 不可用则回退到关键词规则标题
- 下载视频到 `output/`
- 复用现有 B站与小红书上传模块完成发布
- 默认平台为 `bilibili,xiaohongshu`

示例：

```bash
python src/website_video_pipeline.py --url "https://www.pi.website/research/rlt"
python src/website_video_pipeline.py --url "https://www.pi.website/research/rlt" --platforms xiaohongshu
```

说明：
- 当前实现面向 Next.js 研究页，优先提取页面顶部主视频
- 发布标题默认优先使用中文标题，原英文标题仍会保留在简介/正文中
- 小红书视频发布仍受 MCP 限制，上传时可能忽略封面，需在 App 内手动设置

---

## opencode skill 集成 — paper-search

仓库内置 `skills/paper-search/`，把 arxiv（按 topic / 按 venue+year）和 HuggingFace Daily Papers 三种搜索能力包装成 JSON-stdout 的 CLI，方便 opencode 在 `--discover`、`manim` 生成、未来其他流程里直接调。

### 安装本地 skill（推荐，仓库级）

```bash
cd ~/Projects/VlogCutter/JushenRenji
npx skills add ./skills/paper-search --yes
```

执行后 `npx skills` 会把 SKILL.md 同步到 `.agents/skills/paper-search/`，并为本地各 agent（含 opencode / claude code / codex / gemini cli / GitHub Copilot 等）创建 symlink。SKILL.md 改动后重新跑同一条命令即可同步。

### 手动 fallback 安装

如果 `npx skills` 不可用（无 Node 环境）或想直接给 opencode 用：

```bash
mkdir -p .opencode/skills/paper-search
cp -r skills/paper-search/* .opencode/skills/paper-search/
```

### CLI 直接调用

不通过 skill 也能直接跑 CLI（适合脚本 / CI）：

```bash
# 按 topic 搜 arxiv
JSR_NETWORK_PROFILE=gsjts python -m src.discovery_sources.cli arxiv-search \
    --query "diffusion policy" --days 14 --limit 20

# 按会议 + 年份搜 arxiv 接收论文（best-effort 模糊匹配 co: 字段）
JSR_NETWORK_PROFILE=gsjts python -m src.discovery_sources.cli arxiv-by-venue \
    --venue RSS --year 2025 --limit 50

# HF Daily Papers
JSR_NETWORK_PROFILE=gsjts python -m src.discovery_sources.cli hf-daily --limit 20
```

输出统一 JSON 契约：`{"ok": bool, "count": int, "papers": [...]}`，错误时 `ok=false`、`error` 字段、exit code 1，stdout 仍是合法 JSON。

注意：`arxiv-by-venue` 是 best-effort，arxiv `co:` 字段索引并不完全；详见 `skills/paper-search/SKILL.md`。

---

### 视频脚本生成 (skill 路径)

仓库内置 `skills/video-plan/`，把"5 段式结构化视频脚本生成"（opening / intro / method / results / conclusion）包装成 JSON-stdout CLI，方便 opencode / Claude / 其他 agent 在 paper2video 流程外单独调用。

**默认行为不变**：`generate_structured_video_plan(text, ...)` 仍走原 DeepSeek API 单次。设 `JSR_USE_SKILL_VIDEO_PLAN=1` 后，函数内部会改走 subprocess 调本 skill；skill 失败时自动 fallback 回原 Python 路径。

#### 安装本地 skill

```bash
cd ~/Projects/VlogCutter/JushenRenji
npx skills add ./skills/video-plan --yes
```

#### CLI 直接调用

```bash
cat > /tmp/paper_meta.json <<'EOF'
{
  "title": "ViTacFormer",
  "abstract": "Cross-modal transformer for visuo-tactile manipulation...",
  "authors": ["Jane Doe", "John Smith"],
  "key_points": ["跨模态注意力", "200K 预训练"]
}
EOF

JSR_NETWORK_PROFILE=gsjts python -m src.llm_tools.cli generate-plan \
    --paper-meta /tmp/paper_meta.json \
    --target-duration 300 \
    --language zh \
    --out /tmp/plan_out.json
```

输出 stdout：`{"ok": true, "out": "/tmp/plan_out.json", "sections": ["opening","intro","method","results","conclusion"]}`，`/tmp/plan_out.json` 内是 5 段 JSON。

#### 在 paper2video 流程中启用 skill 路径

```bash
JSR_USE_SKILL_VIDEO_PLAN=1 JSR_NETWORK_PROFILE=gsjts python src/main.py \
    --paper-link https://arxiv.org/abs/2506.15953 \
    --target-duration 300
```

`generate_structured_video_plan` 内部会自动 subprocess 调 `python -m src.llm_tools.cli generate-plan`，skill 输出的 5 段会规整成下游期望的 4 段（conclusion 合并到 results 段尾），保持向后兼容。详见 `skills/video-plan/SKILL.md`。

---


### 方法图语义分析 (figure-analysis skill 路径)

仓库内置 `skills/figure-analysis/`，把 `figure_analyzer` 里的"图像语义分析"步骤
（识别 components / connections / key_innovation 等）包装成 JSON-stdout CLI，
内部用 **opencode 多轮 reasoning** 替代 Qwen-VL 单次问到底，
覆盖率更稳，遗漏更少。

**默认行为不变**：`analyze_figure_with_vision_llm(image_path, paper_context)` 仍走原 Qwen-VL `qwen-vl-max` 单次。设 `JSR_USE_SKILL_FIGURE=1` 后，函数会优先 subprocess 调本 skill；skill 失败时自动 fallback 回 Qwen-VL。

opencode 当前主力模型 (deepseek/deepseek-v4-pro 等) 不支持图像直输，本 skill
是基于 `paper_context` (caption / abstract / method 段落) + LaTeX 源码路径的
**文本三轮推理**，分别问：

1. Round 1：列出 5-10 个核心模块 (name / chinese_name / type / description)
2. Round 2：模块之间的连接关系 (from / to / label / type / description)
3. Round 3：figure_type / layout_direction / key_innovation / data_flow / animation_suggestion / has_neural_network / nn_layers

输出 JSON 与 `_merge_analyses` schema 兼容（`source="vision_skill"`, `has_precise_bbox=False`），精确 bbox 仍由 EditBanana / SAM3 / arxiv_latex 等下游路径补。

#### 安装本地 skill

```bash
cd ~/Projects/VlogCutter/JushenRenji
npx skills add ./skills/figure-analysis --yes
```

#### CLI 直接调用

```bash
JSR_NETWORK_PROFILE=gsjts python -m src.figure_cli analyze-figure \
    --image cache/arxiv_src/2506.15953/img/arch.png \
    --paper-context "ViTacFormer: cross-modal transformer for visuo-tactile manipulation" \
    --out /tmp/figure_analysis.json
```

stdout：`{"ok": true, "out": "/tmp/figure_analysis.json", "components": 6, "connections": 5}`。

#### 在 paper2video 流程中启用 skill 路径

```bash
JSR_USE_SKILL_FIGURE=1 JSR_NETWORK_PROFILE=gsjts python src/main.py \
    --paper-link https://arxiv.org/abs/2506.15953 \
    --target-duration 300
```

详见 `skills/figure-analysis/SKILL.md`。

---

### 图片重要性打分 (image-rating skill 路径)

仓库内置 `skills/image-rating/`，把 `llm_tools.llm_agent.rate_image_importance` 的"图片批量打分"步骤包装成 JSON-stdout CLI，内部用 **opencode 多轮决策** 替代原 LLM 单次问到底：

1. Round 1：基于 caption / figure_role / paper_context 给每张图初步打 0-10 分
2. Round 2：自检——视觉化效果差吗？跟其他高分图重复吗？caption 是否对应核心贡献？
3. Round 3：最终分数 + 推荐放在哪一段（opening / intro / method / results / none） + 一句话理由

LESSONS 2026-04-15 Bug1 记过——某次公式图被 LLM 给到 0.92 高分，导致视频里出现长时间公式截图。本 skill 在 prompt 里写明"公式 / 约束 / 损失函数 / 定理截图 ≤ 3 分，section=none"，且在 CLI 代码层 `_enforce_formula_constraint` **再 enforce 一遍**作为双重保险。

**默认行为不变**：`rate_image_importance(captions)` 仍走原 LLM 单次。设 `JSR_USE_SKILL_RATE_IMAGES=1` 后，函数会优先 subprocess 调本 skill；skill 失败时自动 fallback 回原 LLM 单次。返回值始终是 `list[int]`（legacy API 兼容）。

#### 安装本地 skill

```bash
cd ~/Projects/VlogCutter/JushenRenji
npx skills add ./skills/image-rating --yes
```

#### CLI 直接调用

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

输出 stdout：`{"ok": true, "scored": 3, "above_5": 2}`，`/tmp/scores.json` 内每张图含 `image_index / score / reason / recommended_section / rejected` 字段。idx=1 公式图会被自动拉到 ≤ 3 分 + section=none。

#### 在 paper2video 流程中启用 skill 路径

```bash
JSR_USE_SKILL_RATE_IMAGES=1 JSR_NETWORK_PROFILE=gsjts python src/main.py \
    --paper-link https://arxiv.org/abs/2506.15953 \
    --target-duration 300
```

`paperagent_workflow.py` 调用 `rate_image_importance(captions)` 时，环境变量触发后会 subprocess 调 `python -m src.llm_tools.cli rate-images`，得到的多轮决策结果转成 legacy `list[int]` 返回，下游 `select_top_images` 完全无感。详见 `skills/image-rating/SKILL.md`。

---

## 运行测试

```bash
conda activate paperagent
python -m pytest tests/ -v
```

---

## 贡献

欢迎任何形式的贡献！请提交问题或拉取请求。

## 许可证

该项目遵循MIT许可证。
