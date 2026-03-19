"""测试 config.py 配置加载"""
import os


def test_config_exports_required_keys():
    """config 模块应导出必要的配置项"""
    from src.config import (
        CACHE_DIR, PIC_DIR, OUTPUT_DIR, FONT_PATH,
        BILIBILI_COOKIES_FILE, OUTPUT_LANGUAGE,
    )
    assert CACHE_DIR is not None
    assert PIC_DIR is not None
    assert OUTPUT_DIR is not None
    assert FONT_PATH is not None
    assert BILIBILI_COOKIES_FILE is not None
    assert OUTPUT_LANGUAGE in ("zh", "en")


def test_config_api_keys_dict():
    """API_KEYS 字典应包含 llm 和 dashscope"""
    from src.config import API_KEYS
    assert "llm" in API_KEYS
    assert "dashscope" in API_KEYS
    assert "openai" in API_KEYS


def test_config_project_root():
    """PROJECT_ROOT 应指向实际项目目录"""
    from src.config import PROJECT_ROOT
    assert os.path.exists(PROJECT_ROOT)
    assert os.path.exists(os.path.join(PROJECT_ROOT, "config.yaml"))


def test_config_no_bgm():
    """config 不应包含 BGM 相关配置（已移除）"""
    import src.config as config_mod
    assert not hasattr(config_mod, "BGM_PATH")
    assert not hasattr(config_mod, "BGM_VOLUME")
