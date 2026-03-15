"""测试 summary 函数支持字数预算"""
from unittest.mock import patch
import inspect


def test_generate_summary_accepts_word_budget():
    """generate_summary 应接受 word_budget 参数"""
    from src.llm_tools.llm_agent import generate_summary
    sig = inspect.signature(generate_summary)
    assert "word_budget" in sig.parameters


def test_generate_summary_injects_budget_into_prompt():
    """word_budget 应注入到 prompt 中"""
    captured_prompts = []

    def mock_completion(prompt, user_content=None):
        captured_prompts.append(prompt)
        return "这是一个测试摘要。"

    with patch("src.llm_tools.llm_agent.create_chat_completion", side_effect=mock_completion):
        from src.llm_tools.llm_agent import generate_summary
        generate_summary("test text", word_budget=500)
        assert any("500" in p for p in captured_prompts), \
            f"Prompt should contain '500' but got: {captured_prompts}"


def test_generate_short_summary_accepts_word_budget():
    """generate_short_summary 应接受 word_budget 参数"""
    from src.llm_tools.llm_agent import generate_short_summary
    sig = inspect.signature(generate_short_summary)
    assert "word_budget" in sig.parameters
