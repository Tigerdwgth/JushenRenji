import os
import sys
from openai import OpenAI
from pdf_processor import PDFProcessor
from video_creator import VideoCreator
import dashscope
import glob
from moviepy import *
from PIL import Image

MANUALLY_EXTRACT_IMAGES = True
MODEL = 'qwen'
# MODEL = 'deepseek'

api_key = "sk-d55ef632e4dd4863931f15ed102cc9bd"
dashscope.api_key = "sk-265cf380a7214e4eb2b296187c32d758"
if MODEL == 'qwen':
    model = 'qwen-turbo'
    url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
elif MODEL == 'deepseek':
    model = 'deepseek-chat'
    url = 'https://api.deepseek.com/v1'
# 初始化 OpenAI 客户端
# 验证当前使用的Python路径
print(f"当前Python解释器路径: {sys.executable}")
if MODEL == 'qwen':
    client = OpenAI(
        api_key=dashscope.api_key,
        base_url=url
    )
elif MODEL == 'deepseek':
    client = OpenAI(
        api_key = api_key,
        base_url=url
    )
    
# rm -rf ./cache on windows
if os.path.exists("./cache"):
    import shutil
    shutil.rmtree("./cache")
os.makedirs("./cache")



def generate_summary(text):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant,禁止输出markdown形式的文本，不要输出，仅输出纯文本。你的目标是帮助用户快速理解论文核心内容，语言通俗易懂，适合制作论文讲解视频的文案。"},
            {"role": "user", "content": "请总结以下论文的核心内容，参考摘要，需要包含以下问题的回答，不需要重复问题：这篇文章解决了什么问题？为什么重要？论文的主要贡献是什么？研究思路如何展开？请使用简洁的表达，生成约1000字的总结。\n" + text}
        ]
    )
    return response.choices[0].message.content

def generate_title(text):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant,为讲解视频生成一个夸张的引人的标题，可以包含其中出名的作者或者知名单位,使用中文，仅输出标题，不输出其他的理由和分析，不需要输出标点符号"},
            {"role": "user", "content": text}
        ]
    )
    return response.choices[0].message.content

def main():
    print("开始程序")
    
    # 输入PDF文件路径
    pdf_file_path = input("请输入PDF文件的路径: ")
    print(f"输入的PDF路径: {pdf_file_path}")
    
    # 检查文件是否存在
    if not os.path.isfile(pdf_file_path):
        print("文件不存在，请检查路径。")
        return
    print("文件存在，开始处理PDF")
    
    # 创建PDF处理器实例
    pdf_processor = PDFProcessor(pdf_file_path)
    
    # 提取文本和图片
    print("提取PDF文本")
    text = pdf_processor.extract_text()
   
    if not MANUALLY_EXTRACT_IMAGES:
        print("提取PDF图片")
        images = pdf_processor.extract_images()
    else:
        images = glob.glob('./pic/*.png')
        images = [Image.open(image) for image in images]
    
    print(f"提取到 {len(images)} 张图片")
    videos=glob.glob('./pic/*.mp4')
    videos = [VideoFileClip(video) for video in videos]
    print(f"提取到 {len(videos)} 个视频")
    
    # 生成摘要
    print("生成摘要")
    title = generate_title(text[:1000])
    summary = generate_summary(text)
    if summary:
        print("成功生成摘要")
    else:
        print("摘要为空")
    
    # 创建视频
    print("创建视频")
    video_creator = VideoCreator(images, summary,videos)
    video_path = video_creator.create_video(f"output_video_{title}.mp4")
    
    print(f"视频已成功创建，路径为: {video_path}")
    print("程序结束")

if __name__ == "__main__":
    main()