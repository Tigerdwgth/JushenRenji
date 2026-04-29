"""测试 src/distribution/analytics/xhs_stats.py + xhs_stats_helper.py"""
import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest


def _make_completed_proc(stdout: str, returncode: int = 0, stderr: str = ""):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.stdout = stdout
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


def test_parse_helper_output_finds_last_json():
    from src.distribution.analytics.xhs_stats import _parse_helper_output
    stdout = (
        "noise line\n"
        '{"ok": false, "error": "old"}\n'
        '{"ok": true, "stats": {"views": 100, "likes": 10}}\n'
        ""
    )
    out = _parse_helper_output(stdout)
    assert out is not None
    assert out["ok"] is True
    assert out["stats"]["views"] == 100


def test_parse_helper_output_no_json():
    from src.distribution.analytics.xhs_stats import _parse_helper_output
    assert _parse_helper_output("not json\nnot json either") is None
    assert _parse_helper_output("") is None


def test_fetch_note_stats_raises_on_invalid_args():
    from src.distribution.analytics.xhs_stats import fetch_note_stats
    with pytest.raises(ValueError):
        fetch_note_stats("", "token")
    with pytest.raises(ValueError):
        fetch_note_stats("note_id", "")


def test_fetch_note_stats_subprocess_args(tmp_path):
    """验证 subprocess 调用参数 + JSON 契约."""
    sau_dir = tmp_path / "sau"
    venv_py = sau_dir / ".venv/bin/python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("#!/usr/bin/env python3\n")
    venv_py.chmod(0o755)
    cookie = tmp_path / "cookies.json"
    cookie.write_text("{}")

    fake_stats = {"views": 9999, "likes": 88, "collects": 7,
                  "comments": 3, "shares": 2, "raw": {"x": 1}}
    fake_proc = _make_completed_proc(
        stdout=json.dumps({"ok": True, "stats": fake_stats}) + "\n"
    )

    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        from src.distribution.analytics.xhs_stats import fetch_note_stats
        out = fetch_note_stats(
            "noteX", "tokenY",
            account_file=str(cookie), sau_dir=str(sau_dir), timeout=10,
        )

    assert out == fake_stats
    args, kwargs = mock_run.call_args
    cmd = args[0]
    # python -m ... helper
    assert cmd[0] == str(venv_py)
    assert "-m" in cmd
    assert "src.distribution.analytics.xhs_stats_helper" in cmd
    assert "--note-id" in cmd and "noteX" in cmd
    assert "--xsec-token" in cmd and "tokenY" in cmd


def test_fetch_note_stats_raises_on_helper_error(tmp_path):
    sau_dir = tmp_path / "sau"
    sau_dir.mkdir()
    cookie = tmp_path / "cookies.json"
    cookie.write_text("{}")
    fake_proc = _make_completed_proc(
        stdout=json.dumps({"ok": False, "error": "cookie expired"}) + "\n",
        returncode=1,
    )
    with patch("subprocess.run", return_value=fake_proc):
        from src.distribution.analytics.xhs_stats import (XhsStatsError,
                                                          fetch_note_stats)
        with pytest.raises(XhsStatsError, match="cookie expired"):
            fetch_note_stats(
                "noteX", "tokenY",
                account_file=str(cookie), sau_dir=str(sau_dir),
            )


def test_fetch_note_stats_no_json_in_stdout(tmp_path):
    sau_dir = tmp_path / "sau"
    sau_dir.mkdir()
    cookie = tmp_path / "cookies.json"
    cookie.write_text("{}")
    fake_proc = _make_completed_proc(
        stdout="random crash output\nstack trace...\n", returncode=1
    )
    with patch("subprocess.run", return_value=fake_proc):
        from src.distribution.analytics.xhs_stats import (XhsStatsError,
                                                          fetch_note_stats)
        with pytest.raises(XhsStatsError, match="无合法 JSON"):
            fetch_note_stats(
                "noteX", "tokenY",
                account_file=str(cookie), sau_dir=str(sau_dir),
            )


def test_helper_coerce_int_handles_chinese_units():
    from src.distribution.analytics.xhs_stats_helper import _coerce_int
    assert _coerce_int("1.2万") == 12000
    assert _coerce_int("3亿") == 300000000
    assert _coerce_int("2.5k") == 2500
    assert _coerce_int("1500") == 1500
    assert _coerce_int(None) == 0
    assert _coerce_int("") == 0
    assert _coerce_int("invalid") == 0


def test_helper_extract_stats_picks_max():
    """xhs note dict 的字段名在不同版本不同, 取 max."""
    from src.distribution.analytics.xhs_stats_helper import _extract_stats
    note = {
        "interact_info": {
            "liked_count": 100, "collected_count": 50,
            "comment_count": 8, "share_count": 3,
        },
        "view_count": "1.5万",  # 应被识别为 15000
        "liked_count": 99,      # interact 的 100 更大
    }
    out = _extract_stats(note)
    assert out["views"] == 15000
    assert out["likes"] == 100   # 而不是 99
    assert out["collects"] == 50
    assert out["comments"] == 8
    assert out["shares"] == 3
