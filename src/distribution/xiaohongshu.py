# ==================== 小红书 MCP 上传方式 ====================
"""
使用 MCP 协议上传到小红书
需要先启动 MCP 服务:
    docker run -p 18060:18060 xpzouying/xiaohongshu-mcp
    # 或从源码: git clone && cd xiaohongshu-mcp && go run .
"""

import logging
import os
import subprocess
import time
import shutil
from typing import Optional, List

logger = logging.getLogger(__name__)

# MCP 服务地址
MCP_SERVER_URL = "http://localhost:18060/mcp"

# 服务进程缓存
_mcp_process: Optional[subprocess.Popen] = None


def _is_service_reachable(timeout: int = 3) -> bool:
    """检查 MCP HTTP 服务是否可达。"""
    try:
        import requests

        response = requests.get(MCP_SERVER_URL, timeout=timeout)
        # 一些服务即使返回 404/405 也说明端口可达
        return response.status_code < 500
    except Exception:
        return False


def _candidate_local_mcp_paths() -> List[str]:
    """返回可能存在 xiaohongshu-mcp 源码的路径列表。"""
    module_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.abspath(os.path.join(module_dir, "../../../../xiaohongshu-mcp")),
        os.path.abspath(os.path.join(module_dir, "../../xiaohongshu-mcp")),
        os.path.abspath(os.path.join(module_dir, "../../../xiaohongshu-mcp")),
        os.path.expanduser("~/xiaohongshu-mcp"),
    ]
    # 去重且保持顺序
    seen = set()
    deduped = []
    for path in candidates:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


def _start_service_via_docker() -> bool:
    """尝试使用 Docker 启动服务。"""
    global _mcp_process
    if not shutil.which("docker"):
        return False

    try:
        docker_proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        )
        if docker_proc.returncode != 0:
            logger.warning("检测到 docker 命令不可用或无权限，跳过 Docker 启动。")
            return False

        logger.info("使用 Docker 启动 MCP 服务...")
        _mcp_process = subprocess.Popen(
            ["docker", "run", "--rm", "-p", "18060:18060", "xpzouying/xiaohongshu-mcp"],
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

    for mcp_path in _candidate_local_mcp_paths():
        if os.path.exists(mcp_path):
            try:
                logger.info("使用源码启动 MCP 服务: %s", mcp_path)
                _mcp_process = subprocess.Popen(
                    ["go", "run", "."],
                    cwd=mcp_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                return True
            except Exception as exc:
                logger.warning("源码启动失败 (%s): %s", mcp_path, exc)

    return False


def _ensure_mcp_service():
    """确保 MCP 服务已启动"""
    global _mcp_process

    # 检查服务是否已运行
    if _is_service_reachable(timeout=5):
        logger.info("MCP 服务已运行")
        return True

    # 服务未运行，尝试启动
    logger.warning("MCP 服务未运行，正在启动...")

    started = _start_service_via_docker()
    if not started:
        started = _start_service_via_local_source()
    if not started:
        logger.error("自动启动失败：Docker 不可用且未找到可运行的本地 xiaohongshu-mcp 源码。")
        logger.info("请手动启动: docker run -p 18060:18060 xpzouying/xiaohongshu-mcp")
        return False

    # 等待服务启动
    for i in range(30):
        time.sleep(2)
        if _is_service_reachable(timeout=5):
            logger.info("MCP 服务启动成功!")
            return True
        logger.info(f"等待服务启动... ({i+1}/30)")

    logger.error("MCP 服务启动超时")
    return False


class XiaohongshuMCPUploader:
    """小红书 MCP 上传器 (HTTP 方式)"""

    def __init__(self):
        self.session = None

    def connect(self):
        """确保已连接到 MCP 服务"""
        _ensure_mcp_service()
        return self

    def _request(self, method: str, params: dict = None) -> Optional[dict]:
        """向 MCP 服务器发送请求"""
        import requests

        if not _ensure_mcp_service():
            return None

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {}
        }

        try:
            response = requests.post(MCP_SERVER_URL, json=payload, timeout=60)
            result = response.json()

            if "error" in result:
                logger.error(f"MCP 错误: {result['error']}")
                return None

            return result.get("result")
        except requests.exceptions.ConnectionError:
            logger.error(f"无法连接到 MCP 服务: {MCP_SERVER_URL}")
            return None
        except Exception as e:
            logger.error(f"请求失败: {e}")
            return None

    def check_login_status(self) -> bool:
        """检查登录状态"""
        result = self._request("check_login_status")
        if result:
            logger.info(f"登录状态: {result}")
            return result.get("is_logged_in", False)
        return False

    def publish_note(
        self,
        title: str,
        content: str,
        images: List[str],
        visible_level: str = "public",
        is_original: bool = True
    ) -> Optional[dict]:
        """发布图文笔记"""
        # 标题校验
        if len(title) > 20:
            logger.warning(f"标题超过20字，将截取前20字: {title[:20]}")
            title = title[:20]

        # 内容校验
        if len(content) > 1000:
            logger.warning(f"内容超过1000字，将截取")
            content = content[:1000]

        params = {
            "title": title,
            "content": content,
            "images": images,
            "visible_level": visible_level,
            "is_original": is_original
        }

        logger.info(f"发布图文笔记: {title}")
        return self._request("publish_note", params)

    def publish_video(
        self,
        title: str,
        content: str,
        video_path: str,
        cover_path: str = None,
        visible_level: str = "public",
        is_original: bool = True
    ) -> Optional[dict]:
        """发布视频"""
        if len(title) > 20:
            title = title[:20]

        params = {
            "title": title,
            "content": content,
            "video_path": video_path,
            "visible_level": visible_level,
            "is_original": is_original
        }

        if cover_path:
            params["cover_path"] = cover_path

        logger.info(f"发布视频笔记: {title}")
        return self._request("publish_video", params)

    def search_notes(self, keyword: str, page: int = 1) -> Optional[dict]:
        """搜索内容"""
        return self._request("search", {"keyword": keyword, "page": page})

    def get_user_profile(self) -> Optional[dict]:
        """获取用户信息"""
        return self._request("get_user_profile")


class XiaohongshuMCPStdio:
    """小红书 MCP 上传器 (stdio 方式 - 如果支持)"""

    def __init__(self):
        self.session = None

    async def connect(self):
        """连接到 MCP 服务器"""
        try:
            from mcp.client.stdio import stdio_client
            from mcp import ClientSession

            # 尝试找到 xiaohongshu-mcp
            import shutil
            mcp_path = shutil.which("xiaohongshu-mcp")

            if mcp_path:
                from mcp import StdioServerParameters
                server_params = StdioServerParameters(command=mcp_path, args=[])

                async with stdio_client(server_params) as (stdio, write):
                    self.session = ClientSession(stdio, write)
                    async with self.session as session:
                        await session.initialize()
                        logger.info("已连接到小红书 MCP 服务器")
                        return True
            return False
        except Exception as e:
            logger.error(f"连接失败: {e}")
            return False

    async def call_tool(self, name: str, params: dict = None):
        """调用工具"""
        if self.session:
            return await self.session.call_tool(name, params or {})
        return None


def upload_to_xiaohongshu(
    video_path: str = None,
    cover_path: str = None,
    title: str = "",
    content: str = "",
    images: List[str] = None,
    is_video: bool = False
) -> Optional[dict]:
    """
    上传内容到小红书

    Args:
        video_path: 视频文件路径
        cover_path: 封面图片路径
        title: 标题
        content: 正文内容
        images: 图片列表（图文模式）
        is_video: 是否为视频模式

    Returns:
        发布结果 或 None
    """
    uploader = XiaohongshuMCPUploader()

    # 检查登录状态
    if not uploader.check_login_status():
        logger.error("未登录小红书")
        return None

    if is_video and video_path:
        # 视频模式
        return uploader.publish_video(
            title=title,
            content=content,
            video_path=video_path,
            cover_path=cover_path
        )
    elif images:
        # 图文模式
        return uploader.publish_note(
            title=title,
            content=content,
            images=images
        )
    else:
        logger.error("未指定视频或图片")
        return None


def publish_note(title, content, images, visible_level="public", is_original=True):
    """发布图文笔记"""
    return upload_to_xiaohongshu(
        title=title,
        content=content,
        images=images,
        is_video=False
    )


def publish_video(title, content, video_path, cover_path=None):
    """发布视频"""
    return upload_to_xiaohongshu(
        title=title,
        content=content,
        video_path=video_path,
        cover_path=cover_path,
        is_video=True
    )


def check_login_status() -> bool:
    """模块级登录状态检查接口"""
    uploader = XiaohongshuMCPUploader()
    return uploader.check_login_status()


if __name__ == "__main__":
    import datetime

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

    logger.info("=" * 50)
    logger.info("小红书 MCP 上传测试")
    logger.info("=" * 50)

    # 检查登录状态
    print("\n检查登录状态...")
    uploader = XiaohongshuMCPUploader()
    if not uploader.check_login_status():
        logger.info("请扫描浏览器中出现的二维码完成登录")
        logger.info("服务运行在: http://localhost:18060/mcp")
    else:
        # 测试发布图文
        logger.info("\n测试发布图文笔记...")
        result = uploader.publish_note(
            title=f"MCP测试笔记-{datetime.datetime.now().strftime('%H:%M')}",
            content="这是一个通过 MCP 自动发布的小红书笔记测试。",
            images=["/home/jdh/Projects/VlogCutter/JushenRenji/output/daily_summary.png"]
        )

        if result:
            logger.info(f"发布成功! Note ID: {result.get('note_id')}")
        else:
            logger.error("发布失败")
