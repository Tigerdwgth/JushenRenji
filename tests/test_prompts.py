"""测试 prompts.py 提示词注册完整性"""


def test_prompts_dict_contains_core_functions():
    """prompts_dict 应包含所有核心 LLM 函数的 prompt"""
    from src.llm_tools.prompts import prompts_dict

    required_keys = [
        "generate_summary",
        "generate_short_summary",
        "generate_video_title",
        "generate_origin_title",
        "generate_structured_video_plan",
        "rate_image_importance",
        "add_context_to_image_explanations",
        "extract_captions_to_dict",
    ]
    for key in required_keys:
        assert key in prompts_dict, f"缺少 prompt: {key}"


def test_prompts_not_empty():
    """每个注册的 prompt 不应为空字符串"""
    from src.llm_tools.prompts import prompts_dict

    for key, value in prompts_dict.items():
        assert value and len(value.strip()) > 0, f"prompt '{key}' 为空"
