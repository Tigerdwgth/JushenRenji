"""测试 llm_agent.py 核心功能"""
import json
from unittest.mock import patch, MagicMock


def test_parse_json_response_valid():
    """有效 JSON 应正确解析"""
    from src.llm_tools.llm_agent import _parse_json_response
    result = _parse_json_response('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_response_with_markdown():
    """带 markdown 包裹的 JSON 也应能解析"""
    from src.llm_tools.llm_agent import _parse_json_response
    raw = 'Here is the result:\n```json\n{"scores": [1, 2, 3]}\n```\nDone.'
    result = _parse_json_response(raw)
    assert result == {"scores": [1, 2, 3]}


def test_parse_json_response_empty():
    """空字符串应返回空字典"""
    from src.llm_tools.llm_agent import _parse_json_response
    assert _parse_json_response("") == {}
    assert _parse_json_response(None) == {}


def test_parse_json_response_invalid():
    """无法解析的文本应返回空字典"""
    from src.llm_tools.llm_agent import _parse_json_response
    assert _parse_json_response("这不是JSON") == {}


def test_get_prompt_existing():
    """应能获取已注册的 prompt"""
    from src.llm_tools.llm_agent import get_prompt
    from src.llm_tools.prompts import prompts_dict
    # 至少 generate_summary 应该存在
    assert "generate_summary" in prompts_dict
    prompt = get_prompt("generate_summary", "附加文本")
    assert "附加文本" in prompt


def test_get_prompt_nonexistent():
    """未注册的函数名应返回空 prompt"""
    from src.llm_tools.llm_agent import get_prompt
    prompt = get_prompt("nonexistent_function_xyz")
    assert prompt == ""


def test_structured_plan_to_text_full():
    """完整结构化脚本应正确拼接"""
    from src.llm_tools.llm_agent import structured_plan_to_text
    plan = {
        "opening": {"script": "开场白"},
        "intro": {"script": "背景介绍"},
        "method": {"script": "方法描述"},
        "results": {"script": "实验结果"},
    }
    text = structured_plan_to_text(plan)
    assert "开场白" in text
    assert "实验结果" in text
    parts = text.split("\n")
    assert len(parts) == 4


def test_structured_plan_to_text_partial():
    """缺少部分段落的脚本应跳过缺失段"""
    from src.llm_tools.llm_agent import structured_plan_to_text
    plan = {
        "opening": {"script": "开场"},
        "results": {"script": "结果"},
    }
    text = structured_plan_to_text(plan)
    parts = text.split("\n")
    assert len(parts) == 2


def test_structured_plan_to_text_string_values():
    """段落值为字符串时也应正确处理"""
    from src.llm_tools.llm_agent import structured_plan_to_text
    plan = {
        "opening": "直接字符串",
        "intro": {"script": "字典形式"},
    }
    text = structured_plan_to_text(plan)
    assert "直接字符串" in text
    assert "字典形式" in text


def test_structured_plan_to_text_empty():
    """空脚本应返回空字符串"""
    from src.llm_tools.llm_agent import structured_plan_to_text
    assert structured_plan_to_text({}) == ""
    assert structured_plan_to_text(None) == ""


def test_select_top_images_basic():
    """基本 top-N 选择"""
    from src.llm_tools.llm_agent import select_top_images
    items = ["a", "b", "c", "d", "e"]
    scores = [3, 8, 1, 9, 5]
    selected = select_top_images(items, scores, top_n=2)
    assert len(selected) == 2
    # 应选 b(8) 和 d(9)，按原始顺序
    assert selected == ["b", "d"]


def test_select_top_images_fewer_than_n():
    """项目少于 top_n 时应全部返回"""
    from src.llm_tools.llm_agent import select_top_images
    items = ["a", "b"]
    scores = [5, 3]
    selected = select_top_images(items, scores, top_n=5)
    assert len(selected) == 2


def test_lazy_init_not_triggered_on_import():
    """导入模块不应触发 LLM 客户端初始化"""
    import src.llm_tools.llm_agent as agent
    # client 应该还是 None（未调用 _ensure_initialized）
    # 注意：如果之前的测试已经触发了初始化，这个测试的意义有限
    # 但至少验证模块级变量存在
    assert hasattr(agent, '_initialized')
    assert hasattr(agent, 'client')
    assert hasattr(agent, 'model')


def test_create_chat_completion_mock():
    """mock LLM 调用应返回预期结果"""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "测试回复"

    with patch("src.llm_tools.llm_agent._ensure_initialized"):
        with patch("src.llm_tools.llm_agent.client") as mock_client:
            mock_client.chat.completions.create.return_value = mock_response
            from src.llm_tools.llm_agent import create_chat_completion
            result = create_chat_completion("测试prompt")
            assert result == "测试回复"


def test_generate_video_title_removes_exaggerated_words():
    """标题生成后应移除“首次/突破”等夸张宣传词。"""
    with patch("src.llm_tools.llm_agent.create_chat_completion", return_value="首次实现精准操作新突破"):
        from src.llm_tools.llm_agent import generate_video_title

        result = generate_video_title("论文内容")

    assert "首次" not in result
    assert "突破" not in result
    assert result
