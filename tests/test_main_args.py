"""测试 main.py CLI 参数解析"""
import argparse


def test_target_duration_default():
    """--target_duration 默认值应为 300"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", type=str)
    parser.add_argument("--video_length", type=str, default="long", choices=["long", "short"])
    parser.add_argument("--output_language", type=str, default="zh", choices=["zh", "en"])
    parser.add_argument("--platforms", type=str, default="bilibili,xiaohongshu")
    parser.add_argument("--target_duration", type=int, default=300)
    args = parser.parse_args(["--filename", "cs.RO"])
    assert args.target_duration == 300


def test_target_duration_custom():
    """--target_duration 可自定义"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", type=str)
    parser.add_argument("--target_duration", type=int, default=300)
    args = parser.parse_args(["--filename", "test", "--target_duration", "180"])
    assert args.target_duration == 180
