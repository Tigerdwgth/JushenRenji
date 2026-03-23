# 多平台上传模块
from .orchestrator import parse_platforms, upload_generated_content


def upload_bilibili(*args, **kwargs):
    from .bilibili import upload

    return upload(*args, **kwargs)


def upload_to_xiaohongshu(*args, **kwargs):
    from .xiaohongshu import upload_to_xiaohongshu as _impl

    return _impl(*args, **kwargs)


def publish_note(*args, **kwargs):
    from .xiaohongshu import publish_note as _impl

    return _impl(*args, **kwargs)


def publish_video(*args, **kwargs):
    from .xiaohongshu import publish_video as _impl

    return _impl(*args, **kwargs)


def check_login_status(*args, **kwargs):
    from .xiaohongshu import check_login_status as _impl

    return _impl(*args, **kwargs)

__all__ = [
    "upload_bilibili",
    "upload_to_xiaohongshu",
    "publish_note",
    "publish_video",
    "check_login_status",
    "parse_platforms",
    "upload_generated_content",
]
