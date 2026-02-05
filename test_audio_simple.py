#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单音频测试脚本
"""

import logging
from dashscope.audio.tts_v2 import SpeechSynthesizer

logging.basicConfig(level=logging.INFO)

def test_simple():
    print("测试TTS音频生成...")

    ss = SpeechSynthesizer(model="cosyvoice-v1", voice="longxiaochun")

    text = "你好，这是测试"
    print(f"测试文本: {text}")

    data = ss.call(text=text)
    print(f"返回数据类型: {type(data)}")
    print(f"返回数据长度: {len(data) if data else 0}")

    if data:
        path = './cache/simple_test.wav'
        with open(path, 'wb') as f:
            f.write(data)
        print(f"音频已保存到: {path}")

        from moviepy import AudioFileClip
        clip = AudioFileClip(path)
        print(f"音频时长: {clip.duration:.2f}秒")
        clip.close()

        return True
    else:
        print("❌ TTS返回空数据!")
        return False

if __name__ == "__main__":
    success = test_simple()
    if success:
        print("\n✅ 音频测试成功!")
    else:
        print("\n❌ 音频测试失败!")