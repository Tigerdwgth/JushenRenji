import os
import sys
from pdf_processor import PDFProcessor
from video_creator import VideoCreator
import requests
import dashscope
import glob
from moviepy import *
from PIL import Image
api_key = "sk-d55ef632e4dd4863931f15ed102cc9bd"
# 验证当前使用的Python路径
print(f"当前Python解释器路径: {sys.executable}")
dashscope.api_key='sk-265cf380a7214e4eb2b296187c32d758' 
#rm -rf ./cache on windows
if os.path.exists("./cache"):
    import shutil
    shutil.rmtree("./cache")
os.makedirs("./cache")
MANUALLY_EXTRACT_IMAGES=True
def generate_summary(text):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "请总结以下论文内容，大约300字，不要输出markdown形式的文本\n" + text}
        ],
        "stream": False
    }
    response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        print("摘要生成失败:", response.text)
        return ""
def generate_title(text):
    #生成一个夸张的标题
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant,为讲解视频生成一个夸张的引人的标题，可以包含其中出名的作者或者知名单位,使用中文，仅输出标题，不输出其他的理由和分析，不需要输出标点符号"},
            {"role": "user", "content": text}
        ],
        "stream": False
    }
    response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        print("摘要生成失败:", response.text)
        return ""
    
    
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
        images=glob.glob('./pic/*.png')
        images = [Image.open(image) for image in images]

    
    
    # 生成摘要
    print("生成摘要")
    title=generate_title(text[:1000])
    summary = generate_summary(text)
    if summary:
        print("成功生成摘要")
    else:
        print("摘要为空")
    
    # 创建视频
    print("创建视频")
    video_creator = VideoCreator(images, summary)
    video_path = video_creator.create_video(f"output_video{title}.mp4")
    
    print(f"视频已成功创建，路径为: {video_path}")
    print("程序结束")

if __name__ == "__main__":
    main()