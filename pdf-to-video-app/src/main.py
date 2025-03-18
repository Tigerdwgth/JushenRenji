import os
import sys
from openai import OpenAI
from pdf_processor import PDFProcessor
from video_creator import VideoCreator
import dashscope
import glob
from moviepy import *
from PIL import Image

MANUALLY_EXTRACT_IMAGES = False
MODEL = 'qwen'
MODEL = 'deepseek'

api_key = "sk-d55ef632e4dd4863931f15ed102cc9bd"
dashscope.api_key = "sk-265cf380a7214e4eb2b296187c32d758"
if MODEL == 'qwen':
    model = 'qwen-max'
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
            {"role": "system", "content": "You are a helpful assistant,"},
            {"role": "user", "content": "请总结以下论文的核心内容,重点讲解方法，参考摘要，请使用简洁的表达，生成约1000字的总结。禁止输出markdown形式的文本，不要一条一条的列出，而是以长文的形式。你的目标是帮助用户快速理解论文核心内容，语言通俗易懂，适合制作论文讲解视频的文案。请以 “这篇文章...”作为开始，不要重复文章标题\n" + text}
        ]
    )
    return response.choices[0].message.content

def generate_title(text):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant,为讲解视频生成一个简介易懂明了吸引人的中文标题，仅输出标题不输出其他内容，禁止输出多余内容，与标点符号，不要标题加引号。"},
            {"role": "user", "content": text}
        ]
    )
    return response.choices[0].message.content

def main():
    print("开始程序")
    
    # 输入PDF文件路径
    pdf_file_path = input("请输入PDF文件的路径: ")
    print(f"输入的PDF路径: {pdf_file_path}")
    # 如果是网络路径，下载到本地
    if pdf_file_path.startswith("http"):
        print("下载PDF文件")
        def download_file(url):
            import requests
            import os
            file_name = "cached_pdf.pdf"
            file_name = os.path.join("./cache", file_name)
            with open(file_name, "wb") as f:
                response = requests.get(url)
                f.write(response.content)
            return file_name
        pdf_file_path = download_file(pdf_file_path)
        print(f"下载完成，保存路径: {pdf_file_path}")
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
        #remove all the images in the pic folder
        files = glob.glob('./pic/*')
        for f in files:
            os.remove(f)
        pdf_processor.extract_images()
        images = glob.glob('./pic/*.png')
        images = [Image.open(image) for image in images]
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