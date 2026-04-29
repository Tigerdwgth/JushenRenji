#!/usr/bin/env python3
"""SAU venv 内执行的小红书笔记统计抓取 helper.

由 ``src.distribution.analytics.xhs_stats`` subprocess 调用.
所有日志走 stderr, stdout 仅一行 JSON:
    {"ok": true, "stats": {views, likes, collects, comments, shares, raw}}
    {"ok": false, "error": "..."}

Usage:
    sau_venv_python -m src.distribution.analytics.xhs_stats_helper \
        --note-id <id> --xsec-token <token> --account-file <cookies.json>
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict

logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("xhs_stats_helper")


def _emit(payload: Dict[str, Any], code: int = 0):
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(code)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--note-id", required=True)
    p.add_argument("--xsec-token", required=True)
    p.add_argument("--account-file", required=True)
    p.add_argument(
        "--xsec-source", default="pc_search",
        help="xhs API 要求的 xsec_source, 默认 pc_search"
    )
    return p.parse_args()


def _coerce_int(v: Any) -> int:
    """xhs 字段有时是 str / 带 '万', 这里统一成 int."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s:
        return 0
    # 处理 "1.2万" / "1200" / "1k"
    multiplier = 1
    if s.endswith("万"):
        multiplier = 10000
        s = s[:-1]
    elif s.endswith("亿"):
        multiplier = 100000000
        s = s[:-1]
    elif s.lower().endswith("k"):
        multiplier = 1000
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except (TypeError, ValueError):
        return 0


def _extract_stats(note: Dict[str, Any]) -> Dict[str, Any]:
    """从 xhs note dict 提取标准字段. xhs 库不同版本字段名差异:
       liked_count / like_count / likes; collected_count / collect_count;
       view_count / impression_count / pv_count; share_count;
       comment_count.
    """
    interact = note.get("interact_info") or note.get("interactInfo") or {}
    candidates = {
        "views": [
            note.get("view_count"), note.get("impression_count"),
            note.get("pv_count"), interact.get("view_count"),
            interact.get("impression_count"),
        ],
        "likes": [
            interact.get("liked_count"), note.get("liked_count"),
            note.get("like_count"), note.get("likes"),
        ],
        "collects": [
            interact.get("collected_count"), note.get("collected_count"),
            note.get("collect_count"),
        ],
        "comments": [
            interact.get("comment_count"), note.get("comment_count"),
            note.get("comments"),
        ],
        "shares": [
            interact.get("share_count"), note.get("share_count"),
            note.get("shares"),
        ],
    }
    out: Dict[str, Any] = {}
    for key, vals in candidates.items():
        chosen = 0
        for v in vals:
            cv = _coerce_int(v)
            if cv > chosen:
                chosen = cv
        out[key] = chosen
    return out


def _run(args) -> Dict[str, Any]:
    try:
        from xhs import XhsClient  # type: ignore
    except Exception as exc:
        return {"ok": False, "error": f"xhs import 失败: {exc}"}

    try:
        with open(args.account_file, "r", encoding="utf-8") as f:
            cookie_blob = json.load(f)
    except FileNotFoundError:
        return {"ok": False, "error": f"cookie 文件不存在: {args.account_file}"}
    except Exception as exc:
        return {"ok": False, "error": f"cookie 解析失败: {exc}"}

    # SAU 的 xhs cookie 通常是 storage_state 格式: {"cookies": [...]}
    # 也可能是简单 dict {name: value}
    cookie_str = ""
    if isinstance(cookie_blob, dict):
        if isinstance(cookie_blob.get("cookies"), list):
            parts = [
                f"{c.get('name')}={c.get('value')}"
                for c in cookie_blob["cookies"]
                if c.get("name")
            ]
            cookie_str = "; ".join(parts)
        else:
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_blob.items())

    if not cookie_str:
        return {"ok": False, "error": "cookie 文件解析后为空"}

    try:
        client = XhsClient(cookie=cookie_str)
    except Exception as exc:
        return {"ok": False, "error": f"XhsClient 构造失败: {exc}"}

    try:
        note = client.get_note_by_id(
            args.note_id,
            xsec_source=args.xsec_source,
            xsec_token=args.xsec_token,
        )
    except TypeError:
        # 旧版 xhs.get_note_by_id 不接受 xsec_*, 兜底
        try:
            note = client.get_note_by_id(args.note_id)
        except Exception as exc:
            return {"ok": False, "error": f"get_note_by_id 失败: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"get_note_by_id 失败: {exc}"}

    if not isinstance(note, dict):
        return {"ok": False, "error": f"note 非 dict: {type(note)}"}

    stats = _extract_stats(note)
    stats["raw"] = note
    return {"ok": True, "stats": stats}


def main():
    args = _parse_args()
    try:
        payload = _run(args)
    except Exception as exc:
        payload = {"ok": False, "error": f"helper 异常: {exc}"}
    _emit(payload, 0 if payload.get("ok") else 1)


if __name__ == "__main__":
    main()
