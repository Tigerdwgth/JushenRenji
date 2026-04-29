#!/usr/bin/env python3
"""SAU venv 内执行的抖音上传 CLI helper。

由 src/distribution/douyin.py subprocess 调用。所有日志走 stderr，stdout 仅
输出一行 JSON: {"ok": true, "id": "douyin"} 或 {"ok": false, "error": "..."}。

两种执行模式:
1. 默认(无 JSR_USE_CDP_DAEMON): 直接调 SAU `DouYinVideo.douyin_upload_video()`,
   每次都 launch chromium + new_context + storage_state(write back)。
2. CDP 模式(JSR_USE_CDP_DAEMON=1): 通过 connect_over_cdp 复用 chromium-daemon 内
   长跑 page, 跑完不写回 cookie (daemon 退出时统一写一次)。

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
    p.add_argument("--daemon-url", default=os.environ.get(
        "JSR_CHROMIUM_DAEMON_URL", "http://localhost:9222"))
    return p.parse_args()


def _use_cdp() -> bool:
    return os.environ.get("JSR_USE_CDP_DAEMON", "0") not in ("0", "", "false", "False")


async def _run_upload_legacy(args, DouYinVideo, cookie_auth, IMMEDIATE) -> dict:
    """老路径: SAU 自己 launch + new_context + storage_state 写回。"""
    account_file = Path(args.account_file).expanduser().resolve()
    if not await cookie_auth(str(account_file)):
        return {"ok": False, "error": "cookie 已失效, 请重新登录抖音"}

    video_path = Path(args.video).expanduser().resolve()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    thumb = None
    if args.thumb:
        thumb = Path(args.thumb).expanduser().resolve()
        if not thumb.exists():
            logging.warning("封面文件不存在, 跳过: %s", thumb)
            thumb = None

    app = DouYinVideo(
        title=args.title,
        file_path=video_path,
        tags=tags,
        publish_date=0,
        thumbnail_landscape_path=thumb,
        thumbnail_portrait_path=thumb,
        account_file=str(account_file),
        publish_strategy=IMMEDIATE,
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


async def _run_upload_cdp(args, DouYinVideo, IMMEDIATE) -> dict:
    """CDP 模式: 复用 daemon page, 直接复用 SAU DouYinVideo 实例方法跑 upload 流程,
    跳过 launch / new_context / storage_state 写回。"""
    import asyncio as _asyncio
    from src.distribution.sau_helpers.cdp_helpers import (
        get_cdp_page, navigate_and_wait, close_cdp,
    )

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        return {"ok": False, "error": f"视频不存在: {video_path}"}
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    thumb = None
    if args.thumb:
        thumb_p = Path(args.thumb).expanduser().resolve()
        if thumb_p.exists():
            thumb = thumb_p
        else:
            logging.warning("封面文件不存在, 跳过: %s", thumb_p)

    app = DouYinVideo(
        title=args.title,
        file_path=video_path,
        tags=tags,
        publish_date=0,
        thumbnail_landscape_path=thumb,
        thumbnail_portrait_path=thumb,
        account_file=args.account_file,  # 仅作占位, CDP 模式不写回
        publish_strategy=IMMEDIATE,
    )
    await app.validate_upload_args()

    pw, browser, context, page = await get_cdp_page(args.daemon_url)
    try:
        # 复用 daemon page nav 到上传页
        await navigate_and_wait(
            page, "https://creator.douyin.com/creator-micro/content/upload")
        await page.locator(
            "div[class^='container'] input"
        ).set_input_files(str(video_path))

        # 等进入发布页 (复用 SAU 内部 v1/v2 双版本 polling 逻辑, 这里简化为 wait_for_url)
        for _ in range(120):
            url = page.url
            if "/content/publish" in url or "/content/post/video" in url:
                break
            await _asyncio.sleep(1)
        else:
            return {"ok": False, "error": "等待进入发布页超时"}
        await _asyncio.sleep(1)

        await app.fill_title_and_description(
            page, app.title, app.desc or app.title, app.tags)

        # 等视频上传完成 (复用 SAU 的 "重新上传" 检测语义)
        for _ in range(900):
            try:
                cnt = await page.locator(
                    '[class^="long-card"] div:has-text("重新上传")').count()
                if cnt > 0:
                    break
                if await page.locator(
                        'div.progress-div > div:has-text("上传失败")').count():
                    await app.handle_upload_error(page)
            except Exception:
                pass
            await _asyncio.sleep(2)
        else:
            return {"ok": False, "error": "等视频上传完成超时"}

        await app.set_thumbnail(page)

        third = '[class^="info"] > [class^="first-part"] div div.semi-switch'
        if await page.locator(third).count():
            cls_str = await page.eval_on_selector(third, "div => div.className")
            if "semi-switch-checked" not in cls_str:
                await page.locator(third).locator(
                    "input.semi-switch-native-control").click()

        # 立即发布 click
        for _ in range(60):
            try:
                if await app._handle_sms_popup(page):
                    pass
                btn = page.get_by_role("button", name="发布", exact=True)
                if await btn.count():
                    await btn.click()
                await page.wait_for_url(
                    "https://creator.douyin.com/creator-micro/content/manage**",
                    timeout=3000,
                )
                break
            except Exception:
                await app.handle_auto_video_cover(page)
                await _asyncio.sleep(0.5)
        else:
            return {"ok": False, "error": "等待发布跳转超时"}

        # CDP 模式 **绝对不要** context.storage_state(path=...) 写回 cookie
        return {"ok": True, "id": "douyin"}
    except Exception as exc:
        return {
            "ok": False,
            "error": f"上传抛错(CDP): {exc}",
            "traceback": traceback.format_exc(limit=5) if args.debug else "",
        }
    finally:
        await close_cdp(pw, browser)


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
    if not account_file.exists() and not _use_cdp():
        return {"ok": False, "error": f"cookie 文件不存在: {account_file}"}

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        return {"ok": False, "error": f"视频文件不存在: {video_path}"}

    if _use_cdp():
        return await _run_upload_cdp(args, DouYinVideo,
                                     DOUYIN_PUBLISH_STRATEGY_IMMEDIATE)
    return await _run_upload_legacy(args, DouYinVideo, cookie_auth,
                                    DOUYIN_PUBLISH_STRATEGY_IMMEDIATE)


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
