import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "smoke: 真实第三方 API 调用 (默认 skip, -m smoke 才跑)",
    )


def pytest_collection_modifyitems(config, items):
    """默认跳过 smoke 标记的测试; 仅在 -m smoke 显式选择时才执行."""
    keyword = (config.getoption("-m") or "").strip()
    if "smoke" in keyword:
        return
    skip_smoke = __import__("pytest").mark.skip(
        reason="smoke test (需 -m smoke 显式开启)"
    )
    for item in items:
        if "smoke" in item.keywords:
            item.add_marker(skip_smoke)
