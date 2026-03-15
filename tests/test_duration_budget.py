"""测试时长预算计算"""
import sys
sys.path.insert(0, './src')


def test_compute_word_budget_default():
    """300秒 → 总预算1200字, 总结720字, 图片480字"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=300)
    assert budget["total"] == 1200
    assert budget["summary"] == 720
    assert budget["images"] == 480


def test_compute_word_budget_short():
    """30秒 → 总预算120字"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=30)
    assert budget["total"] == 120
    assert budget["summary"] == 72
    assert budget["images"] == 48


def test_per_image_budget():
    """图片预算平均分配到每张图"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=300, num_images=5)
    assert budget["per_image"] == 96  # 480 / 5


def test_per_image_budget_zero_images():
    """0张图片时 per_image 应为 0, 总结拿到全部预算"""
    from paperagent_workflow import compute_word_budget
    budget = compute_word_budget(target_duration=300, num_images=0)
    assert budget["per_image"] == 0
    assert budget["summary"] == 1200
