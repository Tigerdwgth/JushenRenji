import dashscope
from dashscope.audio.tts import SpeechSynthesizer
from moviepy import *
from PIL import Image
import numpy as np

class VideoCreator:
    def __init__(self, images, text):
        self.images = images
        self.text = text
        print("VideoCreator实例已创建")

    def create_video(self, output_file):
        print("开始生成摘要的语音")
        summary_audio = SpeechSynthesizer.call(model='sambert-zhichu-v1',
                                              text=self.text,
                                              sample_rate=48000)
        
        # 保存语音文件
        if summary_audio.get_audio_data() is not None:
            print("保存语音文件")
            with open('summary.wav', 'wb') as f:
                f.write(summary_audio.get_audio_data())
        else:
            print("没有音频数据可保存")
        
        # 加载音频文件
        print("加载音频文件")
        summary_audio_clip = AudioFileClip('summary.wav')
        combined_audio = summary_audio_clip
        duration_per_pic = combined_audio.duration / len(self.images)
        print(f"每张图片持续时间: {duration_per_pic} 秒")
        
        target_size = (1920, 1080)
        
        # 创建视频剪辑
        print("开始创建视频剪辑")
        clips = []
        for idx, img in enumerate(self.images):
            print(f"处理第 {idx + 1}/{len(self.images)} 张图片")
            
            # 计算放大后的尺寸
            scale_factor = min(target_size[0] / img.width, target_size[1] / img.height)
            new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            print(f"放大图片到: {img.size}")
            
            # 创建一个新的背景图像
            new_img = Image.new("RGB", target_size, (0, 0, 0))
            
            # 计算图像放置位置
            paste_position = ((target_size[0] - img.size[0]) // 2, (target_size[1] - img.size[1]) // 2)
            
            # 将缩放后的图像粘贴到背景图像上
            new_img.paste(img, paste_position)
            img = new_img
            print(f"添加黑边后的图片大小: {img.size}")
            # 转换为numpy数组
            img_array = np.array(img)
            
            # 创建视频片段
            clip = ImageClip(img_array).with_duration(duration_per_pic)
            clips.append(clip)
            print(f"第 {idx + 1} 张图片转换为视频片段")
        
        # 合并所有剪辑
        print("合并所有视频剪辑")
        video = concatenate_videoclips(clips, method="compose")
        video = video.with_audio(combined_audio)
        print("视频剪辑合并完成")
        
        # 导出视频
        print(f"导出视频到 {output_file}")
        video.write_videofile(output_file, fps=24, codec='libx264', preset='medium')
        print("视频导出完成")
        
        return output_file
