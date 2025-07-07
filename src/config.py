import os
import yaml
from pathlib import Path

# ==================== 项目配置管理 ====================
"""
项目配置管理模块

该模块负责加载和管理项目的所有配置参数，包括：
- API 密钥配置
- 文件路径配置  
- 环境变量配置
- 语言设置配置

配置文件格式：YAML
配置文件位置：项目根目录/config.yaml
"""

# 获取项目根目录 - 用于定位配置文件和其他资源
PROJECT_ROOT = Path(__file__).parent.parent

def load_config():
    """
    从 YAML 文件加载配置
    
    Returns:
        dict: 配置字典，包含所有配置参数
        
    Raises:
        FileNotFoundError: 当配置文件不存在时抛出异常
    """
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 加载配置字典
_config = load_config()

# ==================== API 密钥配置 ====================
"""
API 密钥配置

支持从配置文件或环境变量中读取 API 密钥，环境变量优先级更高。
用于访问各种 AI 服务和大语言模型 API。
"""

# LLM API 密钥 - 用于访问大语言模型服务（如通义千问等）
# 优先从环境变量 LLM_API_KEY 读取，如果不存在则从配置文件读取
LLM_API_KEY = _config.get("llm_api_key") or os.getenv("LLM_API_KEY")

# 达摩院 DashScope API 密钥 - 用于访问阿里云灵积平台的 AI 服务
# 优先从环境变量 DASHSCOPE_API_KEY 读取，如果不存在则从配置文件读取
DASHSCOPE_API_KEY = _config.get("dashscope_api_key") or os.getenv("DASHSCOPE_API_KEY")

# ==================== 目录和文件路径配置 ====================
"""
目录和文件路径配置

定义项目中各种资源的存储路径，包括缓存、图片、输出文件等。
所有路径都支持相对路径和绝对路径，相对路径相对于项目根目录。
"""

# 缓存目录 - 用于存储临时文件、下载的论文、生成的音频等
# 默认：./cache，可在配置文件中修改
CACHE_DIR = _config.get("cache_dir", "./cache")

# 图片目录 - 用于存储从 PDF 提取的图片、生成的图表等
# 默认：./pic，可在配置文件中修改
PIC_DIR = _config.get("pic_dir", "./pic")

# 输出目录 - 用于存储最终生成的视频文件
# 默认：./output，可在配置文件中修改
OUTPUT_DIR = _config.get("output_dir", "./output")

# 字体文件路径 - 用于视频字幕渲染的中文字体文件
# 默认：./font/SIMHEI.TTF，支持其他 TTF 字体文件
FONT_PATH = _config.get("font_path", "./font/SIMHEI.TTF")

# B站 Cookies 文件路径 - 用于自动上传视频到 B站 的认证信息
# 默认：bilibili_cookies.pkl，存储登录状态的 pickle 文件
BILIBILI_COOKIES_FILE = _config.get("bilibili_cookies_file", "bilibili_cookies.pkl")

# ==================== 环境变量配置 ====================
"""
环境变量配置

用于配置系统环境变量，主要用于第三方工具的集成。
"""

# Tesseract OCR 数据目录 - 用于 OCR 文字识别的训练数据路径
# 指向包含 tessdata 训练数据的目录，用于从 PDF 图片中提取文字
# 默认：项目根目录/font，该目录包含 eng.traineddata 等文件
TESSDATA_PREFIX = _config.get("tessdata_prefix", "/home/jdh/Projects/VlogCutter/JushenRenji/font")

# ==================== 语言设置配置 ====================
"""
语言设置配置

控制系统的输出语言，影响生成的视频内容、提示词等的语言。
"""

# 输出语言设置 - 控制系统生成内容的语言
# 支持的值：
# - "zh": 中文输出，适合中文用户和中文视频制作
# - "en": 英文输出，适合国际用户和英文视频制作
# 默认：zh（中文）
OUTPUT_LANGUAGE = _config.get("output_language", "zh")

# ==================== 兼容性配置 ====================
"""
兼容性配置

为了保持与旧版本代码的兼容性，提供 API_KEYS 字典格式的访问方式。
"""

# API 密钥字典 - 兼容旧版本代码的访问方式
# 包含各种 AI 服务的 API 密钥，方便统一管理和访问
API_KEYS = {
    # OpenAI API 密钥 - 用于访问 GPT 等 OpenAI 服务
    # 仅从环境变量读取，确保安全性
    "openai": os.getenv("OPENAI_API_KEY"),
    
    # DashScope API 密钥 - 阿里云灵积平台密钥
    "dashscope": DASHSCOPE_API_KEY,
    
    # LLM API 密钥 - 通用大语言模型 API 密钥
    "llm": LLM_API_KEY,
}
