"""小红书 MCP 上传模块单元测试。"""
import base64
import json
import inspect
from unittest.mock import MagicMock, patch

import pytest

from src.distribution.xiaohongshu import (
    XiaohongshuMCPUploader,
    _extract_text,
    _extract_image_bytes,
    _call_tool,
    check_login_status,
    publish_note,
)


# ---------------------------------------------------------------------------
# _extract_text / _extract_image_bytes
# ---------------------------------------------------------------------------

class TestExtractHelpers:
    def test_extract_text_from_content(self):
        result = {"content": [{"type": "text", "text": "hello"}]}
        assert _extract_text(result) == "hello"

    def test_extract_text_returns_none_when_no_text(self):
        result = {"content": [{"type": "image", "data": "abc"}]}
        assert _extract_text(result) is None

    def test_extract_text_returns_none_on_empty(self):
        assert _extract_text({}) is None
        assert _extract_text(None) is None

    def test_extract_image_bytes_decodes_base64(self):
        raw = b"fake-image-data"
        encoded = base64.b64encode(raw).decode()
        result = {"content": [{"type": "image", "data": encoded}]}
        assert _extract_image_bytes(result) == raw

    def test_extract_image_bytes_returns_none_when_no_image(self):
        result = {"content": [{"type": "text", "text": "hello"}]}
        assert _extract_image_bytes(result) is None


# ---------------------------------------------------------------------------
# _call_tool
# ---------------------------------------------------------------------------

class TestCallTool:
    def test_uses_tools_call_method(self):
        """确认发出的 JSON-RPC 请求使用 tools/call 方法。"""
        captured = {}

        def fake_post(url, json=None, headers=None, timeout=None):
            if json and json.get("method") == "tools/call":
                captured.update(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"Mcp-Session-Id": "test-session-123"}
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
            return resp

        # 需要重置模块级 session 状态
        with patch("src.distribution.xiaohongshu.ensure_mcp_service", return_value=True), \
             patch("src.distribution.xiaohongshu._mcp_session", None), \
             patch("src.distribution.xiaohongshu._mcp_session_id", None):
            import requests as _req
            with patch.object(_req.Session, "post", side_effect=fake_post):
                _call_tool("check_login_status", {})

        assert captured.get("method") == "tools/call"
        assert captured["params"]["name"] == "check_login_status"

    def test_returns_none_on_service_unavailable(self):
        with patch("src.distribution.xiaohongshu.ensure_mcp_service", return_value=False):
            assert _call_tool("check_login_status") is None

    def test_returns_none_on_mcp_error(self):
        fake_result = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "not found"}}

        with patch("src.distribution.xiaohongshu.ensure_mcp_service", return_value=True), \
             patch("src.distribution.xiaohongshu._ensure_mcp_session", return_value=True), \
             patch("src.distribution.xiaohongshu._mcp_session") as mock_session, \
             patch("src.distribution.xiaohongshu._mcp_session_id", "test-sid"):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = fake_result
            mock_session.post.return_value = mock_resp
            assert _call_tool("nonexistent_tool") is None

    def test_returns_none_on_tool_error_flag(self):
        fake_result = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "isError": True,
                "content": [{"type": "text", "text": "tool failed"}],
            },
        }

        with patch("src.distribution.xiaohongshu.ensure_mcp_service", return_value=True), \
             patch("src.distribution.xiaohongshu._ensure_mcp_session", return_value=True), \
             patch("src.distribution.xiaohongshu._mcp_session") as mock_session, \
             patch("src.distribution.xiaohongshu._mcp_session_id", "test-sid"):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = fake_result
            mock_session.post.return_value = mock_resp
            assert _call_tool("some_tool") is None


# ---------------------------------------------------------------------------
# check_login_status
# ---------------------------------------------------------------------------

class TestCheckLoginStatus:
    def test_returns_true_when_logged_in(self):
        fake_result = {"content": [{"type": "text", "text": json.dumps({"is_logged_in": True})}]}
        with patch("src.distribution.xiaohongshu._call_tool", return_value=fake_result):
            assert check_login_status() is True

    def test_returns_false_when_not_logged_in(self):
        fake_result = {"content": [{"type": "text", "text": json.dumps({"is_logged_in": False})}]}
        with patch("src.distribution.xiaohongshu._call_tool", return_value=fake_result):
            assert check_login_status() is False

    def test_returns_false_on_service_down(self):
        with patch("src.distribution.xiaohongshu._call_tool", return_value=None):
            assert check_login_status() is False


# ---------------------------------------------------------------------------
# XiaohongshuMCPUploader.publish_note
# ---------------------------------------------------------------------------

class TestPublishNote:
    def _make_uploader_connected(self):
        uploader = XiaohongshuMCPUploader()
        return uploader

    def test_publish_note_uses_publish_content_tool(self, tmp_path):
        """确认 publish_note 调用 publish_content 工具。"""
        img = tmp_path / "test.png"
        img.write_bytes(b"fake-image")
        called_with = {}

        def fake_call_tool(tool_name, arguments=None, timeout=120):
            called_with["tool"] = tool_name
            called_with["args"] = arguments
            return {"content": [{"type": "text", "text": json.dumps({"note_id": "abc123"})}]}

        uploader = self._make_uploader_connected()
        with patch("src.distribution.xiaohongshu._call_tool", side_effect=fake_call_tool), \
             patch("src.distribution.xiaohongshu._copy_to_docker_mount", side_effect=lambda p, s="images": f"/app/{s}/{__import__('os').path.basename(p)}"):
            result = uploader.publish_note(
                title="测试标题",
                content="测试内容",
                images=[str(img)],
            )

        assert called_with["tool"] == "publish_content"
        assert called_with["args"]["title"] == "测试标题"
        assert result == {"note_id": "abc123"}

    def test_title_truncated_to_20_chars(self, tmp_path):
        img = tmp_path / "a.png"
        img.write_bytes(b"fake")
        called_with = {}

        def fake_call_tool(tool_name, arguments=None, timeout=120):
            called_with["args"] = arguments
            return {"content": [{"type": "text", "text": "{}"}]}

        uploader = self._make_uploader_connected()
        long_title = "a" * 30
        with patch("src.distribution.xiaohongshu._call_tool", side_effect=fake_call_tool), \
             patch("src.distribution.xiaohongshu._copy_to_docker_mount", side_effect=lambda p, s="images": f"/app/{s}/{__import__('os').path.basename(p)}"):
            uploader.publish_note(title=long_title, content="x", images=[str(img)])

        assert len(called_with["args"]["title"]) == 20

    def test_returns_none_on_failure(self):
        uploader = self._make_uploader_connected()
        with patch("src.distribution.xiaohongshu._call_tool", return_value=None):
            assert uploader.publish_note(title="t", content="c", images=["/x"]) is None


# ---------------------------------------------------------------------------
# XiaohongshuMCPUploader.publish_video 封面传递测试
# ---------------------------------------------------------------------------

class TestPublishVideo:
    def test_publish_video_calls_correct_tool(self):
        """确认 publish_video 调用 publish_with_video 工具。"""
        called_with = {}

        def fake_call_tool(tool_name, arguments=None, timeout=120):
            called_with["tool"] = tool_name
            called_with["args"] = arguments
            return {"content": [{"type": "text", "text": json.dumps({"note_id": "vid123"})}]}

        uploader = XiaohongshuMCPUploader()
        with patch("src.distribution.xiaohongshu._call_tool", side_effect=fake_call_tool), \
             patch("src.distribution.xiaohongshu._copy_to_docker_mount", return_value="/app/data/video.mp4"):
            result = uploader.publish_video(
                title="视频测试",
                content="内容",
                video_path="/tmp/video.mp4",
            )

        assert called_with["tool"] == "publish_with_video"
        assert called_with["args"]["video"] == "/app/data/video.mp4"
        assert "cover" not in called_with["args"]
        assert result == {"note_id": "vid123"}


# ---------------------------------------------------------------------------
# 同步接口验证（无协程）
# ---------------------------------------------------------------------------

class TestSyncInterface:
    def test_all_public_functions_are_synchronous(self):
        """确认所有公开上传接口均为同步函数。"""
        from src.distribution import xiaohongshu as xhs
        for name in ("publish_note", "publish_video", "upload_to_xiaohongshu",
                     "check_login_status", "get_login_qrcode"):
            fn = getattr(xhs, name)
            assert not inspect.iscoroutinefunction(fn), f"{name} 不应该是协程函数"
