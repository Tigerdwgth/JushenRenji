# ==================== B站 MCP 上传方式 ====================
"""
使用 MCP 协议上传视频到B站
需要先安装 MCP Bilibili 服务:
    nvm use 18
    npm install -g @mcpcn/mcp-bilibili

注意：需要使用 Node.js 18+ 版本
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def _extract_payload_dict(raw: object) -> dict:
    """Normalize MCP JSON payload into a dict."""
    if not isinstance(raw, dict):
        return {}

    content = raw.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return first
    return raw


class BilibiliMCPUploader:
    """B站 MCP 上传器"""

    def __init__(self):
        self.process = None
        self.session = None
        self._stdio_context = None
        self._stdio_transport = None

    def _get_node_path(self) -> str:
        """获取 Node 18 路径"""
        return os.path.expanduser("~/.nvm/versions/node/v18.20.8/bin/node")

    def _get_mcp_path(self) -> str:
        """获取 MCP 服务器路径"""
        # 优先使用全局安装的 mcp-bilibili
        mcp_path = os.path.expanduser("~/.nvm/versions/node/v18.20.8/lib/node_modules/@mcpcn/mcp-bilibili/dist/index.js")
        if os.path.exists(mcp_path):
            return mcp_path

        # 如果找不到，使用 npx
        return None

    async def __aenter__(self):
        """支持 with 语句"""
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession, StdioServerParameters

        node_path = self._get_node_path()
        mcp_js_path = self._get_mcp_path()

        if mcp_js_path:
            command = node_path
            args = [mcp_js_path]
        else:
            command = "npx"
            args = ["-y", "@mcpcn/mcp-bilibili"]

        server_params = StdioServerParameters(command=command, args=args)

        logger.info("启动 MCP 服务器...")

        # 使用 async with 上下文管理器
        self._stdio_context = stdio_client(server_params)
        self._stdio_transport = await self._stdio_context.__aenter__()
        self.session = ClientSession(self._stdio_transport[0], self._stdio_transport[1])
        # ClientSession 的 __aenter__ 会自动调用 initialize()
        await self.session.__aenter__()
        logger.info("已连接到 B站 MCP 服务器")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """支持 with 语句退出"""
        await self.close()

    async def close(self):
        """关闭连接"""
        # 清理 session
        if self.session:
            try:
                await self.session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"关闭 session 时出错: {e}")
            self.session = None

        # 清理 stdio context
        if self._stdio_context:
            try:
                await self._stdio_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"关闭 stdio context 时出错: {e}")
            self._stdio_context = None
            self._stdio_transport = None

        logger.info("连接已关闭")

    async def list_tools(self) -> Optional[list]:
        """列出所有可用工具"""
        try:
            result = await self.session.list_tools()
            tools = [t.name for t in result.tools]
            logger.info(f"可用工具: {tools}")
            return tools
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}")
            return None

    async def check_auth_status(self) -> dict:
        """检查授权状态"""
        try:
            result = await self.session.call_tool("bilibili_check_local_token", {})
            text = result.content[0].text if hasattr(result.content[0], 'text') else "{}"
            data = json.loads(text)
            payload = _extract_payload_dict(data)
            if payload:
                return payload
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"检查授权状态失败: {e}")
            return {}

    def generate_authorize_url(self) -> dict:
        """生成授权 URL（自己生成，避免 MCP 自动打开浏览器）"""
        import uuid
        state = str(uuid.uuid4())
        client_id = "2fdc4aec8e4648bd"
        gourl = "https://www.mcpcn.cc/"
        authorize_url = f"https://account.bilibili.com/pc/account-pc/auth/oauth?client_id={client_id}&gourl={gourl}&state={state}"
        return {
            "state": state,
            "authorize_url": authorize_url,
            "tips": "请在浏览器中打开此链接并完成授权"
        }

    async def get_authorize_url(self) -> dict:
        """获取授权 URL"""
        # 直接生成 URL，不调用 MCP 工具（避免自动打开浏览器）
        return self.generate_authorize_url()

    async def get_access_token(self, state: str) -> str:
        """通过 state 获取 access_token"""
        try:
            # 使用 MCP 工具轮询获取 token
            result = await self.session.call_tool("bilibili_web_poll_and_token", {"state": state})
            text = result.content[0].text if hasattr(result.content[0], 'text') else "{}"
            data = json.loads(text)
            payload = _extract_payload_dict(data)
            return payload.get("access_token", "") if isinstance(payload, dict) else ""
        except Exception as e:
            logger.error(f"获取 token 失败: {e}")
            return ""

    async def get_video_categories(self, access_token: str) -> list:
        """获取视频分区"""
        try:
            result = await self.session.call_tool("bilibili_get_video_categories", {"access_token": access_token})
            text = result.content[0].text if hasattr(result.content[0], 'text') else "[]"
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                content = data.get("content")
                if isinstance(content, list):
                    if content and isinstance(content[0], list):
                        return content[0]
                    if content and isinstance(content[0], dict):
                        return content
            return []
        except Exception as e:
            logger.error(f"获取分区失败: {e}")
            return []

    async def upload_video(
        self,
        access_token: str,
        video_file_path: str,
        title: str,
        tid: int,
        tag: str,
        desc: str = "",
        cover_file_path: str = None
    ) -> Optional[str]:
        """上传视频"""
        if not os.path.exists(video_file_path):
            logger.error(f"视频文件不存在: {video_file_path}")
            return None

        params = {
            "access_token": access_token,
            "video_file_path": video_file_path,
            "title": title[:100],  # B站标题限制100字符
            "tid": tid,
            "tag": tag,
        }
        if desc:
            params["desc"] = desc[:250]  # B站描述限制250字符
        if cover_file_path and os.path.exists(cover_file_path):
            params["cover_file_path"] = cover_file_path

        try:
            result = await self.session.call_tool("bilibili_upload_video", params)
            text = result.content[0].text if hasattr(result.content[0], 'text') else "{}"
            data = json.loads(text)
            payload = _extract_payload_dict(data)
            return (
                payload.get("resource_id")
                or payload.get("bvid")
                or payload.get("bv_id")
                or data.get("resource_id")
                or data.get("bvid")
            )
        except Exception as e:
            logger.error(f"上传失败: {e}")
            return None


def check_interactive() -> bool:
    """检查是否在交互式终端中运行"""
    import sys
    return sys.stdin.isatty()


async def upload_video_to_bilibili_mcp(
    video_path: str,
    video_title: str,
    video_tags: str,
    video_desc: str = "",
    cover_path: str = None,
    tid: int = 188,
    access_token: str = None
) -> Optional[str]:
    """
    上传视频到B站 (MCP 方式)

    Args:
        video_path: 视频文件路径
        video_title: 视频标题
        video_tags: 视频标签 (逗号分隔)
        video_desc: 视频描述
        cover_path: 封面图路径
        tid: 视频分区ID (默认 188=生活->日常)
        access_token: 预先提供的 access_token（可选）

    Returns:
        BV号或None
    """
    async with BilibiliMCPUploader() as uploader:
        # 检查授权
        auth_status = await uploader.check_auth_status()
        cached_token = auth_status.get("access_token", "")

        # 优先级：传入的token > 缓存的token
        token = access_token or cached_token

        if not token:
            logger.info("需要授权...")
            auth_result = uploader.generate_authorize_url()
            state = auth_result.get("state")
            authorize_url = auth_result.get("authorize_url")

            logger.info("=" * 60)
            logger.info("请完成以下步骤：")
            logger.info("1. 在浏览器中打开以下链接并扫码登录:")
            logger.info(f"\n{authorize_url}\n")
            logger.info(f"2. State: {state}")
            logger.info("=" * 60)

            if check_interactive():
                # 交互式环境：等待用户输入
                user_state = input("扫码登录后，按回车继续... ").strip()
                if user_state:
                    token = await uploader.get_access_token(user_state)
            else:
                # 非交互式环境：提示用户手动操作
                logger.info("3. 获取到 code 后，使用以下命令继续:")
                logger.info(f"   python -c \"import asyncio; from bilibili import BilibiliMCPUploader; "
                          f"asyncio.run((lambda u: u.__aenter__().__await__())(BilibiliMCPUploader()))\"")
                logger.info(f"   并传入 state='{state}' 获取 token")
                return None

        if not token:
            logger.error("未获取到 access_token")
            return None

        logger.info(f"Access token: {token[:20]}...")

        # 获取分区
        categories = await uploader.get_video_categories(token)
        logger.info(f"分区数量: {len(categories)}")

        # 上传视频
        logger.info("开始上传...")
        bv_id = await uploader.upload_video(
            access_token=token,
            video_file_path=video_path,
            title=video_title,
            tid=tid,
            tag=video_tags,
            desc=video_desc,
            cover_file_path=cover_path
        )

        if bv_id:
            logger.info(f"上传成功! BV号: {bv_id}")
            return bv_id
        else:
            logger.error("上传失败")
            return None


def upload(video_path, title, tags, desc="", cover_path=None, tid=188, access_token=None):
    """同步上传接口

    Args:
        video_path: 视频文件路径
        title: 视频标题
        tags: 视频标签
        desc: 视频描述
        cover_path: 封面图路径
        tid: 视频分区ID
        access_token: 预先提供的 access_token
    """
    return asyncio.run(upload_video_to_bilibili_mcp(
        video_path=video_path,
        video_title=title,
        video_tags=tags,
        video_desc=desc,
        cover_path=cover_path,
        tid=tid,
        access_token=access_token
    ))


if __name__ == "__main__":
    import datetime

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    logger = logging.getLogger(__name__)

    VIDEO_PATH = "/home/jdh/Projects/VlogCutter/JushenRenji/output/daily_summary.mp4"
    COVER_PATH = "/home/jdh/Projects/VlogCutter/JushenRenji/output/daily_summary.png"

    logger.info("=" * 50)
    logger.info("B站MCP上传测试")
    logger.info("=" * 50)

    if os.path.exists(VIDEO_PATH):
        # 调试：先列出可用工具
        async def debug_tools():
            async with BilibiliMCPUploader() as uploader:
                try:
                    tools = await uploader.list_tools()
                    logger.info(f"调试: 发现 {len(tools)} 个工具")
                    for t in tools:
                        logger.info(f"  - {t}")
                    return True
                except Exception as e:
                    logger.error(f"调试失败: {e}")
                    return False

        tools_found = asyncio.run(debug_tools())

        if tools_found:
            result = upload(
                video_path=VIDEO_PATH,
                title=f"测试-{datetime.datetime.now().strftime('%H:%M')}",
                tags="测试",
                desc="测试上传",
                cover_path=COVER_PATH if os.path.exists(COVER_PATH) else None,
                tid=188
            )
            if result:
                print(f"\n成功! BV号: {result}")
            else:
                print("\n失败")
        else:
            print("\n无法连接到 MCP 服务器")
    else:
        print(f"文件不存在: {VIDEO_PATH}")
