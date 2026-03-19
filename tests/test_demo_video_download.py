"""论文Demo视频下载功能单元测试。

覆盖以下修复：
- Bug 1: get_paper_demo_website() UnboundLocalError（LLM返回无JSON时）
- Bug 2: deom_website 拼写错误（paperagent_workflow.py）
- Bug 3: parsed_json 缺少 key 时 KeyError
- Bug 4: download_videos_files 健壮性（网络异常、无效URL等）
"""
import os
import sys
import json
import logging
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock

# 确保 src 目录在 import 路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# 预注入缺失的第三方依赖 stub，防止 import llm_agent 时 ModuleNotFoundError
# 策略：先尝试真实导入，失败时才注入 stub，避免破坏已安装的包
def _ensure_module(mod_name, attrs=None):
    """尝试导入模块，失败时注入 stub。"""
    try:
        __import__(mod_name)
    except ImportError:
        parts = mod_name.split('.')
        for i in range(len(parts)):
            partial = '.'.join(parts[:i+1])
            if partial not in sys.modules:
                m = types.ModuleType(partial)
                m.__path__ = []  # 标记为包
                sys.modules[partial] = m
    if attrs:
        mod = sys.modules.get(mod_name)
        if mod:
            for attr_name, attr_val in attrs.items():
                if not hasattr(mod, attr_name):
                    setattr(mod, attr_name, attr_val)

_ensure_module('dashscope')
_ensure_module('dashscope.audio')
_ensure_module('dashscope.audio.tts_v2')
_ensure_module('openai', {'OpenAI': MagicMock()})
_ensure_module('yaml', {'safe_load': MagicMock(return_value={})})


# =========================================================================
# Bug 1 & 3: get_paper_demo_website 测试
# =========================================================================
class TestGetPaperDemoWebsite(unittest.TestCase):
    """测试 get_paper_demo_website 的各种边界情况。"""

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_no_json_in_response_returns_empty(self, mock_llm):
        """Bug 1: LLM 返回纯文本（不含 JSON），应返回空字符串而非抛出 UnboundLocalError。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = "这个论文没有演示网站"
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, '')

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_valid_json_state_1_returns_url(self, mock_llm):
        """正常情况: state=1 时返回 url。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = json.dumps({"state": "1", "url": "https://example.com/demo"})
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, "https://example.com/demo")

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_valid_json_state_1_int_returns_url(self, mock_llm):
        """state 为整数 1 时也应正常返回 url。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = json.dumps({"state": 1, "url": "https://example.com/demo"})
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, "https://example.com/demo")

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_valid_json_state_0_returns_empty(self, mock_llm):
        """state=0 时应返回空字符串。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = json.dumps({"state": "0", "url": ""})
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, '')

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_missing_state_key_returns_empty(self, mock_llm):
        """Bug 3: JSON 中缺少 state key 时不应抛出 KeyError。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = json.dumps({"url": "https://example.com"})
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, '')

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_missing_url_key_returns_empty(self, mock_llm):
        """Bug 3: state=1 但缺少 url key 时应返回空字符串而非 KeyError。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = json.dumps({"state": "1"})
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, '')

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_invalid_state_value_returns_empty(self, mock_llm):
        """state 值不在 [0, 1, '0', '1'] 范围内时应返回空字符串。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = json.dumps({"state": "2", "url": "https://example.com"})
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, '')

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_malformed_json_returns_empty(self, mock_llm):
        """JSON 格式错误时应返回空字符串。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = '{"state": "1", "url": broken}'
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, '')

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_json_embedded_in_text(self, mock_llm):
        """LLM 返回的文本中嵌入了 JSON 片段，应能正确提取。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = '根据论文分析: {"state": "1", "url": "https://demo.io"} 以上是结果。'
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, "https://demo.io")

    @patch('src.llm_tools.llm_agent.create_chat_completion')
    def test_empty_response_returns_empty(self, mock_llm):
        """LLM 返回空字符串时应返回空字符串。"""
        from src.llm_tools.llm_agent import get_paper_demo_website
        mock_llm.return_value = ""
        result = get_paper_demo_website("some paper text")
        self.assertEqual(result, '')


# =========================================================================
# Bug 2: deom_website 拼写错误验证
# =========================================================================
class TestDemoWebsiteSpelling(unittest.TestCase):
    """验证 paperagent_workflow.py 中不再存在 deom_website 拼写错误。"""

    def test_no_deom_website_typo_in_workflow(self):
        """确认源码中所有 deom_website 已修正为 demo_website。"""
        workflow_path = os.path.join(
            os.path.dirname(__file__), '..', 'src', 'paperagent_workflow.py'
        )
        with open(workflow_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertNotIn('deom_website', content,
                         "paperagent_workflow.py 中仍存在 'deom_website' 拼写错误")
        # 确认正确的变量名存在
        self.assertIn('demo_website', content,
                       "paperagent_workflow.py 中缺少 'demo_website' 变量")


# =========================================================================
# Bug 4: download_videos_files 健壮性测试
# =========================================================================
class TestDownloadVideosFiles(unittest.TestCase):
    """测试 download_videos_files 的异常处理与健壮性。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_url_returns_false(self):
        """空 URL 应直接返回 False。"""
        from src.get_website_data import download_videos_files
        self.assertFalse(download_videos_files('', download_folder=self.tmpdir))

    def test_none_url_returns_false(self):
        """None URL 应直接返回 False。"""
        from src.get_website_data import download_videos_files
        self.assertFalse(download_videos_files(None, download_folder=self.tmpdir))

    def test_invalid_url_scheme_returns_false(self):
        """非 http/https 的 URL 应返回 False。"""
        from src.get_website_data import download_videos_files
        self.assertFalse(download_videos_files('ftp://example.com', download_folder=self.tmpdir))

    def test_non_string_url_returns_false(self):
        """非字符串类型的 URL 应返回 False。"""
        from src.get_website_data import download_videos_files
        self.assertFalse(download_videos_files(12345, download_folder=self.tmpdir))

    @patch('src.get_website_data.requests.Session')
    def test_connection_error_returns_false(self, mock_session_cls):
        """网络连接失败时应返回 False 而非抛出异常。"""
        import requests
        from src.get_website_data import download_videos_files
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("DNS resolution failed")
        mock_session_cls.return_value = mock_session
        result = download_videos_files('https://nonexistent.example.com', download_folder=self.tmpdir)
        self.assertFalse(result)

    @patch('src.get_website_data.requests.Session')
    def test_timeout_returns_false(self, mock_session_cls):
        """请求超时时应返回 False 而非抛出异常。"""
        import requests
        from src.get_website_data import download_videos_files
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.Timeout("Request timed out")
        mock_session_cls.return_value = mock_session
        result = download_videos_files('https://example.com/slow', download_folder=self.tmpdir)
        self.assertFalse(result)

    @patch('src.get_website_data.requests.Session')
    def test_http_error_returns_false(self, mock_session_cls):
        """HTTP 404/500 等错误应返回 False。"""
        import requests
        from src.get_website_data import download_videos_files
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_session.get.return_value = mock_response
        mock_session_cls.return_value = mock_session
        result = download_videos_files('https://example.com/404', download_folder=self.tmpdir)
        self.assertFalse(result)

    @patch('src.get_website_data.requests.Session')
    def test_page_without_video_tags_returns_false(self, mock_session_cls):
        """页面无 video 标签时应返回 False。"""
        from src.get_website_data import download_videos_files
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "<html><body><p>No videos here</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session_cls.return_value = mock_session
        result = download_videos_files('https://example.com/no-video', download_folder=self.tmpdir)
        self.assertFalse(result)

    @patch('src.get_website_data.requests.Session')
    def test_successful_video_download(self, mock_session_cls):
        """正常下载流程应返回 True 并保存文件。"""
        from src.get_website_data import download_videos_files
        mock_session = MagicMock()

        # 第一次 get: 页面 HTML
        page_response = MagicMock()
        page_response.text = '<html><body><video src="demo.mp4"></video></body></html>'
        page_response.raise_for_status = MagicMock()

        # 第二次 get: 视频文件
        video_response = MagicMock()
        video_response.iter_content.return_value = [b'\x00' * 1024]
        video_response.raise_for_status = MagicMock()

        mock_session.get.side_effect = [page_response, video_response]
        mock_session_cls.return_value = mock_session

        result = download_videos_files('https://example.com/project', download_folder=self.tmpdir)
        self.assertTrue(result)
        # 验证文件已创建
        downloaded_files = [f for f in os.listdir(self.tmpdir) if f.endswith('.mp4')]
        self.assertEqual(len(downloaded_files), 1)

    @patch('src.get_website_data.requests.Session')
    def test_max_videos_limit(self, mock_session_cls):
        """max_videos 参数应限制下载数量。"""
        from src.get_website_data import download_videos_files
        mock_session = MagicMock()

        # 页面包含多个 video 标签
        video_tags = ''.join(f'<video src="vid{i}.mp4"></video>' for i in range(20))
        page_response = MagicMock()
        page_response.text = f'<html><body>{video_tags}</body></html>'
        page_response.raise_for_status = MagicMock()

        # 所有视频请求都返回有效数据
        video_response = MagicMock()
        video_response.iter_content.return_value = [b'\x00' * 1024]
        video_response.raise_for_status = MagicMock()

        # 第一个 get 是页面，后续都是视频
        mock_session.get.side_effect = [page_response] + [video_response] * 5
        mock_session_cls.return_value = mock_session

        result = download_videos_files(
            'https://example.com/many-videos',
            download_folder=self.tmpdir,
            max_videos=3,
        )
        self.assertTrue(result)
        # session.get 被调用次数 = 1(页面) + 3(限制)
        self.assertEqual(mock_session.get.call_count, 4)

    @patch('src.get_website_data.requests.Session')
    def test_video_download_timeout_continues(self, mock_session_cls):
        """单个视频下载超时不应影响后续视频下载。"""
        import requests
        from src.get_website_data import download_videos_files
        mock_session = MagicMock()

        page_response = MagicMock()
        page_response.text = (
            '<html><body>'
            '<video src="slow.mp4"></video>'
            '<video src="fast.mp4"></video>'
            '</body></html>'
        )
        page_response.raise_for_status = MagicMock()

        # 第一个视频超时，第二个正常
        timeout_response = requests.Timeout("timeout")
        ok_response = MagicMock()
        ok_response.iter_content.return_value = [b'\x00' * 1024]
        ok_response.raise_for_status = MagicMock()

        mock_session.get.side_effect = [page_response, timeout_response, ok_response]
        mock_session_cls.return_value = mock_session

        result = download_videos_files('https://example.com', download_folder=self.tmpdir)
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
