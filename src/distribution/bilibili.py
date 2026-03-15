"""
B站视频上传模块 (基于 biliup)

使用 biliup 库通过 Cookie 登录上传视频到 B站。
Cookie 获取方式：浏览器登录 bilibili.com → DevTools → Application → Cookies
  复制 SESSDATA、bili_jct、DedeUserID、DedeUserID__ckMd5 填入 config.yaml
"""

import json
import logging
import os
import pickle
import tempfile
from pathlib import Path
from typing import Optional

from biliup.plugins.bili_webup import BiliBili, Data

logger = logging.getLogger(__name__)


def _load_cookies_from_config() -> Optional[dict]:
    """从 config.yaml 的 bilibili_cookies 字段读取 cookie。"""
    try:
        from src.config import _config
    except ImportError:
        try:
            from config import _config
        except ImportError:
            return None

    cookies = _config.get("bilibili_cookies")
    if not cookies or not isinstance(cookies, dict):
        return None

    sessdata = cookies.get("sessdata", "")
    bili_jct = cookies.get("bili_jct", "")
    dedeuserid = cookies.get("dedeuserid", "")
    dedeuserid_ckmd5 = cookies.get("dedeuserid_ckmd5", "")

    if not sessdata or not bili_jct:
        logger.warning("bilibili_cookies 中缺少 sessdata 或 bili_jct")
        return None

    return {
        "SESSDATA": str(sessdata),
        "bili_jct": str(bili_jct),
        "DedeUserID": str(dedeuserid),
        "DedeUserID__ckMd5": str(dedeuserid_ckmd5),
    }


def _load_cookies_from_pkl(pkl_path: str) -> Optional[dict]:
    """从 pkl 文件读取 cookie。

    支持多种 pkl 格式：
    - dict: {"SESSDATA": ..., "bili_jct": ..., ...}
    - dict: {"cookie_info": {"cookies": [...]}}  (biliup 格式)
    - requests CookieJar 对象
    """
    if not os.path.exists(pkl_path):
        return None

    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        logger.error(f"读取 pkl 文件失败: {e}")
        return None

    # 情况1: 直接是 cookie dict
    if isinstance(data, dict):
        if "SESSDATA" in data or "sessdata" in data:
            return {
                "SESSDATA": str(data.get("SESSDATA", data.get("sessdata", ""))),
                "bili_jct": str(data.get("bili_jct", "")),
                "DedeUserID": str(data.get("DedeUserID", data.get("dedeuserid", ""))),
                "DedeUserID__ckMd5": str(data.get("DedeUserID__ckMd5", data.get("dedeuserid_ckmd5", ""))),
            }
        # 情况2: biliup cookie_info 格式
        cookie_info = data.get("cookie_info", {})
        if isinstance(cookie_info, dict) and "cookies" in cookie_info:
            cookies_list = cookie_info["cookies"]
            result = {}
            for c in cookies_list:
                if isinstance(c, dict):
                    result[c["name"]] = c["value"]
            if "SESSDATA" in result:
                return result

    # 情况3: requests CookieJar
    try:
        cookie_dict = {c.name: c.value for c in data}
        if "SESSDATA" in cookie_dict:
            return cookie_dict
    except (TypeError, AttributeError):
        pass

    logger.warning(f"无法解析 pkl 文件中的 cookie 格式: {type(data)}")
    return None


def _resolve_cookies() -> Optional[dict]:
    """按优先级查找可用的 cookie。

    优先级：config.yaml > pkl 文件
    """
    # 1. 从 config.yaml 读取
    cookies = _load_cookies_from_config()
    if cookies:
        logger.info("从 config.yaml 读取到 bilibili cookies")
        return cookies

    # 2. 从 pkl 文件读取
    try:
        from src.config import BILIBILI_COOKIES_FILE
    except ImportError:
        try:
            from config import BILIBILI_COOKIES_FILE
        except ImportError:
            BILIBILI_COOKIES_FILE = "bilibili_cookies.pkl"

    if os.path.exists(BILIBILI_COOKIES_FILE):
        cookies = _load_cookies_from_pkl(BILIBILI_COOKIES_FILE)
        if cookies:
            logger.info(f"从 {BILIBILI_COOKIES_FILE} 读取到 bilibili cookies")
            return cookies

    logger.error(
        "未找到 bilibili cookies。请在 config.yaml 中配置 bilibili_cookies，"
        "或提供 bilibili_cookies.pkl 文件"
    )
    return None


def _create_cookie_json_file(cookies_dict: dict) -> str:
    """将 cookie dict 转为 biliup 所需的 JSON 文件格式，返回临时文件路径。"""
    cookie_data = {
        "cookie_info": {
            "cookies": [
                {"name": k, "value": v} for k, v in cookies_dict.items()
            ]
        },
        "token_info": {
            "access_token": "",
            "refresh_token": "",
        },
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="bili_cookie_"
    )
    json.dump(cookie_data, tmp, ensure_ascii=False)
    tmp.close()
    return tmp.name


def _login_with_cookies(bili: BiliBili, cookies_dict: dict) -> bool:
    """使用 cookie dict 直接登录 biliup 实例。"""
    import requests.utils

    try:
        requests.utils.add_dict_to_cookiejar(
            bili._BiliBili__session.cookies, cookies_dict
        )
        bili._BiliBili__bili_jct = cookies_dict.get("bili_jct", "")
        logger.info("Cookie 注入成功")
        return True
    except Exception as e:
        logger.error(f"Cookie 注入失败: {e}")
        return False


def upload(
    video_path: str,
    title: str,
    tags: str,
    desc: str = "",
    cover_path: Optional[str] = None,
    tid: int = 188,
    access_token: Optional[str] = None,
) -> Optional[str]:
    """上传视频到 B站。

    Args:
        video_path: 视频文件路径
        title: 视频标题（限80字）
        tags: 视频标签（逗号分隔）
        desc: 视频描述
        cover_path: 封面图路径
        tid: 视频分区ID（默认 188=科学科普）
        access_token: 未使用，保留兼容签名

    Returns:
        BV号字符串，失败返回 None
    """
    if not os.path.exists(video_path):
        logger.error(f"视频文件不存在: {video_path}")
        return None

    # 解析 cookies
    cookies = _resolve_cookies()
    if not cookies:
        return None

    # 构造 Data 对象
    video = Data()
    video.title = title[:80]
    video.desc = desc[:250] if desc else ""
    video.tid = tid
    video.copyright = 1  # 自制
    if isinstance(tags, list):
        video.set_tag(tags)
    else:
        video.set_tag([t.strip() for t in tags.split(",") if t.strip()])

    cookie_json_path = None
    try:
        with BiliBili(video) as bili:
            # 登录
            if not _login_with_cookies(bili, cookies):
                return None

            # 上传视频文件
            logger.info(f"开始上传视频: {video_path}")
            video_part = bili.upload_file(
                filepath=video_path,
                lines="AUTO",
                tasks=3,
            )
            video.append(video_part)
            logger.info(f"视频文件上传完成: {video_part.get('title', '')}")

            # 上传封面
            if cover_path and os.path.exists(cover_path):
                logger.info(f"上传封面: {cover_path}")
                cover_url = bili.cover_up(cover_path)
                if cover_url:
                    video.cover = cover_url.replace("http:", "")
                    logger.info("封面上传完成")

            # 提交稿件
            logger.info("提交稿件...")
            ret = bili.submit(submit_api="web")
            logger.info(f"提交结果: {ret}")

            if isinstance(ret, dict):
                if ret.get("code") == 0:
                    data = ret.get("data", {})
                    bvid = data.get("bvid", "")
                    aid = data.get("aid", "")
                    logger.info(f"上传成功! BV号: {bvid}, AV号: {aid}")
                    return bvid or str(aid)
                else:
                    logger.error(f"提交失败: code={ret.get('code')}, message={ret.get('message', '')}")
                    return None
            else:
                logger.warning(f"提交返回非预期格式: {ret}")
                return str(ret) if ret else None

    except Exception as e:
        logger.exception(f"B站上传异常: {e}")
        return None
    finally:
        if cookie_json_path and os.path.exists(cookie_json_path):
            os.unlink(cookie_json_path)


if __name__ == "__main__":
    import argparse
    import datetime

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="B站视频上传 (biliup)")
    parser.add_argument("--test-upload", action="store_true", help="测试上传")
    parser.add_argument("--video", default="./output/daily_summary.mp4", help="视频路径")
    parser.add_argument("--cover", default="./output/daily_summary.png", help="封面路径")
    parser.add_argument("--title", default=None, help="视频标题")
    parser.add_argument("--tags", default="论文解读,AI,arXiv", help="标签(逗号分隔)")
    parser.add_argument("--tid", type=int, default=188, help="分区ID")
    args = parser.parse_args()

    if args.test_upload:
        if not os.path.exists(args.video):
            print(f"视频文件不存在: {args.video}")
            exit(1)

        title = args.title or f"测试上传-{datetime.datetime.now().strftime('%Y%m%d_%H%M')}"
        cover = args.cover if os.path.exists(args.cover) else None

        result = upload(
            video_path=args.video,
            title=title,
            tags=args.tags,
            desc="测试上传",
            cover_path=cover,
            tid=args.tid,
        )
        if result:
            print(f"\n上传成功! BV号: {result}")
        else:
            print("\n上传失败")
    else:
        parser.print_help()
