import os

CACHE_DIR = "./cache"
PIC_DIR = "./pic"
OUTPUT_DIR = "./output"
FONT_PATH = r"./font/SIMHEI.TTF"
BILIBILI_COOKIES_FILE = "bilibili_cookies.pkl"
API_KEYS = {
    "openai": os.getenv("OPENAI_API_KEY"),
    "dashscope": os.getenv("DASHSCOPE_API_KEY"),
}
