#!/usr/bin/env python3
"""SAU venv 内执行的小红书评论拉取/回帖 CLI helper.

stdout 单行 JSON: {"ok": bool, "data": [...] | null, "error": "..."}
所有 logging 走 stderr.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from pathlib import Path

logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")


def _emit(payload: dict, code: int = 0):
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(code)


def _build_xhs_client(sau_dir: Path):
    sys.path.insert(0, str(sau_dir))
    try:
        from xhs import XhsClient  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return None, f"xhs 未安装: {exc}"
    cookie_str = os.environ.get("XHS_COOKIE", "")
    if not cookie_str:
        # SAU 项目下默认 cookie 文件
        cf = sau_dir / "cookiesFile.json"
        if cf.exists():
            try:
                cookie_str = json.loads(cf.read_text())
                if isinstance(cookie_str, dict):
                    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_str.items())
            except Exception:  # noqa: BLE001
                cookie_str = ""
    if not cookie_str:
        return None, "XHS_COOKIE 未设置"
    try:
        client = XhsClient(cookie=cookie_str)
        return client, None
    except Exception as exc:  # noqa: BLE001
        return None, f"XhsClient 初始化失败: {exc}"


def _cmd_pull(args, client) -> dict:
    try:
        all_comments = client.get_note_all_comments(
            args.note_id, xsec_token=args.xsec_token)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"get_note_all_comments: {exc}"}
    out = []
    for c in all_comments or []:
        ctime = c.get("create_time") or 0
        try:
            ctime_int = int(ctime) // 1000 if int(ctime) > 1e11 else int(ctime)
        except Exception:  # noqa: BLE001
            ctime_int = 0
        if args.since_ts and ctime_int and ctime_int < args.since_ts:
            continue
        user = c.get("user_info") or {}
        out.append({
            "id": str(c.get("id") or ""),
            "parent_id": c.get("parent_comment_id") or "",
            "content": c.get("content") or "",
            "nick": user.get("nickname") or user.get("user_nickname") or "",
            "ctime": ctime_int,
        })
    return {"ok": True, "data": out}


def _cmd_reply(args, client) -> dict:
    try:
        client.comment_user(args.note_id, args.comment_id, args.content)
        return {"ok": True, "data": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"comment_user: {exc}"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sau-dir", default=os.environ.get(
        "SAU_DIR",
        "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload",
    ))
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("pull")
    pp.add_argument("--note-id", required=True)
    pp.add_argument("--xsec-token", default="")
    pp.add_argument("--since-ts", type=int, default=0)

    pr = sub.add_parser("reply")
    pr.add_argument("--note-id", required=True)
    pr.add_argument("--comment-id", required=True)
    pr.add_argument("--content", required=True)

    args = p.parse_args()
    sau_dir = Path(args.sau_dir).expanduser().resolve()
    if not sau_dir.exists():
        _emit({"ok": False, "error": f"SAU 目录不存在: {sau_dir}"}, 1)

    client, err = _build_xhs_client(sau_dir)
    if err:
        _emit({"ok": False, "error": err}, 1)

    try:
        if args.cmd == "pull":
            _emit(_cmd_pull(args, client))
        elif args.cmd == "reply":
            _emit(_cmd_reply(args, client))
        else:
            _emit({"ok": False, "error": f"unknown cmd: {args.cmd}"}, 2)
    except Exception as exc:  # noqa: BLE001
        _emit({"ok": False, "error": f"helper crash: {exc}",
               "tb": traceback.format_exc()[-500:]}, 1)


if __name__ == "__main__":  # pragma: no cover
    main()
