"""测试图片重要性打分函数"""
import json
from unittest.mock import patch


def test_rate_image_importance_returns_scores():
    """应返回与输入图片数量相同的分数列表"""
    mock_response = json.dumps({"scores": [8, 5, 9, 3, 7]})

    with patch("src.llm_tools.llm_agent.create_chat_completion", return_value=mock_response):
        from src.llm_tools.llm_agent import rate_image_importance
        captions = [
            "Figure 1: Overall architecture",
            "Figure 2: Training curve",
            "Figure 3: Method pipeline",
            "Figure 4: Ablation table",
            "Figure 5: Comparison results",
        ]
        scores = rate_image_importance(captions)
        assert len(scores) == 5
        assert all(isinstance(s, (int, float)) for s in scores)


def test_rate_image_importance_prompt_exists():
    """prompts_dict 中应包含 rate_image_importance"""
    from src.llm_tools.prompts import prompts_dict
    assert "rate_image_importance" in prompts_dict


def test_rate_image_importance_selects_top_n():
    """select_top_images 应根据分数选出 top-N"""
    from src.llm_tools.llm_agent import select_top_images
    scores = [3, 8, 1, 9, 5]
    items = ["a", "b", "c", "d", "e"]
    selected = select_top_images(items, scores, top_n=3)
    assert len(selected) == 3
    assert selected == ["b", "d", "e"]
