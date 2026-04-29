#!/usr/bin/env python3
"""SAU venv 内执行的抖音上传 CLI helper。

由 src/distribution/douyin.py subprocess 调用。所有日志走 stderr，stdout 仅
输出一行 JSON: {"ok": true, "id": "douyin"} 或 {"ok": false, "error": "..."}。

Usage:
    sau_venv_python -m src.distribution.sau_helpers.upload_douyin \
        --video /path/to/video.mp4 \
        --title "标题" \
        --tags 关键词1,关键词2 \
        --account-file ~/cache/douyin_cookies.json \
        [--thumb /path/to/cover.png] \
        [--immediate] [--debug]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(message)s")


def _emit(payload: dict, code: int = 0):
    """单行 JSON 写 stdout, 然后退出。"""
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(code)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--tags", default="", help="逗号分隔关键词")
    p.add_argument("--account-file", required=True)
    p.add_argument("--thumb", default=None, help="封面图路径(可选)")
    p.add_argument("--immediate", action="store_true",
                   help="立即发布(默认即立即发布)")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--sau-dir", default=os.environ.get(
        "SAU_DIR",
        "/home/jdh/Projects/VlogCutter/third_party/social-auto-upload",
    ))
    return p.parse_args()


async def _run_upload(args) -> dict:
    sau_dir = Path(args.sau_dir).expanduser().resolve()
    if not sau_dir.exists():
        return {"ok": False, "error": f"SAU 目录不存在: {sau_dir}"}

    # SAU 必须从其根目录运行（conf.py 用相对路径）
    sys.path.insert(0, str(sau_dir))
    os.chdir(sau_dir)

    try:
        from uploader.douyin_uploader.main import (  # type: ignore
            DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
            DouYinVideo,
            cookie_auth,
        )
    except Exception as exc:
        return {"ok": False, "error": f"SAU import 失败: {exc}"}

    account_file = Path(args.account_file).expanduser().resolve()
    if not account_file.exists():
        return {"ok": False, "error": f"cookie 文件不存在: {account_file}"}

    # 校验 cookie 仍然有效（避免上传到一半被踢回登录页）
    if not await cookie_auth(str(account_file)):
        return {"ok": False, "error": "cookie 已失效, 请重新登录抖音"}

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        return {"ok": False, "error": f"视频文件不存在: {video_path}"}

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    thumb = None
    if args.thumb:
        thumb = Path(args.thumb).expanduser().resolve()
        if not thumb.exists():
            logging.warning("封面文件不存在, 跳过: %s", thumb)
            thumb = None

    # publish_date=0 表示立即发布(配合 IMMEDIATE 策略)
    publish_date = 0 if args.immediate else 0

    app = DouYinVideo(
        title=args.title,
        file_path=video_path,
        tags=tags,
        publish_date=publish_date,
        thumbnail_landscape_path=thumb,
        thumbnail_portrait_path=thumb,
        account_file=str(account_file),
        publish_strategy=DOUYIN_PUBLISH_STRATEGY_IMMEDIATE,
    )

    try:
        await app.douyin_upload_video()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"上传抛错: {exc}",
            "traceback": traceback.format_exc(limit=5) if args.debug else "",
        }
    return {"ok": True, "id": "douyin"}


def main():
    args = _parse_args()
    try:
        result = asyncio.run(_run_upload(args))
    except Exception as exc:
        result = {"ok": False, "error": f"helper 顶层异常: {exc}"}
    if result.get("ok"):
        _emit(result, code=0)
    else:
        _emit(result, code=1)


if __name__ == "__main__":
    main()
