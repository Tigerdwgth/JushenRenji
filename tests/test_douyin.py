"""测试 src/distribution/douyin.py 的 subprocess 包装层(全部 mock 子进程)。"""
import json
import os
import tempfile
from unittest.mock import patch, MagicMock


def _make_video_file():
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(b"fake mp4")
    return path


def _make_cookie_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({"cookies": [], "origins": []}, f)
    return path


def test_normalize_tags_str_passthrough():
    from src.distribution.douyin import _normalize_tags
    assert _normalize_tags("VLA,机器人") == "VLA,机器人"


def test_normalize_tags_list_join():
    from src.distribution.douyin import _normalize_tags
    assert _normalize_tags(["VLA", " 机器人 ", ""]) == "VLA,机器人"


def test_normalize_tags_none():
    from src.distribution.douyin import _normalize_tags
    assert _normalize_tags(None) == ""


def test_upload_returns_id_on_helper_success():
    """helper stdout 输出 ok=true 应返回 id"""
    video = _make_video_file()
    cookie = _make_cookie_file()
    try:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = '{"ok": true, "id": "douyin"}\n'
        proc.stderr = ""
        with patch("src.distribution.douyin.subprocess.run", return_value=proc) as mock_run, \
             patch("src.distribution.douyin.os.path.isdir", return_value=True), \
             patch("src.distribution.douyin._resolve_sau_python", return_value="/fake/py"):
            from src.distribution.douyin import upload
            result = upload(
                video_path=video,
                title="测试标题",
                tags=["VLA", "机器人"],
                account_file=cookie,
                sau_dir="/fake/sau",
            )
        assert result == "douyin"
        called_args = mock_run.call_args.args[0]
        assert "--video" in called_args
        assert "--title" in called_args
        assert "--tags" in called_args
        # tags 应被规范化
        idx = called_args.index("--tags")
        assert called_args[idx + 1] == "VLA,机器人"
        assert "--immediate" in called_args
    finally:
        os.unlink(video)
        os.unlink(cookie)


def test_upload_returns_none_on_helper_failure():
    """helper 输出 ok=false 应返回 None"""
    video = _make_video_file()
    cookie = _make_cookie_file()
    try:
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = '{"ok": false, "error": "cookie 已失效"}\n'
        proc.stderr = ""
        with patch("src.distribution.douyin.subprocess.run", return_value=proc), \
             patch("src.distribution.douyin.os.path.isdir", return_value=True), \
             patch("src.distribution.douyin._resolve_sau_python", return_value="/fake/py"):
            from src.distribution.douyin import upload
            result = upload(video_path=video, title="t",
                             account_file=cookie, sau_dir="/fake/sau")
        assert result is None
    finally:
        os.unlink(video)
        os.unlink(cookie)


def test_upload_returns_none_on_missing_video():
    """视频不存在直接 None, 不调 subprocess"""
    cookie = _make_cookie_file()
    try:
        with patch("src.distribution.douyin.subprocess.run") as mock_run:
            from src.distribution.douyin import upload
            result = upload(video_path="/nonexistent.mp4", title="t",
                             account_file=cookie, sau_dir="/fake/sau")
        assert result is None
        mock_run.assert_not_called()
    finally:
        os.unlink(cookie)


def test_upload_returns_none_on_missing_cookie():
    """cookie 不存在直接 None"""
    video = _make_video_file()
    try:
        with patch("src.distribution.douyin.subprocess.run") as mock_run:
            from src.distribution.douyin import upload
            result = upload(video_path=video, title="t",
                             account_file="/nonexistent.json",
                             sau_dir="/fake/sau")
        assert result is None
        mock_run.assert_not_called()
    finally:
        os.unlink(video)


def test_upload_passes_cover_path_when_exists():
    """传 cover_path 且文件存在应附加 --thumb 参数"""
    video = _make_video_file()
    cookie = _make_cookie_file()
    cover = _make_video_file()  # 当作图片占位
    try:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = '{"ok": true, "id": "douyin"}'
        proc.stderr = ""
        with patch("src.distribution.douyin.subprocess.run", return_value=proc) as mock_run, \
             patch("src.distribution.douyin.os.path.isdir", return_value=True), \
             patch("src.distribution.douyin._resolve_sau_python", return_value="/fake/py"):
            from src.distribution.douyin import upload
            upload(video_path=video, title="t", cover_path=cover,
                    account_file=cookie, sau_dir="/fake/sau")
        called = mock_run.call_args.args[0]
        assert "--thumb" in called
    finally:
        os.unlink(video)
        os.unlink(cookie)
        os.unlink(cover)


def test_upload_handles_subprocess_timeout():
    """subprocess 超时应返回 None, 不抛"""
    import subprocess as _sp
    video = _make_video_file()
    cookie = _make_cookie_file()
    try:
        with patch("src.distribution.douyin.subprocess.run",
                   side_effect=_sp.TimeoutExpired(cmd="x", timeout=1)), \
             patch("src.distribution.douyin.os.path.isdir", return_value=True), \
             patch("src.distribution.douyin._resolve_sau_python", return_value="/fake/py"):
            from src.distribution.douyin import upload
            result = upload(video_path=video, title="t",
                             account_file=cookie, sau_dir="/fake/sau",
                             timeout=1)
        assert result is None
    finally:
        os.unlink(video)
        os.unlink(cookie)


def test_upload_returns_none_on_garbage_stdout():
    """helper 输出非 JSON 应返回 None"""
    video = _make_video_file()
    cookie = _make_cookie_file()
    try:
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = "garbage not json\n"
        proc.stderr = "Traceback ..."
        with patch("src.distribution.douyin.subprocess.run", return_value=proc), \
             patch("src.distribution.douyin.os.path.isdir", return_value=True), \
             patch("src.distribution.douyin._resolve_sau_python", return_value="/fake/py"):
            from src.distribution.douyin import upload
            result = upload(video_path=video, title="t",
                             account_file=cookie, sau_dir="/fake/sau")
        assert result is None
    finally:
        os.unlink(video)
        os.unlink(cookie)
