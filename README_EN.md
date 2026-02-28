# Paper2Video App

This project converts PDF files into explanatory videos. Users can input a PDF file, and the application will extract text and images to generate engaging videos.

## Project Structure
```
├── cache
├── config.yaml
├── font
├── output
├── src
│   ├── distribution          # Multi-platform upload modules
│   │   ├── __init__.py
│   │   ├── bilibili.py      # Bilibili upload
│   │   └── xiaohongshu.py   # Xiaohongshu upload
│   ├── llm_tools
│   ├── utils
│   ├── main.py
│   └── video_creator.py
├── requirements.txt
├── README.md
└── README_EN.md
```

## Features

1. **PDF Processing**: Extract text and images from PDF files.
2. **Video Creation**: Combine extracted content into videos.
3. **Summary & Title Generation**: Generate engaging summaries and titles.
4. **Multi-platform Upload**: Support Bilibili, Xiaohongshu, etc.

## Installation

```bash
conda create -n paperagent python=3.10
conda activate paperagent
pip install -r requirements.txt
pip install mcp  # MCP client library
pip3 install torch torchvision torchaudio  # Linux
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126  # Windows
pip install -e .
```

Fix tesseract compatibility in `anaconda3/envs/paperagent/lib/site-packages/deepdoctection/extern/tessocr.py`:

```python
# Add before line 263
if not results:
   return all_results
```

```python
# Modify line 181
with open(tmp_name, "rb") as output_file:
```

---

# Multi-Platform Upload

## Bilibili MCP Upload

### 1. Install Node.js
```bash
conda install conda-forge::nodejs
nvm use 18  # Must use Node 18
```

### 2. Install MCP Bilibili Service
```bash
npm install -g @mcpcn/mcp-bilibili
```

### 3. Install MCP Python Library
```bash
pip install mcp
```

### 4. Usage
```python
from src.distribution.bilibili import upload_video_to_bilibili_mcp

# Upload video
result = upload_video_to_bilibili_mcp(
    video_path="/path/to/video.mp4",
    video_title="Video Title",
    video_tags="tag1,tag2",
    video_description="Description",
    cover_path="/path/to/cover.png",
    tid=188  # Tech category
)

if result:
    print(f"Upload successful! BV ID: {result}")
```

### 5. First-time Authorization
First run will:
1. Open browser with authorization QR code
2. Scan to login to Bilibili
3. Get `state` value
4. Input `state` in terminal to complete authorization

---

## Xiaohongshu MCP Upload

### 1. Install Go
```bash
# Windows: https://go.dev/dl/
# Linux: conda install -c conda-forge go
```

### 2. Start MCP Service
```bash
# Docker (recommended)
docker run -p 18060:18060 xpzouying/xiaohongshu-mcp

# Source
git clone https://github.com/xpzouying/xiaohongshu-mcp
cd xiaohongshu-mcp
go run .
```

### 3. Install MCP Python Library
```bash
pip install mcp requests
```

### 4. Usage
```python
from src.distribution.xiaohongshu import upload_to_xiaohongshu

# Image note
upload_to_xiaohongshu(
    title="Note title (max 20 chars)",
    content="Content (max 1000 chars)",
    images=["/path/to/image1.jpg"],
    is_video=False
)

# Video note
upload_to_xiaohongshu(
    title="Video title",
    content="Video description",
    video_path="/path/to/video.mp4",
    cover_path="/path/to/cover.png",
    is_video=True
)
```

### 5. Functions
| Function | Description |
|----------|-------------|
| `check_login_status()` | Check login status |
| `publish_note()` | Publish image note |
| `publish_video()` | Publish video |
| `search_notes()` | Search content |
| `get_user_profile()` | Get user profile |

---

## Run Application

```bash
# Default: auto-upload to both Bilibili and Xiaohongshu (image note)
python src/main.py --filename "{papername}"

# Upload to Bilibili only
python src/main.py --filename "{papername}" --platforms bilibili

# Upload to Xiaohongshu only (image note)
python src/main.py --filename "{papername}" --platforms xiaohongshu

# Disable upload, generate local video only
python src/main.py --filename "{papername}" --platforms none
```

Notes:
- `--platforms` accepts comma-separated values from `bilibili,xiaohongshu`; default is `bilibili,xiaohongshu`.
- Upload flow is partial-success tolerant: one platform failure does not block the other.

---

## License

MIT License
