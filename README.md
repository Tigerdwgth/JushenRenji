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
│   │   ├── bilibili.py       # B站上传
│   │   └── xiaohongshu.py    # 小红书上传
│   ├── llm_tools
│   ├── utils
│   ├── main.py
│   └── video_creator.py
├── requirements.txt
├── README.md
└── README_EN.md
```

## 功能

1. **PDF处理**：从PDF文件中提取文本和图片。
2. **视频创建**：将提取的内容合成视频。
3. **摘要和标题生成**：生成引人注目的摘要和标题，以吸引观众。
4. **多平台上传**：支持B站、小红书等平台自动上传。

## 使用说明

### 安装依赖

```bash
conda create -n paperagent python=3.10
conda activate paperagent
pip install -r requirements.txt
pip install mcp  # MCP 客户端库
pip3 install torch torchvision torchaudio  # Linux
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126  # Windows
pip install -e .
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

## B站 MCP 上传方式

### 1. 安装 Node.js
```bash
conda install conda-forge::nodejs
nvm use 18  # 必须使用 Node 18
```

### 2. 安装 MCP Bilibili 服务
```bash
npm install -g @mcpcn/mcp-bilibili
```

### 3. 安装 MCP Python 库
```bash
pip install mcp
```

### 4. 使用示例
```python
from src.distribution.bilibili import upload_video_to_bilibili_mcp

# 上传视频
result = upload_video_to_bilibili_mcp(
    video_path="/path/to/video.mp4",
    video_title="视频标题",
    video_tags="标签1,标签2",
    video_description="视频描述",
    cover_path="/path/to/cover.png",
    tid=188  # 科技分区
)

if result:
    print(f"上传成功! BV号: {result}")
```

### 5. 首次授权流程
首次运行时会自动：
1. 打开浏览器显示授权二维码
2. 扫码登录B站
3. 获取 `state` 值
4. 终端输入 `state` 完成授权

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
python src/main.py --filename "{papername}" --platforms none
```

说明：
- `--platforms` 支持 `bilibili,xiaohongshu` 的逗号组合，默认值为 `bilibili,xiaohongshu`。
- 平台上传采用“部分成功”策略：某一个平台失败不会阻塞另一个平台。

---

## 贡献

欢迎任何形式的贡献！请提交问题或拉取请求。

## 许可证

该项目遵循MIT许可证。
