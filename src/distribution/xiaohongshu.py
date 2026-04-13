# ==================== 小红书 MCP 上传方式 ====================
"""
使用 MCP 协议上传到小红书（图文 / 视频）。

MCP 服务启动方式（推荐 docker-compose）：

  mkdir -p ./data/xhs ./images/xhs
  docker run -d --name xhs-mcp \\
    -p 18060:18060 \\
    -v "$(pwd)/data/xhs:/app/data" \\
    -v "$(pwd)/images/xhs:/app/images" \\
    -e COOKIES_PATH=/app/data/cookies.json \\
    --restart unless-stopped \\
    xpzouying/xiaohongshu-mcp

首次使用需要扫码登录：
  python -m src.distribution.xiaohongshu --login
"""

import base64
import json
import logging
import os
import shutil
import subprocess
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

# MCP 服务地址
MCP_SERVER_URL = "http://localhost:18060/mcp"

# 项目根目录（从本文件向上4级）
_FILE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_FILE_DIR, "../.."))

# Docker 挂载目录（放在项目 tmp 目录下）
MCP_DATA_DIR = os.path.join(_PROJECT_ROOT, "tmp", "xhs", "data")
MCP_IMAGES_DIR = os.path.join(_PROJECT_ROOT, "tmp", "xhs", "images")

# QR 码保存路径
QR_CODE_PATH = os.path.join(_PROJECT_ROOT, "tmp", "xhs", "login_qrcode.png")

# 服务进程缓存（非 Docker 方式）
_mcp_process: Optional[subprocess.Popen] = None


# ---------------------------------------------------------------------------
# 服务可达性 & 启动
# ---------------------------------------------------------------------------

def _is_service_reachable(timeout: int = 3) -> bool:
    """检查 MCP HTTP 服务是否可达（通过 initialize 探测）。"""
    try:
        import requests
        payload = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "paperagent", "version": "1.0"}
        }}
        resp = requests.post(MCP_SERVER_URL, json=payload, timeout=timeout)
        return resp.status_code < 500
    except Exception:
        return False


def _ensure_data_dirs():
    """确保 Docker 挂载目录存在。"""
    os.makedirs(MCP_DATA_DIR, exist_ok=True)
    os.makedirs(MCP_IMAGES_DIR, exist_ok=True)


def _copy_to_docker_mount(src_path: str, subdir: str = "images") -> str:
    """将宿主机文件复制到 Docker 挂载目录，返回容器内路径。

    使用安全的 ASCII 文件名避免 Docker 容器内的编码问题。

    Args:
        src_path: 宿主机上的文件绝对路径
        subdir: 挂载子目录 ("images" 或 "data")

    Returns:
        容器内路径，如 /app/images/xhs_upload_0a1b.png
    """
    import hashlib

    _ensure_data_dirs()
    mount_dir = MCP_IMAGES_DIR if subdir == "images" else MCP_DATA_DIR
    container_prefix = "/app/images" if subdir == "images" else "/app/data"

    # 生成安全的 ASCII 文件名：hash 前缀 + 原始扩展名
    _, ext = os.path.splitext(src_path)
    short_hash = hashlib.md5(src_path.encode()).hexdigest()[:8]
    safe_name = f"xhs_upload_{short_hash}{ext}"
    dst_path = os.path.join(mount_dir, safe_name)

    shutil.copy2(src_path, dst_path)
    logger.info("已复制文件到 Docker 挂载目录: %s -> %s", os.path.basename(src_path), safe_name)

    return f"{container_prefix}/{safe_name}"


def _start_service_via_docker() -> bool:
    """使用 Docker 启动 xiaohongshu-mcp 服务。"""
    global _mcp_process
    if not shutil.which("docker"):
        logger.warning("未找到 docker 命令，跳过 Docker 启动。")
        return False

    # 检查 docker 守护进程是否可用
    check = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        logger.warning(
            "Docker 守护进程不可访问（可能需要 sudo 或添加到 docker 组）。"
            "请手动运行：sudo usermod -aG docker $USER 后重启会话。"
        )
        return False

    # 检查是否已有同名容器在运行
    ps_out = check.stdout.strip().splitlines()
    if "xhs-mcp" in ps_out:
        logger.info("Docker 容器 xhs-mcp 已在运行")
        return True

    _ensure_data_dirs()

    logger.info("使用 Docker 启动 xiaohongshu-mcp 服务...")
    try:
        _mcp_process = subprocess.Popen(
            [
                "docker", "run", "--rm",
                "--name", "xhs-mcp",
                "-p", "18060:18060",
                "-v", f"{MCP_DATA_DIR}:/app/data",
                "-v", f"{MCP_IMAGES_DIR}:/app/images",
                "-e", "COOKIES_PATH=/app/data/cookies.json",
                "xpzouying/xiaohongshu-mcp",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True
    except Exception as exc:
        logger.warning("Docker 启动失败: %s", exc)
        return False


def _start_service_via_local_source() -> bool:
    """尝试通过本地源码 go run 启动服务。"""
    global _mcp_process
    if not shutil.which("go"):
        return False

    candidates = [
        os.path.abspath(os.path.join(_PROJECT_ROOT, "../xiaohongshu-mcp")),
        os.path.abspath(os.path.join(_PROJECT_ROOT, "../../xiaohongshu-mcp")),
        os.path.expanduser("~/xiaohongshu-mcp"),
    ]
    for mcp_path in dict.fromkeys(candidates):  # 去重
        if os.path.exists(mcp_path):
            try:
                logger.info("使用本地源码启动 MCP 服务: %s", mcp_path)
                _ensure_data_dirs()
                env = os.environ.copy()
                env["COOKIES_PATH"] = os.path.join(MCP_DATA_DIR, "cookies.json")
                _mcp_process = subprocess.Popen(
                    ["go", "run", "."],
                    cwd=mcp_path,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                return True
            except Exception as exc:
                logger.warning("本地源码启动失败 (%s): %s", mcp_path, exc)
    return False


def ensure_mcp_service() -> bool:
    """确保 MCP 服务已启动，返回是否成功。"""
    if _is_service_reachable(timeout=5):
        logger.info("MCP 服务已运行")
        return True

    logger.warning("MCP 服务未运行，正在启动...")

    started = _start_service_via_docker() or _start_service_via_local_source()
    if not started:
        logger.error(
            "自动启动失败。请手动运行:\n"
            "  mkdir -p tmp/xhs/data tmp/xhs/images\n"
            "  docker run -d --name xhs-mcp -p 18060:18060 \\\n"
            "    -v \"$(pwd)/tmp/xhs/data:/app/data\" \\\n"
            "    -v \"$(pwd)/tmp/xhs/images:/app/images\" \\\n"
            "    -e COOKIES_PATH=/app/data/cookies.json \\\n"
            "    xpzouying/xiaohongshu-mcp"
        )
        return False

    for i in range(30):
        time.sleep(2)
        if _is_service_reachable(timeout=5):
            logger.info("MCP 服务启动成功!")
            return True
        logger.info("等待服务启动... (%d/30)", i + 1)

    logger.error("MCP 服务启动超时")
    return False


# ---------------------------------------------------------------------------
# MCP JSON-RPC 底层调用
# ---------------------------------------------------------------------------

# 模块级 MCP session 缓存（session_id + requests.Session）
_mcp_session: Optional["requests.Session"] = None
_mcp_session_id: Optional[str] = None
_mcp_call_id: int = 0


def _ensure_mcp_session() -> bool:
    """初始化 MCP session（initialize + notifications/initialized），缓存复用。"""
    import requests as _req

    global _mcp_session, _mcp_session_id, _mcp_call_id

    if _mcp_session is not None and _mcp_session_id is not None:
        return True

    _mcp_session = _req.Session()
    headers = {"Content-Type": "application/json"}

    try:
        resp = _mcp_session.post(
            MCP_SERVER_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "paperagent", "version": "1.0"},
                },
            },
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if not sid:
            logger.error("MCP initialize 返回中缺少 Mcp-Session-Id")
            _mcp_session = None
            return False
        _mcp_session_id = sid
        _mcp_call_id = 1
        logger.info("MCP session 已建立: %s", sid)

        # 发送 initialized 通知
        _mcp_session.post(
            MCP_SERVER_URL,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**headers, "Mcp-Session-Id": sid},
            timeout=10,
        )
        return True
    except Exception as exc:
        logger.error("MCP session 初始化失败: %s", exc)
        _mcp_session = None
        _mcp_session_id = None
        return False


def _call_tool(tool_name: str, arguments: dict = None, timeout: int = 120) -> Optional[dict]:
    """
    向 MCP 服务器发起 tools/call 请求，返回解析后的结果字典或 None。

    自动管理 MCP session（initialize → Mcp-Session-Id）。

    Args:
        tool_name: MCP 工具名称
        arguments: 工具参数
        timeout: HTTP 请求超时（秒），默认 120 秒
    """
    import requests as _req

    global _mcp_session, _mcp_session_id, _mcp_call_id

    if not ensure_mcp_service():
        return None

    if not _ensure_mcp_session():
        return None

    _mcp_call_id += 1
    payload = {
        "jsonrpc": "2.0",
        "id": _mcp_call_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments or {},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Mcp-Session-Id": _mcp_session_id,
    }

    try:
        resp = _mcp_session.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except _req.exceptions.ConnectionError:
        logger.error("无法连接到 MCP 服务: %s", MCP_SERVER_URL)
        # 重置 session 以便下次重建
        _mcp_session = None
        _mcp_session_id = None
        return None
    except Exception as exc:
        logger.error("HTTP 请求失败: %s", exc)
        return None

    if "error" in body:
        err = body["error"]
        logger.error("MCP 返回错误: %s", err)
        # 如果 session 失效，重置并重试一次
        if "session" in str(err).lower() or "initialization" in str(err).lower():
            logger.info("MCP session 可能已失效，尝试重建...")
            _mcp_session = None
            _mcp_session_id = None
            if _ensure_mcp_session():
                _mcp_call_id += 1
                payload["id"] = _mcp_call_id
                headers["Mcp-Session-Id"] = _mcp_session_id
                try:
                    resp = _mcp_session.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=60)
                    body = resp.json()
                    if "error" not in body:
                        result = body.get("result", {})
                        if isinstance(result, dict) and result.get("isError"):
                            content_list = result.get("content", [])
                            err_text = content_list[0].get("text", "") if content_list else ""
                            logger.error("工具执行错误: %s", err_text)
                            return None
                        return result
                except Exception:
                    pass
        return None

    result = body.get("result", {})

    # MCP 规范返回 {content: [...], isError: bool}
    if isinstance(result, dict) and result.get("isError"):
        content_list = result.get("content", [])
        err_text = content_list[0].get("text", "") if content_list else ""
        logger.error("工具执行错误: %s", err_text)
        return None

    return result


def _extract_text(result: dict) -> Optional[str]:
    """从 tools/call 结果中提取第一个 text 内容。"""
    if not isinstance(result, dict):
        return None
    for item in result.get("content", []):
        if item.get("type") == "text":
            return item.get("text")
    return None


def _extract_image_bytes(result: dict) -> Optional[bytes]:
    """从 tools/call 结果中提取第一个 image 的原始字节。"""
    if not isinstance(result, dict):
        return None
    for item in result.get("content", []):
        if item.get("type") == "image":
            data = item.get("data", "")
            try:
                return base64.b64decode(data)
            except Exception as exc:
                logger.warning("base64 解码失败: %s", exc)
    return None


# ---------------------------------------------------------------------------
# 登录管理
# ---------------------------------------------------------------------------

def get_login_qrcode() -> Optional[str]:
    """
    获取小红书登录二维码，保存到本地并返回文件路径。

    二维码保存路径：tmp/xhs/login_qrcode.png
    """
    result = _call_tool("get_login_qrcode")
    if result is None:
        return None

    image_bytes = _extract_image_bytes(result)
    if image_bytes:
        os.makedirs(os.path.dirname(QR_CODE_PATH), exist_ok=True)
        with open(QR_CODE_PATH, "wb") as f:
            f.write(image_bytes)
        logger.info("二维码已保存: %s", QR_CODE_PATH)
        return QR_CODE_PATH

    # 有些版本返回 URL 而非图片
    text = _extract_text(result)
    if text:
        logger.info("登录二维码信息: %s", text)
        return text

    logger.error("无法获取登录二维码")
    return None


def check_login_status() -> bool:
    """检查小红书登录状态，返回 True 表示已登录。"""
    result = _call_tool("check_login_status")
    if result is None:
        return False

    text = _extract_text(result)
    if text:
        try:
            data = json.loads(text)
            logged_in = data.get("is_logged_in", data.get("logged_in", False))
            logger.info("登录状态: %s", "已登录" if logged_in else "未登录")
            return bool(logged_in)
        except json.JSONDecodeError:
            # 有些实现直接返回布尔字符串或中文状态文本
            text_lower = text.strip().lower()
            logged_in = (
                text_lower in ("true", "1", "yes", "logged_in")
                or "已登录" in text
                or "logged in" in text_lower
            )
            return logged_in

    return False


def login_with_qrcode() -> bool:
    """
    引导用户完成扫码登录。

    步骤：
    1. 获取二维码并保存
    2. 打印文件路径 / 提示用户扫码
    3. 轮询登录状态，最长等待 3 分钟

    Returns:
        True 登录成功，False 超时或失败
    """
    logger.info("=" * 60)
    logger.info("小红书扫码登录")
    logger.info("=" * 60)

    qr_path = get_login_qrcode()
    if not qr_path:
        logger.error("获取二维码失败，请检查 MCP 服务是否正常运行")
        return False

    # 如果是本地文件，给出明确路径
    if os.path.exists(str(qr_path)):
        print(f"\n请使用小红书 App 扫描以下二维码完成登录：")
        print(f"  二维码图片: {qr_path}\n")
        # 尝试用系统默认程序打开图片（非阻塞）
        try:
            import subprocess as _sp
            _sp.Popen(["xdg-open", qr_path], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass
    else:
        print(f"\n请访问以下链接完成登录（扫码或点击）：\n  {qr_path}\n")

    # 轮询登录状态（最多 180 秒）
    for i in range(36):
        time.sleep(5)
        if check_login_status():
            logger.info("扫码登录成功!")
            return True
        logger.info("等待扫码... (%d/36)", i + 1)

    logger.error("登录超时，请重试")
    return False


# ---------------------------------------------------------------------------
# 上传器
# ---------------------------------------------------------------------------



def _prepend_cover_to_video(video_path: str, cover_path: str, duration: float = 1.5) -> str:
    """将封面图作为首帧插入视频开头，小红书会自动截取第一帧作为封面。"""
    if not cover_path or not os.path.exists(cover_path):
        return video_path

    base, ext = video_path.rsplit(".", 1)
    output_path = base + "_with_cover." + ext
    try:
        from moviepy import VideoFileClip, ImageClip, concatenate_videoclips
        from PIL import Image
        import numpy as np

        video = VideoFileClip(video_path)
        w, h = video.size

        # 封面图缩放到视频尺寸
        img = Image.open(cover_path).convert("RGB")
        img_w, img_h = img.size
        scale = min(w / img_w, h / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        bg = Image.new("RGB", (w, h), (0, 0, 0))
        bg.paste(img, ((w - new_w) // 2, (h - new_h) // 2))

        cover_clip = ImageClip(np.array(bg), duration=duration)
        final = concatenate_videoclips([cover_clip, video])
        final.write_videofile(output_path, fps=video.fps or 30,
                             codec="libx264", audio_codec="aac",
                             preset="fast")
        video.close()
        final.close()

        if os.path.exists(output_path):
            logger.info("封面已嵌入视频开头: %s", output_path)
            return output_path
        return video_path
    except Exception as exc:
        logger.warning("封面嵌入异常: %s", exc)
        return video_path

class XiaohongshuMCPUploader:
    """小红书 MCP 上传器（HTTP JSON-RPC 方式）。"""

    def connect(self) -> "XiaohongshuMCPUploader":
        """确保 MCP 服务可达并已登录；如未登录则引导扫码。"""
        if not ensure_mcp_service():
            raise RuntimeError("MCP 服务未启动，无法上传")

        if not check_login_status():
            logged_in = login_with_qrcode()
            if not logged_in:
                raise RuntimeError("未登录小红书，无法上传")
        return self

    def publish_note(
        self,
        title: str,
        content: str,
        images: List[str],
        visible_level: str = "public",
        is_original: bool = True,
        tags: Optional[List[str]] = None,
    ) -> Optional[dict]:
        """
        发布图文笔记（publish_content 工具）。

        Args:
            title: 标题（最多 20 字）
            content: 正文（最多 1000 字）
            images: 图片绝对路径列表（1~9 张）
            visible_level: 可见范围 public / private
            is_original: 是否声明原创
            tags: 话题标签列表（可选）
        """
        if len(title) > 20:
            logger.warning("标题超过20字，截取前20字")
            title = title[:20]
        if len(content) > 1000:
            logger.warning("内容超过1000字，截取")
            content = content[:1000]

        # 将图片复制到 Docker 挂载目录，使用容器内路径
        container_images = []
        for img_path in images:
            if os.path.exists(img_path):
                container_images.append(_copy_to_docker_mount(img_path, "images"))
            else:
                logger.warning("图片文件不存在，跳过: %s", img_path)

        if not container_images:
            logger.error("没有有效的图片文件")
            return None

        # MCP 工具期望中文可见范围
        _visibility_map = {"public": "公开可见", "private": "仅自己可见", "friends": "仅互关好友可见"}
        arguments: dict = {
            "title": title,
            "content": content,
            "images": container_images,
            "visibility": _visibility_map.get(visible_level, visible_level),
            "is_original": is_original,
        }
        if tags:
            arguments["tags"] = tags

        logger.info("发布图文笔记: %s（%d 张图）", title, len(container_images))
        result = _call_tool("publish_content", arguments, timeout=300)
        if result is None:
            return None

        text = _extract_text(result)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
        return result

    def publish_video(
        self,
        title: str,
        content: str,
        video_path: str,
        cover_path: Optional[str] = None,
        visible_level: str = "public",
        is_original: bool = True,
        tags: Optional[List[str]] = None,
    ) -> Optional[dict]:
        """发布视频笔记（publish_with_video 工具）。"""
        if len(title) > 20:
            title = title[:20]

        # 将视频复制到 Docker 挂载目录，使用容器内路径
        container_video = _copy_to_docker_mount(video_path, "data")

        arguments: dict = {
            "title": title,
            "content": content,
            "video": container_video,
        }
        # MCP publish_with_video 不支持 cover 参数，
        # 通过 ffmpeg 将封面嵌入视频开头，小红书会自动截取第一帧作为封面
        if cover_path and os.path.exists(cover_path):
            patched_video = _prepend_cover_to_video(video_path, cover_path, duration=1.0)
            if patched_video != video_path:
                container_video = _copy_to_docker_mount(patched_video, "data")
                arguments["video"] = container_video
                logger.info("已将封面嵌入视频开头用于小红书封面")
        # MCP 工具期望中文可见范围
        _visibility_map = {"public": "公开可见", "private": "仅自己可见", "friends": "仅互关好友可见"}
        if visible_level:
            arguments["visibility"] = _visibility_map.get(visible_level, visible_level)
        if tags:
            arguments["tags"] = tags

        logger.info("发布视频笔记: %s", title)
        result = _call_tool("publish_with_video", arguments, timeout=600)
        if result is None:
            return None

        text = _extract_text(result)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
        return result

    def get_user_profile(self) -> Optional[dict]:
        """获取当前登录用户信息。"""
        result = _call_tool("user_profile")
        if result is None:
            return None
        text = _extract_text(result)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
        return result


# ---------------------------------------------------------------------------
# 模块级便捷接口（与 orchestrator 兼容）
# ---------------------------------------------------------------------------

def upload_to_xiaohongshu(
    video_path: str = None,
    cover_path: str = None,
    title: str = "",
    content: str = "",
    images: List[str] = None,
    is_video: bool = False,
    tags: Optional[List[str]] = None,
) -> Optional[dict]:
    """
    上传内容到小红书。

    Args:
        video_path: 视频文件路径（视频模式）
        cover_path: 封面图片路径
        title: 标题
        content: 正文内容
        images: 图片列表（图文模式）
        is_video: 是否为视频模式
        tags: 话题标签（可选）

    Returns:
        发布结果字典 或 None（失败）
    """
    uploader = XiaohongshuMCPUploader()
    uploader.connect()  # 如未登录会自动引导扫码

    if is_video and video_path:
        return uploader.publish_video(
            title=title,
            content=content,
            video_path=video_path,
            cover_path=cover_path,
        )
    elif images:
        return uploader.publish_note(
            title=title,
            content=content,
            images=images,
            tags=tags,
        )
    else:
        logger.error("未指定视频或图片，无法上传")
        return None


def publish_note(
    title: str,
    content: str,
    images: List[str],
    visible_level: str = "public",
    is_original: bool = True,
    tags: Optional[List[str]] = None,
) -> Optional[dict]:
    """发布图文笔记（orchestrator 兼容接口）。"""
    return upload_to_xiaohongshu(
        title=title,
        content=content,
        images=images,
        is_video=False,
        tags=tags,
    )


def publish_video(
    title: str,
    content: str,
    video_path: str,
    cover_path: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Optional[dict]:
    """发布视频（orchestrator 兼容接口）。"""
    return upload_to_xiaohongshu(
        title=title,
        content=content,
        video_path=video_path,
        cover_path=cover_path,
        is_video=True,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# CLI 入口（手动测试 / 登录）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import datetime

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="小红书 MCP 上传工具")
    parser.add_argument("--login", action="store_true", help="引导扫码登录")
    parser.add_argument("--status", action="store_true", help="检查登录状态")
    parser.add_argument("--test-note", action="store_true", help="发布测试图文")
    args = parser.parse_args()

    if not ensure_mcp_service():
        print("\n[ERROR] MCP 服务未启动，请先运行 Docker：")
        print(
            "  mkdir -p tmp/xhs/data tmp/xhs/images\n"
            '  docker run -d --name xhs-mcp -p 18060:18060 \\\n'
            '    -v "$(pwd)/tmp/xhs/data:/app/data" \\\n'
            '    -v "$(pwd)/tmp/xhs/images:/app/images" \\\n'
            '    -e COOKIES_PATH=/app/data/cookies.json \\\n'
            '    xpzouying/xiaohongshu-mcp'
        )
        exit(1)

    if args.login:
        success = login_with_qrcode()
        print("登录成功!" if success else "登录失败")
    elif args.status:
        logged_in = check_login_status()
        print(f"登录状态: {'已登录' if logged_in else '未登录'}")
    elif args.test_note:
        test_image = os.path.join(_PROJECT_ROOT, "output", "daily_summary.png")
        if not os.path.exists(test_image):
            print(f"测试图片不存在: {test_image}")
            exit(1)
        result = publish_note(
            title=f"MCP测试-{datetime.datetime.now().strftime('%H:%M')}",
            content="这是一个通过 MCP 自动发布的小红书图文测试。",
            images=[test_image],
        )
        print(f"发布结果: {result}")
    else:
        parser.print_help()
