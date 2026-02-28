from src.distribution import bilibili


def test_upload_sync_facade_uses_asyncio_run(monkeypatch):
    called = {"run": False}

    def fake_run(coro):
        called["run"] = True
        # close coro to avoid runtime warning in test
        coro.close()
        return "BV123"

    monkeypatch.setattr(bilibili.asyncio, "run", fake_run)

    result = bilibili.upload(
        video_path="/tmp/demo.mp4",
        title="title",
        tags="tag",
        desc="desc",
        cover_path=None,
        tid=188,
        access_token="token",
    )

    assert called["run"] is True
    assert result == "BV123"
