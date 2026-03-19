import os
import json
import sys
from openai import OpenAI
from pdf_processor import PDFProcessor
from video_creator import VideoCreator
from get_website_data import download_videos_files
from config import FONT_PATH
from get_arxiv_latest import get_paper_from_arxiv,filter_papers_by_date,Paper
from generate_cover import generate_cover
# from auto_upload_bilibili import upload_video_to_bilibili
import dashscope
import glob
from moviepy import *
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
import shutil
import re
import datetime
import logging

from src.llm_tools.llm_agent import (
    MANUALLY_EXTRACT_IMAGES,
    generate_summary,
    generate_short_summary,
    generate_video_title,
    generate_origin_title,
    generate_structured_video_plan,
    structured_plan_to_text,
    get_paper_demo_website,
    rate_image_importance,
    select_top_images,
    add_context_to_image_explanations,
)
# image agent for qwen-vl
try:
    from src.llm_tools.image_agent import ImageAgent
except Exception:
    # fallback import path
    from llm_tools.image_agent import ImageAgent

try:
    from src.extract_caption import extract_captions_from_pdf
except Exception:
    try:
        from extract_caption import extract_captions_from_pdf
    except Exception:
        extract_captions_from_pdf = None

# 配置日志记录
logging.basicConfig(
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)
file_handler = logging.FileHandler('app.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

# ---- 时长预算常量 ----
TTS_CHARS_PER_SECOND = 4  # 中文 TTS cosyvoice-v1 约 4 字/秒
SUMMARY_BUDGET_RATIO = 0.6  # 总结占比
IMAGE_BUDGET_RATIO = 0.4    # 图片解释占比
MAX_IMAGES_DEFAULT = 5      # 图片筛选默认上限
DURATION_OVERFLOW_RATIO = 1.1  # TTS 后兜底的弹性比例


def compute_word_budget(target_duration: int = 300, num_images: int = MAX_IMAGES_DEFAULT) -> dict:
    """根据目标视频时长计算文字预算。

    Args:
        target_duration: 目标时长（秒）
        num_images: 图片数量（用于计算每张图的预算）

    Returns:
        dict: {"total", "summary", "images", "per_image"}
    """
    total = target_duration * TTS_CHARS_PER_SECOND
    if num_images <= 0:
        return {"total": total, "summary": total, "images": 0, "per_image": 0}
    summary_budget = int(total * SUMMARY_BUDGET_RATIO)
    image_budget = total - summary_budget
    per_image = image_budget // num_images if num_images > 0 else 0
    return {
        "total": total,
        "summary": summary_budget,
        "images": image_budget,
        "per_image": per_image,
    }


def extract_abstract_from_text(raw_text: str, limit: int = 1500) -> str:
    """Heuristic extraction of abstract text from full PDF content."""
    if not raw_text:
        return ""
    text = raw_text.strip()
    if not text:
        return ""

    pattern = re.compile(r'(?:^|\n)\s*(Abstract|ABSTRACT|摘要)[:\s]*')
    match = pattern.search(text)
    abstract = ""
    if match:
        start = match.end()
        remainder = text[start:]
        end_pattern = re.compile(r'(?:^|\n)\s*(Keywords|Index Terms|INTRODUCTION|Introduction|\d+\s+Introduction|1\.|I\.)', re.IGNORECASE)
        end_match = end_pattern.search(remainder)
        abstract = remainder[:end_match.start()] if end_match else remainder
    else:
        abstract = text[:limit]

    lines = [line.strip() for line in abstract.splitlines() if line.strip()]
    condensed = ' '.join(lines)
    return condensed[:limit]


def get_videoclips(paper_text: str = "", demo_url: str = "", download_folder: str = './pic'):
    """Download supplementary demo videos if available and return VideoFileClip list."""
    resolved_url = (demo_url or '').strip()

    if not resolved_url and paper_text:
        try:
            candidate = get_paper_demo_website(paper_text[:1500])
            if candidate:
                resolved_url = candidate.strip()
                logging.info("自动获取到的视频网址: %s", resolved_url)
        except Exception as e:
            logging.error("自动获取视频网址失败: %s", e)

    if not resolved_url:
        logging.info("未提供可用的视频网址，跳过演示视频下载")
        return []

    # 清理旧的 mp4，避免混入历史文件
    try:
        for stale_video in glob.glob(os.path.join(download_folder, '*.mp4')):
            os.remove(stale_video)
    except Exception as e:
        logging.warning("清理旧视频文件失败: %s", e)

    download_success = False
    try:
        download_success = download_videos_files(resolved_url, download_folder=download_folder) or False
    except Exception as e:
        logging.error("下载演示视频失败: %s", e)

    logging.info("发现视频网址 %s，尝试获取视频", resolved_url)
    video_paths = sorted(glob.glob(os.path.join(download_folder, '*.mp4')))
    videos = []
    for video in video_paths:
        try:
            videos.append(VideoFileClip(video))
        except Exception as e:
            logging.warning("加载演示视频 %s 失败: %s", video, e)

    if videos:
        logging.info("提取到 %d 个演示视频", len(videos))
    elif not download_success:
        logging.info("未成功获取任何演示视频")

    return videos

def run_pdf_to_video_pipeline(paper=None,pdf_file_path=None,demowebsite=None,en_title="",prefix="",target_duration=300):
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
    paper_abstract = ""
    if paper and getattr(paper, "abstract", None):
        paper_abstract = paper.abstract.strip()
    if not paper_abstract:
        paper_abstract = extract_abstract_from_text(text)
    images = process_pdf_images(pdf_processor)
    # 尝试使用 qwen-vl 对图片做解释（如果可用）
    try:
        os.makedirs('./cache', exist_ok=True)
        image_agent = ImageAgent()
        # 构建 contexts：从 PDF 提取的 captions 可作为题注
        try:
            from src.extract_caption import extract_captions_from_pdf
        except Exception:
            try:
                from extract_caption import extract_captions_from_pdf
            except Exception:
                extract_captions_from_pdf = None
        contexts = None
        if extract_captions_from_pdf:
            try:
                contexts_dict = extract_captions_from_pdf(pdf_file_path)
                contexts = {}
                for k, v in contexts_dict.items():
                    m = re.search(r"(\d+)", k)
                    if m:
                        idx = int(m.group(1))
                        contexts[idx] = v
            except Exception:
                contexts = None

        # ---- 图片筛选（基于 LLM 打分） ----
        if len(images) > MAX_IMAGES_DEFAULT:
            logging.info(f"图片数量 {len(images)} 超过上限 {MAX_IMAGES_DEFAULT}，进行重要性筛选")
            try:
                captions_for_rating = []
                for img_idx in range(len(images)):
                    cap = contexts.get(img_idx + 1, f"Figure {img_idx + 1}") if contexts else f"Figure {img_idx + 1}"
                    captions_for_rating.append(cap)
                scores = rate_image_importance(captions_for_rating)
                images = select_top_images(images, scores, top_n=MAX_IMAGES_DEFAULT)
                logging.info(f"筛选后保留 {len(images)} 张图片")
            except Exception as e:
                logging.warning(f"图片筛选失败，使用前 {MAX_IMAGES_DEFAULT} 张: {e}")
                images = images[:MAX_IMAGES_DEFAULT]

        # 计算文字预算
        word_budget = compute_word_budget(target_duration, num_images=len(images))
        logging.info(f"文字预算: 总结{word_budget['summary']}字, 图片{word_budget['images']}字 (每张{word_budget['per_image']}字)")

        # 先用LLM总结文章核心内容，然后传递给图像解释
        logging.info("生成文章核心内容总结用于图像解释")
        try:
            paper_core_summary = generate_summary(text, word_budget=word_budget['summary'])
            logging.info("文章核心内容总结生成成功")
        except Exception as e:
            logging.warning(f"生成文章核心内容总结失败: {e}")
            paper_core_summary = text

        explanations = image_agent.explain_images(images, contexts=contexts, paper_abstract=paper_abstract, paper_text=paper_core_summary, per_image_budget=word_budget['per_image'])

        # 为图像解释添加上下文和过渡语句
        logging.info("为图像解释添加上下文和过渡语句")
        try:
            explanations = add_context_to_image_explanations(explanations)
            logging.info("上下文和过渡语句添加成功")
        except Exception as e:
            logging.warning(f"添加上下文和过渡语句失败: {e}")

        with open('./cache/image_explanations.json', 'w', encoding='utf-8') as f:
            json.dump(explanations, f, ensure_ascii=False, indent=2)
        logging.info("已保存图像解释到 ./cache/image_explanations.json")
    except Exception as e:
        logging.warning("调用 image_agent 解释图片失败: %s", e)
        word_budget = compute_word_budget(target_duration, num_images=len(images))

    logging.info("提取到 %d 张图片", len(images))

    videos = get_videoclips(text, demowebsite)
    # 生成摘要（优先使用结构化脚本，回退为普通摘要）
    logging.info("生成结构化视频脚本")
    structured_plan = {}
    try:
        structured_plan = generate_structured_video_plan(text, word_budget=word_budget['summary'])
        if structured_plan:
            summary = structured_plan_to_text(structured_plan)
            title = generate_video_title(text[:1000])
            logging.info("结构化脚本生成成功，使用5段式叙事")
        else:
            raise ValueError("结构化脚本为空")
    except Exception as e:
        logging.warning(f"结构化脚本生成失败，回退为普通摘要: {e}")
        # 复用已生成的 paper_core_summary，避免重复 LLM 调用
        if paper_core_summary and paper_core_summary != text:
            summary = paper_core_summary
            title = generate_video_title(text[:1000])
            logging.info("复用 paper_core_summary 作为摘要，节省 LLM 调用")
        else:
            title, summary = call_llm(text, word_budget=word_budget['summary'])

    # 创建视频（将图像解释传入 VideoCreator，使每张图像可被讲解）
    logging.info("开始创建视频")
    image_explanations = None
    try:
        if os.path.exists('./cache/image_explanations.json'):
            with open('./cache/image_explanations.json', 'r', encoding='utf-8') as f:
                image_explanations = json.load(f)
        else:
            image_explanations = globals().get('explanations', None)
    except Exception:
        image_explanations = globals().get('explanations', None)

    # 将结构化脚本传入 VideoCreator，用于语义匹配图文对应
    video_creator = VideoCreator(images, summary, videos, image_explanations=image_explanations, target_duration=target_duration, structured_plan=structured_plan)
    save_path = f"./output/{title}.mp4"
    video_path = video_creator.create_video(save_path)
    if not video_path or not os.path.exists(video_path):
        raise RuntimeError(f"视频创建失败，输出文件不存在: {save_path}")
    try:
        generate_cover('./pic/1.png', title, video_path.replace(".mp4", ".png"))
    except Exception as e:
        logging.warning("封面生成失败，跳过封面: %s", e)
    logging.info("视频已成功创建，路径为: %s", video_path)
    #convert to absolute path
    video_path = os.path.abspath(video_path)
    logging.info("已完成本地视频生成，主流程不再自动上传。")
    logging.info("程序结束")
    return video_path

def call_llm(text, word_budget: int = 1000):
    with ThreadPoolExecutor() as executor:
        future_title = executor.submit(generate_video_title, text[:1000])
        future_summary = executor.submit(generate_summary, text, word_budget)
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
        # 按文件名中的数字排序
        images.sort(key=lambda x: int(re.findall(r'\d+', os.path.basename(x))[0]) if re.findall(r'\d+', os.path.basename(x)) else 0)
        logging.info(f"图片文件排序后的顺序: {[os.path.basename(img) for img in images]}")
        images = [Image.open(image) for image in images]
    else:
        images = glob.glob('./pic/*.png')
        # 同样进行排序
        images.sort(key=lambda x: int(re.findall(r'\d+', os.path.basename(x))[0]) if re.findall(r'\d+', os.path.basename(x)) else 0)
        logging.info(f"手动提取图片排序后的顺序: {[os.path.basename(img) for img in images]}")
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
        def download_file(url, max_retries=3):
            """下载远程文件并保存到本地，带指数退避重试。"""
            import requests
            import time as _time
            file_name = os.path.join("./cache", "cached_pdf.pdf")
            for attempt in range(max_retries):
                try:
                    response = requests.get(url, timeout=60)
                    response.raise_for_status()
                    with open(file_name, "wb") as f:
                        f.write(response.content)
                    return file_name
                except Exception as e:
                    wait = 2 ** attempt
                    logging.warning(f"PDF 下载失败 (第{attempt+1}次), {wait}s 后重试: {e}")
                    if attempt < max_retries - 1:
                        _time.sleep(wait)
                    else:
                        logging.error(f"PDF 下载最终失败: {e}")
                        raise
        pdf_file_path = download_file(pdf_file_path)
        logging.info(f"下载完成，保存路径: {pdf_file_path}")
    # 检查文件是否存在
    if not os.path.isfile(pdf_file_path):
        logging.info("文件不存在，请检查路径。")
        return -1
    return pdf_file_path

def generate_daily_arxiv_summary(query="cs.RO", date=datetime.datetime.now().strftime(r"%Y-%m-%d"), max_papers=20, output_filename="./output/daily_summary.mp4",long_or_short="short",target_duration=300):
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
    if papers is None:
        raise RuntimeError(f"拉取 arXiv 论文失败，query={query}")
    logging.info(f"找到 {len(papers)} 篇论文,正在筛选...")
    # 过滤日期
    papers = filter_papers_by_date(papers, date)
    # 限制论文数量
    if len(papers) > max_papers:
        papers = papers[:max_papers]
        logging.info(f"限制论文数量为 {max_papers} 篇")
    # 如果没有找到符合条件的论文，抛出异常
    cn_titles=[]
    if not papers:
        raise RuntimeError(f"未找到符合条件的论文，query={query}, date={date}")
    else:
        logging.info(f"找到 {len(papers)} 篇论文")
        logging.info(f"日期: {date}")
        logging.info([paper.title for paper in papers])  # 使用 Paper 数据类的属性

    # 初始化成功生成的视频片段路径列表
    generated_part_paths = []
    processed_papers = []
    origin_titles = []
    summaries = []  # 每篇论文的中文摘要，用于上传平台文案

    # ---- 时长预算 ----
    if len(papers) > 1:
        per_paper_duration = max(30, target_duration // len(papers))
    else:
        per_paper_duration = target_duration
    logging.info(f"目标总时长: {target_duration}秒, 每篇论文目标: {per_paper_duration}秒")

    for paper_idx, paper in enumerate(papers):
        logging.info(f"处理第 {paper_idx + 1} 篇论文: {paper.title}")
        # 下载论文 PDF
        pdf_url = paper.link.replace("abs", "pdf").split('v1')[0]
        pdf_file_path = download_if_remote(pdf_url)
        if not pdf_file_path or pdf_file_path == -1:
            logging.warning(f"无法下载或找到 PDF 文件: {pdf_url}")
            continue
        
        # 创建 PDF 处理器实例
        pdf_processor = PDFProcessor(pdf_file_path)
        
        # 提取文本和图片
        logging.info("提取 PDF 文本和图片")
        text = pdf_processor.extract_text()
        images = process_pdf_images(pdf_processor, cnt=2 if long_or_short == "short" else None)
        paper_abstract = paper.abstract.strip() if getattr(paper, "abstract", None) else extract_abstract_from_text(text)

        # 对提取到的图片尝试做图像解释并保存
        try:
            os.makedirs('./cache', exist_ok=True)
            image_agent = ImageAgent()
            # reuse extract_captions_from_pdf if available
            try:
                contexts_dict = extract_captions_from_pdf(pdf_file_path) if 'extract_captions_from_pdf' in globals() else {}
            except Exception:
                contexts_dict = {}
            contexts = {}
            for k, v in (contexts_dict or {}).items():
                m = re.search(r"(\d+)", k)
                if m:
                    idx = int(m.group(1))
                    contexts[idx] = v

            # ---- 图片筛选（基于 LLM 打分） ----
            if len(images) > MAX_IMAGES_DEFAULT:
                logging.info(f"图片数量 {len(images)} 超过上限 {MAX_IMAGES_DEFAULT}，进行重要性筛选")
                try:
                    captions_for_rating = []
                    for img_idx in range(len(images)):
                        cap = contexts.get(img_idx + 1, f"Figure {img_idx + 1}") if contexts else f"Figure {img_idx + 1}"
                        captions_for_rating.append(cap)
                    scores = rate_image_importance(captions_for_rating)
                    images = select_top_images(images, scores, top_n=MAX_IMAGES_DEFAULT)
                    logging.info(f"筛选后保留 {len(images)} 张图片")
                except Exception as e:
                    logging.warning(f"图片筛选失败，使用前 {MAX_IMAGES_DEFAULT} 张: {e}")
                    images = images[:MAX_IMAGES_DEFAULT]

            # 计算文字预算
            word_budget = compute_word_budget(per_paper_duration, num_images=len(images))
            logging.info(f"文字预算: 总结{word_budget['summary']}字, 图片{word_budget['images']}字 (每张{word_budget['per_image']}字)")

            # 先用LLM总结文章核心内容，然后传递给图像解释
            logging.info("生成文章核心内容总结用于图像解释")
            try:
                paper_core_summary = generate_summary(text, word_budget=word_budget['summary'])
                logging.info("文章核心内容总结生成成功")
            except Exception as e:
                logging.warning(f"生成文章核心内容总结失败: {e}")
                paper_core_summary = text  # 如果失败，使用原始文本

            explanations = image_agent.explain_images(images, contexts=contexts, paper_abstract=paper_abstract, paper_text=paper_core_summary, per_image_budget=word_budget['per_image'])

            # 为图像解释添加上下文和过渡语句
            logging.info("为图像解释添加上下文和过渡语句")
            try:
                explanations = add_context_to_image_explanations(explanations)
                logging.info("上下文和过渡语句添加成功")
            except Exception as e:
                logging.warning(f"添加上下文和过渡语句失败: {e}")

            with open(f'./cache/image_explanations_part_{paper_idx+1}.json', 'w', encoding='utf-8') as f:
                json.dump(explanations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning("图像解释保存失败: %s", e)
        if not images:
            logging.warning(f"未提取到图片，跳过论文: {paper.title}")
            continue
        
        # 生成简短摘要（注入字数预算）
        logging.info("生成摘要")
        # word_budget 可能在 try 块外未定义（图像解释失败时），兜底计算
        if 'word_budget' not in dir():
            word_budget = compute_word_budget(per_paper_duration, num_images=len(images))
        demo_website, origin_title, short_summary, cn_title = call_llm_multithread(
            [
                (get_paper_demo_website, text[:1000]),
                (generate_origin_title, text[:200]),
                (lambda t: generate_short_summary(t, word_budget=word_budget['summary']), f"{text[:5000]} {paper.comments}")
                    if long_or_short == "short"
                    else (lambda t: generate_summary(t, word_budget=word_budget['summary']), paper.comments + text),
                (generate_video_title, text[:200]),
            ]
        )
        
        cn_titles.append(cn_title)
        summaries.append(short_summary or "")
        if not short_summary:
            logging.warning(f"摘要生成失败，跳过论文: {paper.title}")
            continue
        
        # 单篇论文时在循环内生成封面（循环只执行一次）
        # 多篇论文时封面在循环外、合并视频后统一生成，避免每次迭代覆盖同一文件
        if len(papers) == 1:
            try:
                generate_cover('./pic/1.png', cn_title, output_filename.replace(".mp4", ".png"))
            except Exception as e:
                logging.warning("单篇论文封面生成失败，跳过封面: %s", e)
        # 限制图片数量为前两张
        if long_or_short == "short":
            images = images[:3]
            
        # 为当前论文创建独立视频
        logging.info(f"创建第 {paper_idx + 1} 篇论文的视频片段")
        # 传入图像解释以便合成时对每张图片进行解读性讲解
        try:
            image_explanations_part = None
            cache_path = f'./cache/image_explanations_part_{paper_idx+1}.json'
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    image_explanations_part = json.load(f)
        except Exception:
            image_explanations_part = None
        video_creator = VideoCreator(images, short_summary, video_clips=get_videoclips(text, demo_website), image_explanations=image_explanations_part, target_duration=per_paper_duration)
        part_save_path = f"./output/part_{paper_idx + 1}.mp4"
        part_video_path = video_creator.create_video(part_save_path)
        if not part_video_path or not os.path.exists(part_video_path):
            raise RuntimeError(f"视频片段生成失败: {part_save_path}")
        generated_part_paths.append(part_video_path)
        processed_papers.append(paper)
        origin_titles.append(origin_title)
    
    # 如果没有任何可用视频片段，抛出异常
    if not generated_part_paths:
        raise RuntimeError("未生成任何可用视频片段，无法创建视频")

    #如果只有一篇论文，重命名part1为论文名.mp4，并返回统一三元组
    if len(papers) == 1:
        part_video_path = generated_part_paths[0]
        date_str=datetime.datetime.now().strftime(r"%Y-%m-%d")
        title_for_filename = cn_titles[0] if cn_titles else "daily_summary"
        title_for_filename = re.sub(r'[\\/:*?"<>|]', '', title_for_filename).strip() or "daily_summary"
        new_part_video_path = os.path.abspath(f"./output/{date_str}_{title_for_filename}.mp4")
        if os.path.abspath(part_video_path) != new_part_video_path:
            os.replace(part_video_path, new_part_video_path)
        # 同步重命名封面文件，确保 cover_path = video_path.replace(".mp4", ".png") 能找到
        old_cover = os.path.abspath(output_filename.replace(".mp4", ".png"))
        new_cover = new_part_video_path.replace(".mp4", ".png")
        if os.path.exists(old_cover) and os.path.abspath(old_cover) != os.path.abspath(new_cover):
            os.replace(old_cover, new_cover)
            logging.info(f"封面已重命名: {old_cover} -> {new_cover}")
        if not os.path.exists(new_part_video_path):
            raise RuntimeError(f"单篇视频输出失败: {new_part_video_path}")
        logging.info(f"单篇视频已成功生成，路径为: {new_part_video_path}")
        return new_part_video_path, origin_titles, cn_titles, summaries

    # 合并所有论文的视频片段（至少一段）
    video_clips = [VideoFileClip(path) for path in generated_part_paths]
    
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
                duration=video_clips[idx].duration) for idx, _ in enumerate(processed_papers)]
    final_tiles = concatenate_videoclips(title_clips, method="compose")
    final_video = concatenate_videoclips(video_clips, method="compose")
    final_video = CompositeVideoClip([final_video, final_tiles])
    final_video.write_videofile(output_filename, fps=24, codec='libx264', preset='medium')

    # 多篇论文合并完成后，统一生成日报封面（避免循环内反复覆盖）
    try:
        generate_cover('./pic/1.png', "Arxiv具身日报" + str(date), output_filename.replace(".mp4", ".png"))
    except Exception as e:
        logging.warning("日报封面生成失败，跳过封面: %s", e)

    # 转换为绝对路径
    final_video_path = os.path.abspath(output_filename)
    if not os.path.exists(final_video_path):
        raise RuntimeError(f"日报视频输出失败: {final_video_path}")
    logging.info(f"日报视频已成功生成，路径为: {final_video_path}")
    return final_video_path, origin_titles, cn_titles, summaries
