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

# API Keys - 环境变量优先，YAML 兜底
LLM_API_KEY = os.getenv("LLM_API_KEY") or _config.get("llm_api_key")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") or _config.get("dashscope_api_key")

# Directory and File Paths - 全大写全局变量
CACHE_DIR = _config.get("cache_dir", "./cache")
PIC_DIR = _config.get("pic_dir", "./pic")
OUTPUT_DIR = _config.get("output_dir", "./output")
_raw_font_path = _config.get("font_path", "./font/SIMHEI.TTF")
FONT_PATH = str(PROJECT_ROOT / _raw_font_path) if not os.path.isabs(_raw_font_path) else _raw_font_path
BILIBILI_COOKIES_FILE = _config.get("bilibili_cookies_file", "bilibili_cookies.pkl")

# Environment Variables
TESSDATA_PREFIX = _config.get("tessdata_prefix", "/home/jdh/Projects/VlogCutter/JushenRenji/font")

# Language Settings
OUTPUT_LANGUAGE = _config.get("output_language", "zh")

# 兼容旧版本的 API_KEYS 字典
API_KEYS = {
    "openai": os.getenv("OPENAI_API_KEY"),
    "dashscope": DASHSCOPE_API_KEY,
    "llm": LLM_API_KEY,
}
