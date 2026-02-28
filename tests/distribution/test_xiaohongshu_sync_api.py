import inspect

from src.distribution.xiaohongshu import XiaohongshuMCPUploader


def test_request_method_is_synchronous():
    assert inspect.iscoroutinefunction(XiaohongshuMCPUploader._request) is False


def test_check_login_status_works_with_sync_request(monkeypatch):
    uploader = XiaohongshuMCPUploader()

    def fake_request(method, params=None):
        assert method == "check_login_status"
        return {"is_logged_in": True}

    monkeypatch.setattr(uploader, "_request", fake_request)
    assert uploader.check_login_status() is True
