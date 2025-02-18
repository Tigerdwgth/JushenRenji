import dashscope
from dashscope.audio.tts_v2 import *
from moviepy import *
from PIL import Image
import numpy as np
import re

class VideoCreator:
    def __init__(self, images, text, video_clips=None):
        self.images = images
        self.text = text
        self.video_clips = video_clips or []
        self.texts = []
        self.time = []
        self.texts_starts = []
        self.audioclips = []
        self.video = None
        print("VideoCreator实例已创建")

    def videocaption(self, subtitle_list):        
        txts = []
        for si,sentence in enumerate(subtitle_list):
            #一行最多10个字
            sentence_segs=[sentence[i:i+20] for i in range(0,len(sentence),20)]
            duration=self.time[si]/len(sentence_segs)
            for seg in sentence_segs:
                txt = (TextClip(text=seg, 
                                font_size=80,
                                size=(1920, 1080),
                                font=r'F:\PaperReadingAgent\font\SIMHEI.TTF',
                                text_align='center',
                                vertical_align='bottom',
                                color='white',
                                stroke_color='black',
                                stroke_width=2,
                                duration=duration,
                                )
                    )
                txts.append(txt)
        # connect the text clips
        subtitles = concatenate_videoclips(txts)
        # 合成字幕
        self.video = CompositeVideoClip([self.video, subtitles])
        # 合成音频
        # self.video = self.video.with_audio(AudioFileClip('Python.mp3'))
        # 保存视频，注意加上参数audio_codec='aac'，否则音频无声音



    def create_video(self, output_file):
        print("开始生成摘要的语音")
        #按中英文句号分割sentences = re.split(r'[。！？]', text)
        # self.texts=self.text.split('。')
        self.texts=re.split(r'[。！，？,.*\n\s:：]', self.text)
        #计算每句话的时间
        #合成每句话的音频
        model ="cosyvoice-v1"
        voice = "longxiaochun"
        audio_start=0
        tmp_texts=[]
        ss=SpeechSynthesizer(model=model, voice=voice)
        for idx,text in enumerate(self.texts):
            summary_audio = ss.call(text=text)
            #save audio
            if summary_audio.get_audio_data() is not None:
                tmp_texts.append(text)
                with open(f'./cache/summary{idx}.wav', 'wb') as f:
                    f.write(summary_audio.get_audio_data())
                self.audioclips.append(AudioFileClip(f'./cache/summary{idx}.wav'))
                self.time.append(self.audioclips[-1].duration)
                self.texts_starts.append(audio_start)
                audio_start+=self.audioclips[-1].duration
            else:
                print("没有音频数据可保存")
        self.texts=tmp_texts
        # 加载音频文件
        
        print("合成总音频文件")
        summary_audio_clip = concatenate_audioclips(self.audioclips)
        combined_audio = summary_audio_clip
        duration_per_pic = (combined_audio.duration) / len(self.images)   
        print(f"每张图片持续时间: {duration_per_pic} 秒")
        
        target_size = (1920, 1080)
        
        # 创建视频剪辑
        print("开始创建视频剪辑")
        clips = []
                # 处理视频片段
        if self.video_clips:
            print("处理视频片段")
            for idx, video_clip in enumerate(self.video_clips):
                # 调整视频尺寸以匹配目标尺寸
                video_clip = video_clip.resized(width=1920, height=1080)
                clips.append(video_clip)
                print(f"添加第 {idx + 1} 个视频片段")
            duration_per_pic = (combined_audio.duration-sum([clips[i].duration for i in range(len(clips))])
                                ) / len(self.images)       
        # 处理图片
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
        self.video = concatenate_videoclips(clips, method="compose")
        self.video = self.video.with_audio(combined_audio)
        #添加字幕
        self.videocaption(self.texts)
        
        print("视频剪辑合并完成")
        
        # 导出视频
        print(f"导出视频到 {output_file}")
        self.video.write_videofile(output_file, fps=24, codec='libx264', preset='medium')
        print("视频导出完成")
        
        return output_file
