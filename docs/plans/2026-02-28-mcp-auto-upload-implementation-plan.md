# MCP Dual-Platform Auto Upload Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add parameter-driven automatic upload orchestration for Bilibili and Xiaohongshu, with default dual-platform upload and partial-success behavior.

**Architecture:** Keep video generation in `src/main.py`, move upload control into a new `src/distribution/orchestrator.py`, and normalize platform upload entrypoints to synchronous APIs used by orchestrator. Isolate each platform failure so one failure never blocks the other, then return a structured summary.

**Tech Stack:** Python 3.10, asyncio, MCP Python client, requests, argparse, pytest.

---

### Task 1: Add platform parsing and orchestration skeleton

**Files:**
- Create: `src/distribution/orchestrator.py`
- Test: `tests/distribution/test_orchestrator.py`

**Step 1: Write the failing test**

```python
from src.distribution.orchestrator import parse_platforms


def test_parse_platforms_default_dual():
    assert parse_platforms(None) == ["bilibili", "xiaohongshu"]


def test_parse_platforms_none_disables_upload():
    assert parse_platforms("none") == []


def test_parse_platforms_filters_unknown_values():
    assert parse_platforms("bilibili,foo,xiaohongshu") == ["bilibili", "xiaohongshu"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/distribution/test_orchestrator.py -v`
Expected: FAIL with import error for missing `src.distribution.orchestrator`.

**Step 3: Write minimal implementation**

```python
# src/distribution/orchestrator.py
VALID_PLATFORMS = {"bilibili", "xiaohongshu"}


def parse_platforms(raw: str | None) -> list[str]:
    if raw is None:
        return ["bilibili", "xiaohongshu"]
    value = raw.strip().lower()
    if not value or value == "none":
        return []
    result = []
    for item in value.split(","):
        platform = item.strip()
        if platform in VALID_PLATFORMS and platform not in result:
            result.append(platform)
    return result
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/distribution/test_orchestrator.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/distribution/test_orchestrator.py src/distribution/orchestrator.py
git commit -m "feat: add upload platform parsing helper"
```

### Task 2: Fix Xiaohongshu sync/async mismatch and expose stable sync calls

**Files:**
- Modify: `src/distribution/xiaohongshu.py`
- Test: `tests/distribution/test_xiaohongshu_sync_api.py`

**Step 1: Write the failing test**

```python
from src.distribution.xiaohongshu import XiaohongshuMCPUploader


def test_check_login_status_calls_sync_request(monkeypatch):
    uploader = XiaohongshuMCPUploader()

    def fake_request(method, params=None):
        assert method == "check_login_status"
        return {"is_logged_in": True}

    monkeypatch.setattr(uploader, "_request", fake_request)
    assert uploader.check_login_status() is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/distribution/test_xiaohongshu_sync_api.py -v`
Expected: FAIL because `_request` is async and returns coroutine in sync context.

**Step 3: Write minimal implementation**

```python
# change _request to synchronous def
# def _request(self, method: str, params: dict = None) -> Optional[dict]:
#     ...
# and keep check_login_status/publish_note/publish_video as sync callers
```

Also add missing function exported by `distribution/__init__.py`:

```python
def check_login_status() -> bool:
    uploader = XiaohongshuMCPUploader()
    return uploader.check_login_status()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/distribution/test_xiaohongshu_sync_api.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/distribution/xiaohongshu.py tests/distribution/test_xiaohongshu_sync_api.py
git commit -m "fix: normalize xiaohongshu uploader to sync api"
```

### Task 3: Add Bilibili synchronous facade and correct call site behavior

**Files:**
- Modify: `src/distribution/bilibili.py`
- Test: `tests/distribution/test_bilibili_sync_entry.py`

**Step 1: Write the failing test**

```python
from src.distribution import bilibili


def test_upload_sync_facade_uses_asyncio_run(monkeypatch):
    called = {"run": False}

    def fake_run(coro):
        called["run"] = True
        return "BV123"

    monkeypatch.setattr(bilibili.asyncio, "run", fake_run)
    result = bilibili.upload(
        video_path="/tmp/a.mp4",
        title="t",
        tags="a,b",
        desc="d",
        cover_path=None,
        tid=188,
        access_token="tok",
    )
    assert called["run"] is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/distribution/test_bilibili_sync_entry.py -v`
Expected: FAIL if sync facade is not consistently used by main flow.

**Step 3: Write minimal implementation**

```python
# Ensure upload(...) remains stable sync facade
# Keep all async details internal to upload_video_to_bilibili_mcp(...)
# Ensure parameter names align: video_desc not video_description
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/distribution/test_bilibili_sync_entry.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/distribution/bilibili.py tests/distribution/test_bilibili_sync_entry.py
git commit -m "fix: keep bilibili uploader sync facade stable"
```

### Task 4: Implement upload orchestrator with partial-success summary

**Files:**
- Modify: `src/distribution/orchestrator.py`
- Test: `tests/distribution/test_orchestrator.py`

**Step 1: Write the failing test**

```python
from src.distribution.orchestrator import upload_generated_content


def test_partial_success_does_not_raise(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    cover = tmp_path / "c.png"
    video.write_bytes(b"x")
    cover.write_bytes(b"x")

    monkeypatch.setattr(
        "src.distribution.orchestrator.upload_bilibili",
        lambda **kwargs: "BV1"
    )

    def fail_xhs(**kwargs):
        raise RuntimeError("xhs error")

    monkeypatch.setattr("src.distribution.orchestrator.upload_xiaohongshu_note", fail_xhs)

    result = upload_generated_content(
        platforms=["bilibili", "xiaohongshu"],
        video_path=str(video),
        cover_path=str(cover),
        video_title="t",
        video_desc="d",
        cn_titles=["中文题目"],
        origin_titles=["English title"],
    )

    assert result["bilibili"]["ok"] is True
    assert result["xiaohongshu"]["ok"] is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/distribution/test_orchestrator.py::test_partial_success_does_not_raise -v`
Expected: FAIL before orchestration is implemented.

**Step 3: Write minimal implementation**

```python
def upload_generated_content(...):
    result = {}
    # Bilibili branch with try/except
    # Xiaohongshu branch with try/except
    # Build xiaohongshu title/content/images from runtime artifacts
    return result
```

Include helper functions:
- `_build_xhs_title(...)`
- `_build_xhs_content(...)`
- `_collect_xhs_images(...)`

**Step 4: Run test to verify it passes**

Run: `pytest tests/distribution/test_orchestrator.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/distribution/orchestrator.py tests/distribution/test_orchestrator.py
git commit -m "feat: add upload orchestrator with partial success handling"
```

### Task 5: Integrate orchestrator into CLI main flow

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_main_platforms.py`

**Step 1: Write the failing test**

```python
from src.main import parse_args


def test_platforms_default_is_dual(monkeypatch):
    monkeypatch.setattr("sys.argv", ["prog", "--filename", "cs.RO"])
    args = parse_args()
    assert args.platforms == "bilibili,xiaohongshu"
```

And test upload call dispatch:

```python
def test_main_calls_orchestrator(monkeypatch):
    # monkeypatch generate_daily_arxiv_summary and upload_generated_content
    # assert upload_generated_content called with parsed platforms
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_platforms.py -v`
Expected: FAIL before `--platforms` integration.

**Step 3: Write minimal implementation**

```python
# add parser arg:
# parser.add_argument("--platforms", type=str, default="bilibili,xiaohongshu", ...)
# parse platforms via parse_platforms
# replace direct bilibili call with upload_generated_content(...)
# log summary result
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_platforms.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/main.py tests/test_main_platforms.py
git commit -m "feat: add --platforms and integrate upload orchestrator"
```

### Task 6: Update docs and add regression checks

**Files:**
- Modify: `README.md`
- Modify: `README_EN.md`

**Step 1: Write doc expectations as checks**

Use simple grep-based check:

```bash
rg -n "--platforms|xiaohongshu|bilibili" README.md README_EN.md
```

Expected: existing docs incomplete for new behavior.

**Step 2: Update docs with exact examples**

Add examples:

```bash
python src/main.py --filename "cs.RO"
python src/main.py --filename "cs.RO" --platforms bilibili
python src/main.py --filename "cs.RO" --platforms xiaohongshu
python src/main.py --filename "cs.RO" --platforms none
```

Explain partial-success behavior explicitly.

**Step 3: Run sanity checks**

Run:

```bash
pytest tests/distribution/test_orchestrator.py tests/distribution/test_xiaohongshu_sync_api.py tests/distribution/test_bilibili_sync_entry.py tests/test_main_platforms.py -v
python -m src.main --help
```

Expected: tests PASS, help shows `--platforms`.

**Step 4: Commit**

```bash
git add README.md README_EN.md
git commit -m "docs: document platform-controlled dual upload workflow"
```

## Final Validation Checklist

1. Single-platform and dual-platform modes behave as specified.
2. `none` mode skips all upload actions.
3. One platform failure does not block the other.
4. Logs include per-platform result and final summary.
5. No direct async call from `main.py` without orchestration boundary.
