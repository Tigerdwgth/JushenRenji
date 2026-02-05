#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频处理管道测试脚本
测试修复后的音频生成、加载、合并和资源管理功能
"""

import os
import sys
import logging
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

# 导入音频处理工具
try:
    from src.utils.audio_helpers import (
        safe_tts_save,
        safe_audio_clip_loader,
        safe_concatenate_audio,
        create_silent_audio,
        AudioResourceManager,
        audio_logger
    )
except ImportError:
    try:
        from utils.audio_helpers import (
            safe_tts_save,
            safe_audio_clip_loader,
            safe_concatenate_audio,
            create_silent_audio,
            AudioResourceManager,
            audio_logger
        )
    except ImportError:
        print("❌ 无法导入音频处理工具模块")
        sys.exit(1)

from dashscope.audio.tts_v2 import SpeechSynthesizer
import dashscope

# 设置DashScope API密钥
try:
    from src.config import DASHSCOPE_API_KEY
    dashscope.api_key = DASHSCOPE_API_KEY
except ImportError:
    try:
        from config import DASHSCOPE_API_KEY
        dashscope.api_key = DASHSCOPE_API_KEY
    except ImportError:
        print("⚠️  无法导入配置，将使用默认环境变量")


def test_tts_generation():
    """测试TTS音频生成"""
    print("\n" + "="*60)
    print("测试1: TTS音频生成")
    print("="*60)

    tests = []

    # 测试文本
    test_text = "这是一个音频修复测试，确保TTS正常工作"

    try:
        ss = SpeechSynthesizer(model="cosyvoice-v1", voice="longxiaochun")
        audio_logger.info("开始TTS测试")

        # 使用安全TTS保存
        audio_path = './cache/test_pipeline.wav'
        result_path = safe_tts_save(ss, test_text, audio_path, 0)

        if result_path:
            tests.append({
                'name': 'TTS数据生成',
                'passed': True,
                'details': f"成功生成音频文件: {result_path}"
            })
            print(f"✅ TTS数据生成: 成功")
        else:
            tests.append({
                'name': 'TTS数据生成',
                'passed': False,
                'details': "TTS返回空数据或验证失败"
            })
            print(f"❌ TTS数据生成: 失败")

    except Exception as e:
        tests.append({
            'name': 'TTS数据生成',
            'passed': False,
            'details': f"异常: {e}"
        })
        print(f"❌ TTS数据生成: 异常 - {e}")

    return tests


def test_audio_loading():
    """测试音频文件加载"""
    print("\n" + "="*60)
    print("测试2: 音频文件加载")
    print("="*60)

    tests = []

    # 测试加载生成的音频文件
    audio_path = './cache/test_pipeline.wav'

    try:
        clip = safe_audio_clip_loader(audio_path)

        if clip and hasattr(clip, 'duration') and clip.duration > 0:
            tests.append({
                'name': '音频文件加载',
                'passed': True,
                'details': f"音频时长: {clip.duration:.2f}秒, 采样率: {clip.fps}Hz"
            })
            print(f"✅ 音频文件加载: 成功 (时长: {clip.duration:.2f}秒)")

            # 关闭clip
            clip.close()
        else:
            tests.append({
                'name': '音频文件加载',
                'passed': False,
                'details': "音频文件损坏或时长无效"
            })
            print(f"❌ 音频文件加载: 失败")

    except Exception as e:
        tests.append({
            'name': '音频文件加载',
            'passed': False,
            'details': f"异常: {e}"
        })
        print(f"❌ 音频文件加载: 异常 - {e}")

    return tests


def test_audio_merging():
    """测试音频合并"""
    print("\n" + "="*60)
    print("测试3: 音频合并")
    print("="*60)

    tests = []

    try:
        # 加载多个音频文件进行合并测试
        audio_files = ['./cache/test_pipeline.wav']

        if os.path.exists('./cache/test_pipeline.wav'):
            # 加载第一个音频文件
            clip1 = safe_audio_clip_loader('./cache/test_pipeline.wav')

            if clip1:
                # 合并音频（自己和自己合并，测试重复合并）
                merged = safe_concatenate_audio([clip1, clip1])

                if merged and hasattr(merged, 'duration') and merged.duration > 0:
                    tests.append({
                        'name': '音频合并',
                        'passed': True,
                        'details': f"合并后时长: {merged.duration:.2f}秒"
                    })
                    print(f"✅ 音频合并: 成功 (合并后时长: {merged.duration:.2f}秒)")

                    # 关闭合并后的音频
                    merged.close()
                    clip1.close()
                else:
                    tests.append({
                        'name': '音频合并',
                        'passed': False,
                        'details': "合并后音频无效"
                    })
                    print(f"❌ 音频合并: 失败")

                    if clip1:
                        clip1.close()
            else:
                tests.append({
                    'name': '音频合并',
                    'passed': False,
                    'details': "无法加载音频文件进行合并"
                })
                print(f"❌ 音频合并: 失败 - 无法加载音频文件")
        else:
            tests.append({
                'name': '音频合并',
                'passed': False,
                'details': "测试音频文件不存在"
            })
            print(f"❌ 音频合并: 失败 - 测试音频文件不存在")

    except Exception as e:
        tests.append({
            'name': '音频合并',
            'passed': False,
            'details': f"异常: {e}"
        })
        print(f"❌ 音频合并: 异常 - {e}")

    return tests


def test_resource_management():
    """测试资源管理"""
    print("\n" + "="*60)
    print("测试4: 资源管理")
    print("="*60)

    tests = []

    try:
        # 测试AudioResourceManager
        with AudioResourceManager() as manager:
            # 加载音频文件
            if os.path.exists('./cache/test_pipeline.wav'):
                clip = safe_audio_clip_loader('./cache/test_pipeline.wav')

                if clip:
                    manager.add_clip(clip)

                    # 验证clip已添加到管理器
                    if len(manager.clips) > 0:
                        tests.append({
                            'name': '资源管理',
                            'passed': True,
                            'details': f"成功管理 {len(manager.clips)} 个音频资源"
                        })
                        print(f"✅ 资源管理: 成功 (管理 {len(manager.clips)} 个音频资源)")
                    else:
                        tests.append({
                            'name': '资源管理',
                            'passed': False,
                            'details': "音频资源未正确添加到管理器"
                        })
                        print(f"❌ 资源管理: 失败 - 音频资源未正确添加")
                else:
                    tests.append({
                        'name': '资源管理',
                        'passed': False,
                        'details': "无法加载测试音频文件"
                    })
                    print(f"❌ 资源管理: 失败 - 无法加载测试音频文件")
            else:
                tests.append({
                    'name': '资源管理',
                    'passed': False,
                    'details': "测试音频文件不存在"
                })
                print(f"❌ 资源管理: 失败 - 测试音频文件不存在")

        # 验证资源是否已自动清理
        if os.path.exists('./cache/test_pipeline.wav'):
            try:
                # 尝试重新加载文件，验证资源已正确释放
                from moviepy import AudioFileClip
                test_clip = AudioFileClip('./cache/test_pipeline.wav')
                test_clip.close()

                tests.append({
                    'name': '资源清理',
                    'passed': True,
                    'details': "资源管理器正确清理了音频资源"
                })
                print(f"✅ 资源清理: 成功")
            except Exception as e:
                tests.append({
                    'name': '资源清理',
                    'passed': False,
                    'details': f"资源清理失败: {e}"
                })
                print(f"❌ 资源清理: 失败 - {e}")

    except Exception as e:
        tests.append({
            'name': '资源管理',
            'passed': False,
            'details': f"异常: {e}"
        })
        print(f"❌ 资源管理: 异常 - {e}")

    return tests


def test_silent_audio():
    """测试静音音频生成"""
    print("\n" + "="*60)
    print("测试5: 静音音频生成")
    print("="*60)

    tests = []

    try:
        # 测试创建静音音频
        silent = create_silent_audio(duration=1.0)

        if silent and hasattr(silent, 'duration') and silent.duration > 0:
            tests.append({
                'name': '静音音频生成',
                'passed': True,
                'details': f"成功生成 {silent.duration:.2f} 秒静音音频"
            })
            print(f"✅ 静音音频生成: 成功 (时长: {silent.duration:.2f}秒)")

            # 关闭静音音频
            silent.close()
        else:
            tests.append({
                'name': '静音音频生成',
                'passed': False,
                'details': "静音音频生成失败"
            })
            print(f"❌ 静音音频生成: 失败")

    except Exception as e:
        tests.append({
            'name': '静音音频生成',
            'passed': False,
            'details': f"异常: {e}"
        })
        print(f"❌ 静音音频生成: 异常 - {e}")

    return tests


def main():
    """主测试函数"""
    print("🚀 开始音频处理管道测试")
    print(f"当前工作目录: {os.getcwd()}")

    # 创建缓存目录
    os.makedirs('./cache', exist_ok=True)

    # 运行所有测试
    all_tests = []
    all_tests.extend(test_tts_generation())
    all_tests.extend(test_audio_loading())
    all_tests.extend(test_audio_merging())
    all_tests.extend(test_resource_management())
    all_tests.extend(test_silent_audio())

    # 输出测试结果汇总
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)

    passed = 0
    failed = 0

    for test in all_tests:
        status = "✅" if test['passed'] else "❌"
        print(f"{status} {test['name']}: {test['details']}")

        if test['passed']:
            passed += 1
        else:
            failed += 1

    print("\n" + "="*60)
    print(f"总计: {passed} 通过, {failed} 失败")
    print("="*60)

    if failed == 0:
        print("\n🎉 所有音频测试通过！音频修复成功！")
        return True
    else:
        print(f"\n⚠️  有 {failed} 个测试失败，请检查日志文件获取详细信息")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 测试运行异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)