import dashscope
from dashscope.audio.tts import SpeechSynthesizer
from moviepy import *
from PIL import Image
import numpy as np

dashscope.api_key='sk-265cf380a7214e4eb2b296187c32d758'
result = SpeechSynthesizer.call(model='sambert-zhichu-v1',
                                text='今天天气怎么样',
                                sample_rate=48000)
if result.get_audio_data() is not None:
    with open('output.wav', 'wb') as f:
        f.write(result.get_audio_data())

title="""李飞飞最新工作。震惊！多模态大模型竟然能“思考空间”？揭秘MLLM如何看、记、答三步走！"""
content="""人类具备通过连续视觉观察记住空间布局的能力，这种“视觉-空间智能”让我们能够回忆起物体位置和距离。但问题来了：多模态大模型（MLLMs）在训练了数百万视频数据后，能否也具备这种“空间思考”能力？

为此，研究者提出了一个全新的视频视觉-空间智能基准（VSI-Bench），涵盖5000多个问答对，来评估MLLMs的空间记忆与推理能力。研究发现，尽管MLLMs的表现接近人类，但依然逊色一筹。通过实验，研究者探究了模型在空间上的“思考”方式，包括语言表达和视觉推理。他们发现，模型对局部世界和空间关系的认知有所显现，但空间推理能力仍是限制其更高性能的主要瓶颈。

有趣的是，常用的语言推理技术（例如链式推理、自一致性、树式推理）未能显著提升模型表现；反之，当模型在问答过程中显式生成“认知地图”时，其对空间距离的判断能力却得到了明显增强！

这项研究揭示了当前MLLMs在“空间智能”方面的潜力与不足，同时也指出了未来发展的方向——通过更明确的空间表征和推理机制，开发具有更强空间感知能力的AI系统！"""
import glob
pics=glob.glob('./pic/*.png')

# 生成标题和内容的语音
title_audio = SpeechSynthesizer.call(model='sambert-zhichu-v1',
                                     text=title,
                                     sample_rate=48000)
content_audio = SpeechSynthesizer.call(model='sambert-zhichu-v1',
                                       text=content,
                                       sample_rate=48000)

# 保存语音文件
if title_audio.get_audio_data() is not None:
    with open('title.wav', 'wb') as f:
        f.write(title_audio.get_audio_data())

if content_audio.get_audio_data() is not None:
    with open('content.wav', 'wb') as f:
        f.write(content_audio.get_audio_data())

# 合并标题和内容的音频
title_audio_clip = AudioFileClip('title.wav')
content_audio_clip = AudioFileClip('content.wav')
combined_audio = concatenate_audioclips([title_audio_clip, content_audio_clip])
duration_per_pic = combined_audio.duration / len(pics)

# 获取第一张图片的尺寸作为标准
first_img = Image.open(pics[0])
target_size = first_img.size
first_img.close()

# 创建视频剪辑
clips = []
for pic in pics:
    # 读取并调整图片大小
    img = Image.open(pic)
    if img.size != target_size:
        img = img.resize(target_size, Image.Resampling.LANCZOS)
    # 转换为numpy数组
    img_array = np.array(img)
    img.close()
    
    # 创建视频片段
    clip = ImageClip(img_array)
    clip = clip.resized(target_size)
    clip = clip.with_duration(duration_per_pic)
    clips.append(clip)

# 合并所有剪辑
video = concatenate_videoclips(clips, method="compose")
video = video.with_audio(combined_audio)

# 导出视频
video.write_videofile('output.mp4', fps=24, codec='libx264', preset='medium')
