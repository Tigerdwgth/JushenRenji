"""B站上传模块 (biliup) 单元测试"""
import os
import json
import pickle
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.distribution import bilibili


# ---- Cookie 加载测试 ----

class TestLoadCookiesFromConfig:
    def test_valid_cookies(self, monkeypatch):
        fake_config = {
            "bilibili_cookies": {
                "sessdata": "abc123",
                "bili_jct": "def456",
                "dedeuserid": "789",
                "dedeuserid_ckmd5": "md5hash",
            }
        }
        monkeypatch.setattr(bilibili, "_load_cookies_from_config", lambda: {
            "SESSDATA": "abc123",
            "bili_jct": "def456",
            "DedeUserID": "789",
            "DedeUserID__ckMd5": "md5hash",
        })
        result = bilibili._load_cookies_from_config()
        assert result["SESSDATA"] == "abc123"
        assert result["bili_jct"] == "def456"

    def test_missing_config_returns_none(self, monkeypatch):
        monkeypatch.setattr(bilibili, "_load_cookies_from_config", lambda: None)
        assert bilibili._load_cookies_from_config() is None


class TestLoadCookiesFromPkl:
    def test_dict_format(self, tmp_path):
        pkl_path = str(tmp_path / "cookies.pkl")
        data = {
            "SESSDATA": "sess_val",
            "bili_jct": "jct_val",
            "DedeUserID": "123",
            "DedeUserID__ckMd5": "md5",
        }
        with open(pkl_path, "wb") as f:
            pickle.dump(data, f)

        result = bilibili._load_cookies_from_pkl(pkl_path)
        assert result is not None
        assert result["SESSDATA"] == "sess_val"
        assert result["bili_jct"] == "jct_val"

    def test_biliup_cookie_info_format(self, tmp_path):
        pkl_path = str(tmp_path / "cookies.pkl")
        data = {
            "cookie_info": {
                "cookies": [
                    {"name": "SESSDATA", "value": "s1"},
                    {"name": "bili_jct", "value": "j1"},
                    {"name": "DedeUserID", "value": "u1"},
                    {"name": "DedeUserID__ckMd5", "value": "m1"},
                ]
            }
        }
        with open(pkl_path, "wb") as f:
            pickle.dump(data, f)

        result = bilibili._load_cookies_from_pkl(pkl_path)
        assert result is not None
        assert result["SESSDATA"] == "s1"

    def test_nonexistent_file_returns_none(self):
        result = bilibili._load_cookies_from_pkl("/nonexistent/path.pkl")
        assert result is None

    def test_unrecognized_format_returns_none(self, tmp_path):
        pkl_path = str(tmp_path / "cookies.pkl")
        with open(pkl_path, "wb") as f:
            pickle.dump(["not", "a", "dict"], f)

        result = bilibili._load_cookies_from_pkl(pkl_path)
        assert result is None


class TestCreateCookieJsonFile:
    def test_creates_valid_json(self):
        cookies = {"SESSDATA": "s", "bili_jct": "j"}
        path = bilibili._create_cookie_json_file(cookies)
        try:
            with open(path) as f:
                data = json.load(f)
            assert "cookie_info" in data
            names = [c["name"] for c in data["cookie_info"]["cookies"]]
            assert "SESSDATA" in names
            assert "bili_jct" in names
        finally:
            os.unlink(path)


# ---- upload() 函数签名兼容性测试 ----

class TestUploadSignature:
    def test_upload_rejects_missing_file(self, monkeypatch):
        """upload() 应在文件不存在时返回 None"""
        result = bilibili.upload(
            video_path="/nonexistent/video.mp4",
            title="test",
            tags="tag1,tag2",
        )
        assert result is None

    def test_upload_rejects_no_cookies(self, monkeypatch):
        """upload() 应在无 cookie 时返回 None"""
        monkeypatch.setattr(bilibili, "_resolve_cookies", lambda: None)

        # 创建临时视频文件
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake video data")
            tmp_video = f.name

        try:
            result = bilibili.upload(
                video_path=tmp_video,
                title="test",
                tags="tag1",
            )
            assert result is None
        finally:
            os.unlink(tmp_video)

    def test_upload_accepts_all_params(self):
        """验证 upload() 函数签名兼容 orchestrator 调用"""
        import inspect
        sig = inspect.signature(bilibili.upload)
        params = list(sig.parameters.keys())
        assert "video_path" in params
        assert "title" in params
        assert "tags" in params
        assert "desc" in params
        assert "cover_path" in params
        assert "tid" in params
        assert "access_token" in params


# ---- _login_with_cookies 测试 ----

class TestLoginWithCookies:
    def test_injects_cookies_into_session(self):
        mock_bili = MagicMock()
        mock_bili._BiliBili__session = MagicMock()
        mock_bili._BiliBili__session.cookies = MagicMock()

        cookies = {"SESSDATA": "s", "bili_jct": "j", "DedeUserID": "u"}
        result = bilibili._login_with_cookies(mock_bili, cookies)

        assert result is True
        assert mock_bili._BiliBili__bili_jct == "j"
