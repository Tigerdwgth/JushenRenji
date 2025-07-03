import os
import yaml
from pathlib import Path

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

def load_config():
    """从 YAML 文件加载配置"""
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 加载配置
_config = load_config()

# API Keys - 全大写全局变量
LLM_API_KEY = _config.get("llm_api_key") or os.getenv("LLM_API_KEY")
DASHSCOPE_API_KEY = _config.get("dashscope_api_key") or os.getenv("DASHSCOPE_API_KEY")

# Directory and File Paths - 全大写全局变量
CACHE_DIR = _config.get("cache_dir", "./cache")
PIC_DIR = _config.get("pic_dir", "./pic")
OUTPUT_DIR = _config.get("output_dir", "./output")
FONT_PATH = _config.get("font_path", "./font/SIMHEI.TTF")
BILIBILI_COOKIES_FILE = _config.get("bilibili_cookies_file", "bilibili_cookies.pkl")

# Environment Variables
TESSDATA_PREFIX = _config.get("tessdata_prefix", "/home/jdh/Projects/VlogCutter/JushenRenji/font")

# 兼容旧版本的 API_KEYS 字典
API_KEYS = {
    "openai": os.getenv("OPENAI_API_KEY"),
    "dashscope": DASHSCOPE_API_KEY,
    "llm": LLM_API_KEY,
}
