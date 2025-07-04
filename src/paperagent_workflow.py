import os
import json
import sys
from openai import OpenAI
from pdf_processor import PDFProcessor
from video_creator import VideoCreator
from get_website_data import download_videos_files
from config import *
from get_arxiv_latest import get_paper_from_arxiv,filter_papers_by_date,Paper
from generate_cover import generate_cover
import dashscope
import glob
from moviepy import *
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
import shutil
import re
import datetime
import logging

from src.llm_tools.llm_agent import *

# 配置日志记录
logging.basicConfig(
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)
file_handler = logging.FileHandler('app.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)


def get_videoclips(url):
    try:
        if len(demowebsite)<=0:
            demowebsite=get_paper_demo_website(text[:5000])
            logging.info("获取到的网址为%s", demowebsite)
        else:
            download_videos_files(demowebsite)
    except Exception as e:
        logging.error("发生错误: %s", e)
    logging.info("发现视频网址，尝试获取视频") 
    videos=glob.glob('./pic/*.mp4')
    videos = [VideoFileClip(video) for video in videos]
    logging.info("提取到 %d 个视频", len(videos))
    return videos

def run_pdf_to_video_pipeline(paper=None,pdf_file_path=None,demowebsite=None,en_title="",prefix=""):
    logging.info("开始程序")
    # 输入PDF文件路径
    if not pdf_file_path:
        pdf_file_path, demowebsite = get_inputs()
    # 如果是网络路径，下载到本地
    pdf_file_path = download_if_remote(pdf_file_path)
    logging.info("文件存在，开始处理PDF")
    # 创建PDF处理器实例
    pdf_processor = PDFProcessor(pdf_file_path)
    # 提取文本和图片
    logging.info("提取PDF文本")
    text = pdf_processor.extract_text()
    images = process_pdf_images(pdf_processor)
    
    logging.info("提取到 %d 张图片", len(images))
    # 利用正则表达式过滤其中的网址,并访问网址直接下载视频

    videos= get_videoclips(demowebsite)
    # 生成摘要
    logging.info("生成摘要")
    title, summary = call_llm(text)
    
    # 创建视频
    logging.info("开始创建视频")
    video_creator = VideoCreator(images, summary,videos)
    save_path = f"./output/{title}.mp4"
    video_path = video_creator.create_video(save_path)
    generate_cover('./pic/1.png', title, video_path.replace(".mp4",".png"))
    logging.info("视频已成功创建，路径为: %s", video_path)
    #convert to absolute path
    video_path = os.path.abspath(video_path)
    # 上传到B站
    
    upload_video_to_bilibili(video_path, title, "人工智能,具身智能,机器人,模仿学习,VLA,具身,机械臂,计算机视觉", en_title, generate_video_proceedings(str(paper)) if paper else prefix)
    logging.info("视频上传成功！")
    logging.info("程序结束")

def call_llm(text):
    with ThreadPoolExecutor() as executor:
        future_title = executor.submit(generate_video_title, text[:1000])
        future_summary = executor.submit(generate_summary, text)
        title = future_title.result()
        summary = future_summary.result()
    if summary:
        logging.info("成功生成摘要")
    else:
        logging.warning("摘要为空")
    return title,summary

def call_llm_multithread(list_of_func_and_params):
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(func, param) for func, param in list_of_func_and_params]
        results = [future.result() for future in futures]
    return results

def get_inputs():
    pdf_file_path = input("请输入PDF文件的路径: ")
    logging.info(f"输入的PDF路径: {pdf_file_path}")
    demowebsite=input("请输入视频网址:")
    return pdf_file_path,demowebsite
def process_pdf_images(pdf_processor,cnt=None):
    """
    处理 PDF 文件中的图片。

    功能：
    - 如果未手动提取图片，则清空 `./pic` 文件夹中的所有图片文件，并从 PDF 文件中提取图片保存到该文件夹。
    - 如果已手动提取图片，则直接从 `./pic` 文件夹中加载图片。
    - 返回提取的图片列表，每个图片以 `PIL.Image` 对象的形式表示。

    参数：
    - pdf_processor: PDFProcessor 对象，用于处理 PDF 文件。

    返回值：
    - images (list): 包含提取图片的列表，每个图片为 `PIL.Image` 对象。
    """
    if not MANUALLY_EXTRACT_IMAGES:
        logging.info("提取PDF图片")
        #remove all the images in the pic folder
        files = glob.glob('./pic/*')
        for f in files:
            os.remove(f)
        pdf_processor.extract_images(cnt=cnt)
        images = glob.glob('./pic/*.png')
        images = [Image.open(image) for image in images]
    else:
        images = glob.glob('./pic/*.png')
        images = [Image.open(image) for image in images]
    return images

def download_if_remote(pdf_file_path):
    """
    检查并下载远程 PDF 文件。

    功能：
    - 如果给定的 PDF 文件路径是远程 URL，则下载该文件并缓存到 `./cache` 文件夹中。
    - 如果文件路径不是 URL，则直接返回。

    参数：
    - pdf_file_path (str): PDF 文件的路径或 URL。

    返回值：
    - pdf_file_path (str): 如果是远程文件，返回下载后的本地文件路径；否则返回原始路径。

    注意：
    - 下载的文件会保存为 `./cache/cached_pdf.pdf`。
    """
    if pdf_file_path.startswith("http"):
        logging.info("下载PDF文件")
        def download_file(url):
            """
            下载远程文件并保存到本地。

            参数：
            - url (str): 远程文件的 URL。

            返回值：
            - file_name (str): 下载后的本地文件路径。
            """
            import requests
            import os
            file_name = "cached_pdf.pdf"
            file_name = os.path.join("./cache", file_name)
            with open(file_name, "wb") as f:
                response = requests.get(url)
                f.write(response.content)
            return file_name
        pdf_file_path = download_file(pdf_file_path)
        logging.info(f"下载完成，保存路径: {pdf_file_path}")
    # 检查文件是否存在
    if not os.path.isfile(pdf_file_path):
        logging.info("文件不存在，请检查路径。")
        return -1
    return pdf_file_path

def generate_daily_arxiv_summary(query="cs.RO", date=datetime.datetime.now().strftime(r"%Y-%m-%d"), max_papers=20, output_filename="./output/daily_summary.mp4",long_or_short="short"):
    """
    为每天 arXiv 上的论文生成一个简短的日报性总结视频。
    参数：
    - query (str): arXiv 查询关键词，默认是 "cs.RO"（机器人学）。
    - date (str): 筛选论文的日期（格式：YYYY-MM-DD），默认是 None（不筛选）。
    - max_papers (int): 每日报告的最大论文数量，默认是 5。
    - output_filename (str): 生成的视频文件路径，默认是 "./output/daily_summary.mp4"。
    """
    logging.info("开始生成每日 arXiv 论文总结视频")
    # 获取最新的论文
    papers = get_paper_from_arxiv(query=query)
    logging.info(f"找到 {len(papers)} 篇论文,正在筛选...")
    # 过滤日期
    papers = filter_papers_by_date(papers, date)
    # 限制论文数量
    if len(papers) > max_papers:
        papers = papers[:max_papers]
        logging.info(f"限制论文数量为 {max_papers} 篇")
    # 如果没有找到符合条件的论文，返回
    cn_titles=[]
    if not papers:
        logging.warning("未找到符合条件的论文")
        try:
            download_if_remote(query)
        except Exception as e:
            logging.error(f"下载或处理 PDF 文件时发生错误: {e}")
        return
    else:
        logging.info(f"最终处理 {len(papers)} 篇论文")
        logging.info(f"日期: {date}")
        logging.info([paper.title for paper in papers])  # 使用 Paper 数据类的属性

    # 初始化视频片段列表
    video_clips = []
    origin_titles = []

    for idx, paper in enumerate(papers):
        logging.info(f"处理第 {idx + 1} 篇论文: {paper.title}")
        # 下载论文 PDF
        pdf_url = paper.link.replace("abs", "pdf").split('v1')[0]
        pdf_file_path = download_if_remote(pdf_url)
        if not pdf_file_path:
            logging.warning(f"无法下载或找到 PDF 文件: {pdf_url}")
            continue
        
        # 创建 PDF 处理器实例
        pdf_processor = PDFProcessor(pdf_file_path)
        
        # 提取文本和图片
        logging.info("提取 PDF 文本和图片")
        text = pdf_processor.extract_text()
        images = process_pdf_images(pdf_processor, cnt=2 if long_or_short == "short" else None)
        if not images:
            logging.warning(f"未提取到图片，跳过论文: {paper.title}")
            continue
        
        # 生成简短摘要
        logging.info("生成摘要")
        deom_website, origin_title, short_summary,cn_title = call_llm_multithread(
            [
                (get_paper_demo_website, text[:1000]),
                (generate_origin_title, text[:200]),
                (generate_short_summary, f"{text[:5000]} {paper.comments}") if long_or_short == "short" else (generate_summary, paper.comments+text),
                (generate_video_title, text[:200]),
                
            ]
        )
        
        cn_titles.append(cn_title)
        if not short_summary:
            logging.warning(f"摘要生成失败，跳过论文: {paper.title}")
            continue
        
        if len(papers) > 1:
            generate_cover('./pic/1.png', "Arxiv具身日报" + str(date), output_filename.replace(".mp4", ".png"))
        else:
            generate_cover('./pic/1.png', cn_title, output_filename.replace(".mp4", ".png"))
        # 限制图片数量为前两张
        if long_or_short == "short":
            images = images[:3]
            
        # 为当前论文创建独立视频
        logging.info(f"创建第 {idx + 1} 篇论文的视频片段")
        video_creator = VideoCreator(images, short_summary,video_clips=get_videoclips(deom_website))
        part_save_path = f"./output/part_{idx + 1}.mp4"
        part_video_path = video_creator.create_video(part_save_path)
        video_clips.append(VideoFileClip(part_video_path))
        origin_titles.append(origin_title)
    
    #如果只有一篇论文，重命名part1为论文名.mp4
    if len(papers) == 1:
        # part_save_path = f"./output/part_{idx + 1}.mp4"
        part_video_path=f"./output/part_1.mp4"
        new_part_video_path = f"./output/{cn_titles[0]}.mp4"
        os.rename(part_video_path, new_part_video_path)
        # video_clips[0] = VideoFileClip(new_part_video_path)
        # output_filename = new_part_video_path
        
        
    # 合并所有论文的视频片段
    if not video_clips:
        logging.warning("未生成任何视频片段，无法创建日报视频")
        return
    
    logging.info("合并所有论文的视频片段")
    # 将论文的标题以字幕的形式，显示在每段视频的最上方
    title_clips = [
        TextClip(text=_.title, font_size=25,
                 font=FONT_PATH,
                 size=(1920, 1080),
                 color='white',
                 text_align='center', 
                 vertical_align='top',
                 stroke_color='black', 
                 stroke_width=3, 
                duration=video_clips[idx].duration) for idx, _ in enumerate(papers)]
    final_tiles = concatenate_videoclips(title_clips, method="compose")
    final_video = concatenate_videoclips(video_clips, method="compose")
    final_video = CompositeVideoClip([final_video, final_tiles])
    final_video.write_videofile(output_filename, fps=24, codec='libx264', preset='medium')
    
    # 转换为绝对路径
    final_video_path = os.path.abspath(output_filename)
    logging.info(f"日报视频已成功生成，路径为: {final_video_path}")
    return final_video_path, origin_titles,cn_titles
