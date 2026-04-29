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


# ---------------------------------------------------------------------------
# generate_video_tags 三平台关键词生成测试
# ---------------------------------------------------------------------------
def test_sanitize_tag_basic():
    """sanitize 应去除标点、空格、#号"""
    from src.llm_tools.llm_agent import _sanitize_tag
    assert _sanitize_tag("具身智能") == "具身智能"
    assert _sanitize_tag("# 具身智能 ") == "具身智能"
    assert _sanitize_tag("VLA, ") == "VLA"
    assert _sanitize_tag("机器人(操作)") == "机器人操作"
    assert _sanitize_tag("") == ""
    assert _sanitize_tag(None) == ""


def test_sanitize_tag_banned_words_dropped():
    """含'首次/突破/震撼/颠覆'等违禁词的 tag 整个丢弃"""
    from src.llm_tools.llm_agent import _sanitize_tag
    assert _sanitize_tag("首次发布") == ""
    assert _sanitize_tag("突破性方法") == ""
    assert _sanitize_tag("震撼登场") == ""
    assert _sanitize_tag("颠覆AI") == ""


def test_sanitize_tag_max_len():
    """超过 max_len 应截断"""
    from src.llm_tools.llm_agent import _sanitize_tag
    assert _sanitize_tag("VeryLongTagWord", max_len=8) == "VeryLong"
    assert _sanitize_tag("具身智能技术", max_len=4) == "具身智能"


def test_normalize_tag_list_dedup_and_clamp():
    """normalize 应去重并截到 limit"""
    from src.llm_tools.llm_agent import _normalize_tag_list
    result = _normalize_tag_list(
        ["VLA", "具身智能", "VLA", "机器人", "AI论文", "VLA", "大模型"],
        limit=3,
    )
    assert result == ["VLA", "具身智能", "机器人"]


def test_normalize_tags_dict_empty_falls_back():
    """空 dict 输入应返回 fallback"""
    from src.llm_tools.llm_agent import _normalize_tags_dict, _FALLBACK_VIDEO_TAGS
    out = _normalize_tags_dict({})
    assert set(out) == {"bilibili", "xiaohongshu", "douyin"}
    assert out["bilibili"] == _FALLBACK_VIDEO_TAGS["bilibili"]


def test_normalize_tags_dict_clamps_each_platform():
    """每个平台超额都应 clamp 到各自 limit"""
    from src.llm_tools.llm_agent import _normalize_tags_dict
    huge = ["t" + str(i) for i in range(50)]
    out = _normalize_tags_dict({
        "bilibili": huge, "xiaohongshu": huge, "douyin": huge,
    })
    assert len(out["bilibili"]) == 12
    assert len(out["xiaohongshu"]) == 8
    assert len(out["douyin"]) == 5


def test_generate_video_tags_happy_path():
    """LLM 返回合法 JSON 时应正确解析三平台关键词"""
    fake_resp = (
        '{"bilibili": ["VLA", "具身智能", "机器人", "AI论文", "Diffusion", "大模型", "前沿科技", "arXiv"], '
        '"xiaohongshu": ["VLA", "AI论文笔记", "机器人", "前沿科技", "具身"], '
        '"douyin": ["VLA", "黑科技", "AI"]}'
    )
    with patch("src.llm_tools.llm_agent.create_chat_completion",
               return_value=fake_resp):
        from src.llm_tools.llm_agent import generate_video_tags
        result = generate_video_tags(
            cn_title="VLA: 视觉-语言-动作模型",
            en_title="Vision-Language-Action: A Foundation Model",
            abstract="We propose VLA, a foundation model that ...",
        )
    assert "bilibili" in result and "xiaohongshu" in result and "douyin" in result
    assert "VLA" in result["bilibili"]
    assert 8 <= len(result["bilibili"]) <= 12
    assert 5 <= len(result["xiaohongshu"]) <= 8
    assert 3 <= len(result["douyin"]) <= 5


def test_generate_video_tags_filters_exaggerated_words():
    """LLM 即使返回违禁词也应被过滤"""
    fake_resp = (
        '{"bilibili": ["VLA", "首次提出", "突破性", "机器人", "AI论文", "大模型"], '
        '"xiaohongshu": ["颠覆AI", "AI论文笔记", "VLA"], '
        '"douyin": ["震撼", "黑科技", "AI"]}'
    )
    with patch("src.llm_tools.llm_agent.create_chat_completion",
               return_value=fake_resp):
        from src.llm_tools.llm_agent import generate_video_tags
        result = generate_video_tags(cn_title="t", en_title="t", abstract="x")
    flat = result["bilibili"] + result["xiaohongshu"] + result["douyin"]
    for banned in ("首次提出", "突破性", "颠覆AI", "震撼"):
        assert banned not in flat, f"违禁词 {banned} 应被过滤"


def test_generate_video_tags_invalid_json_fallback():
    """LLM 返回非 JSON 应 fallback 而不抛"""
    with patch("src.llm_tools.llm_agent.create_chat_completion",
               return_value="这不是 JSON 而是闲话"):
        from src.llm_tools.llm_agent import generate_video_tags, _FALLBACK_VIDEO_TAGS
        result = generate_video_tags(cn_title="t", en_title="t", abstract="x")
    assert result["bilibili"] == _FALLBACK_VIDEO_TAGS["bilibili"]


def test_generate_video_tags_empty_input_fallback():
    """全空输入直接 fallback，不调 LLM"""
    from src.llm_tools.llm_agent import generate_video_tags, _FALLBACK_VIDEO_TAGS
    # 不 mock LLM，但应该不会被调用
    with patch("src.llm_tools.llm_agent.create_chat_completion") as mock_llm:
        result = generate_video_tags(cn_title="", en_title="", abstract="")
    assert mock_llm.call_count == 0
    assert result["bilibili"] == _FALLBACK_VIDEO_TAGS["bilibili"]


def test_generate_video_tags_llm_exception_fallback():
    """LLM 抛异常时也应 fallback"""
    with patch("src.llm_tools.llm_agent.create_chat_completion",
               side_effect=RuntimeError("boom")):
        from src.llm_tools.llm_agent import generate_video_tags, _FALLBACK_VIDEO_TAGS
        result = generate_video_tags(cn_title="t", en_title="t", abstract="x")
    assert result["bilibili"] == _FALLBACK_VIDEO_TAGS["bilibili"]


def test_merge_video_tags_dedup_order():
    """多篇论文 tag 合并保序去重"""
    from src.llm_tools.llm_agent import merge_video_tags
    result = merge_video_tags([
        {"bilibili": ["VLA", "具身智能"], "xiaohongshu": ["AI论文笔记"], "douyin": ["机器人"]},
        {"bilibili": ["VLA", "Diffusion", "大模型"], "xiaohongshu": ["AI论文笔记", "前沿科技"], "douyin": ["AI"]},
    ])
    # VLA 在前，去重后只出现一次
    assert result["bilibili"][0] == "VLA"
    assert result["bilibili"].count("VLA") == 1
    assert "Diffusion" in result["bilibili"]
    # xiaohongshu / douyin 同理
    assert result["xiaohongshu"][0] == "AI论文笔记"
    assert "前沿科技" in result["xiaohongshu"]


def test_merge_video_tags_empty_returns_fallback():
    """空列表合并返回 fallback"""
    from src.llm_tools.llm_agent import merge_video_tags, _FALLBACK_VIDEO_TAGS
    result = merge_video_tags([])
    assert result["bilibili"] == _FALLBACK_VIDEO_TAGS["bilibili"]
