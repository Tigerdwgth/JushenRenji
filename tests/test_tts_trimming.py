"""测试 TTS 后兜底裁剪逻辑"""


def test_trim_segments_within_budget():
    """不超标时不裁剪"""
    from src.video_creator import trim_segments_to_duration
    segments = [
        {"type": "expl", "duration": 10.0, "image_idx": 0},
        {"type": "summary", "duration": 20.0, "image_idx": 0},
        {"type": "expl", "duration": 15.0, "image_idx": 1},
        {"type": "summary", "duration": 25.0, "image_idx": 1},
    ]
    result = trim_segments_to_duration(segments, target_duration=300)
    assert len(result) == 4  # 不裁剪


def test_trim_segments_removes_tail_expl_first():
    """超标时优先从尾部移除图片解释段"""
    from src.video_creator import trim_segments_to_duration
    segments = [
        {"type": "summary", "duration": 50.0, "image_idx": 0},
        {"type": "expl", "duration": 30.0, "image_idx": 1},
        {"type": "summary", "duration": 50.0, "image_idx": 1},
        {"type": "expl", "duration": 30.0, "image_idx": 2},  # 应优先移除尾部expl
    ]
    # 总时长 160, 目标 100, 弹性 110
    result = trim_segments_to_duration(segments, target_duration=100)
    total = sum(s["duration"] for s in result)
    assert total <= 110


def test_trim_preserves_order():
    """裁剪后保留段的顺序不变"""
    from src.video_creator import trim_segments_to_duration
    segments = [
        {"type": "summary", "duration": 40.0, "image_idx": 0},
        {"type": "expl", "duration": 20.0, "image_idx": 1},
        {"type": "summary", "duration": 40.0, "image_idx": 1},
        {"type": "expl", "duration": 20.0, "image_idx": 2},
        {"type": "summary", "duration": 40.0, "image_idx": 2},
    ]
    result = trim_segments_to_duration(segments, target_duration=100)
    # 检查保留段的 image_idx 是递增的
    indices = [s["image_idx"] for s in result]
    assert indices == sorted(indices)
