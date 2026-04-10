import os
import json
import datetime
import logging
import argparse

from paperagent_workflow import generate_daily_arxiv_summary
from src.distribution.orchestrator import parse_platforms, upload_generated_content
from src.manim_engine import ManimEngine

logging.basicConfig(
    level=logging.DEBUG,  # 修改为 DEBUG 级别
    format='%(asctime)s - %(levelname)s - %(message)s'
)
file_handler = logging.FileHandler('app.log', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

def parse_args():
    parser = argparse.ArgumentParser(description="Arxiv Paper Processing Script")
    #papername
    parser.add_argument(
        "--filename",
        type=str,
        help="The filename to process, e.g., 'cs.RO' for robotics papers. or a paper tile"
    )
    #output length
    parser.add_argument(
        "--video_length",
        type=str,
        default="long",
        choices=["long", "short"],
        help="Output format: 'long' for detailed summaries, 'short' for brief summaries"
    )
    #output language default is Chinese
    parser.add_argument(
        "--output_language",
        type=str,
        default="zh",
        choices=["zh", "en"],
        help="Output language: 'zh' for Chinese, 'en' for English"
    )
    parser.add_argument(
        "--platforms",
        type=str,
        default="bilibili,xiaohongshu",
        help="Upload platforms, comma-separated: bilibili,xiaohongshu or none"
    )
    parser.add_argument(
        "--target_duration",
        type=int,
        default=300,
        help="Target video duration in seconds (default: 300 = 5min)"
    )

    # Manim 演示生成参数
    parser.add_argument(
        "--manim",
        action="store_true",
        default=False,
        help="Generate Manim animation presentation instead of Ken Burns video"
    )
    parser.add_argument(
        "--manim-tts",
        action="store_true",
        default=False,
        help="Add TTS narration to Manim presentation"
    )
    parser.add_argument(
        "--manim-fmt",
        type=str,
        default="mp4",
        choices=["mp4", "gif"],
        help="Manim output format (default: mp4)"
    )
    parser.add_argument(
        "--manim-quality",
        type=str,
        default="medium",
        choices=["low", "medium", "high"],
        help="Manim render quality: low(480p), medium(720p), high(1080p)"
    )

    return parser.parse_args()


if __name__ == "__main__":

    args= parse_args()
    filename = args.filename
    language = args.output_language
    video_length = args.video_length
    platforms = parse_platforms(args.platforms)
    target_duration = args.target_duration

    manim_mode = getattr(args, "manim", False)
    manim_tts = getattr(args, "manim_tts", False)
    manim_fmt = getattr(args, "manim_fmt", "mp4")
    manim_quality = getattr(args, "manim_quality", "medium")

    try:
        if not filename:
            raise ValueError("参数 --filename 不能为空，例如 --filename cs.RO")
        today=datetime.datetime.now()
        # arXiv 周末不更新，周一需要回退到上周五
        # 周一(0)->回退3天到周五, 周日(6)->回退2天到周五, 周六(5)->回退1天到周五
        weekday = today.weekday()
        if weekday == 0:  # 周一
            delta_days = 3
        elif weekday == 6:  # 周日
            delta_days = 2
        elif weekday == 5:  # 周六
            delta_days = 1
        else:
            delta_days = 1
        target_date = today - datetime.timedelta(days=delta_days)
        yesterday = target_date.strftime(r"%Y-%m-%d")
        today=today.strftime(r"%Y-%m-%d")
        logging.info("今天是%s,查询论文日期是%s", today, yesterday)
        path, titles, cn_titles, summaries, paper_links, project_links = generate_daily_arxiv_summary(
            query=filename,
            max_papers=1,
            date=str(yesterday),
            long_or_short=video_length,
            target_duration=target_duration,
        )
        if not path or not os.path.exists(path):
            raise RuntimeError(f"视频生成失败，输出文件不存在: {path}")
        logging.info("本地视频生成完成: %s", path)

        # ---- Manim 演示模式 ----
        if manim_mode:
            logging.info("进入 Manim 演示生成模式")
            from paperagent_workflow import PDFProcessor
            from src.llm_tools.llm_agent import generate_structured_video_plan

            # 复用已有的 structured_plan 数据（如果 generate_daily_arxiv_summary 生成了的话）
            # 这里需要重新获取论文文本和 structured_plan
            # 尝试从 cache 中读取
            paper_text = ""
            structured_plan = {}
            cache_plan_path = "./cache/structured_plan.json"
            if os.path.exists(cache_plan_path):
                with open(cache_plan_path, "r", encoding="utf-8") as f:
                    structured_plan = json.load(f)
            cache_text_path = "./cache/paper_text.txt"
            if os.path.exists(cache_text_path):
                with open(cache_text_path, "r", encoding="utf-8") as f:
                    paper_text = f.read()

            if not structured_plan:
                logging.warning("未找到缓存的 structured_plan，将从论文重新生成")
                # 尝试从最近的 PDF 中重新提取
                import glob as _glob
                cached_pdf = "./cache/cached_pdf.pdf"
                if os.path.exists(cached_pdf):
                    proc = PDFProcessor(cached_pdf)
                    paper_text = proc.extract_text()
                    structured_plan = generate_structured_video_plan(paper_text)

            if structured_plan and paper_text:
                engine = ManimEngine(
                    paper_text=paper_text,
                    structured_plan=structured_plan,
                    output_dir="./output/manim",
                )
                manim_path = engine.run(
                    tts=manim_tts,
                    quality=manim_quality,
                    fmt=manim_fmt,
                )
                if manim_path:
                    logging.info("Manim 演示视频已生成: %s", manim_path)
                    print(f"Manim output: {manim_path}")
                else:
                    logging.error("Manim 演示视频生成失败")
            else:
                logging.error("无法获取论文数据，Manim 生成跳过")
        logging.info("英文标题列表: %s", titles)
        logging.info("中文标题列表: %s", cn_titles)
        print(path)

        video_path = path
        cover_path = path.replace(".mp4", ".png")
        video_title = cn_titles[0] if len(titles) == 1 else f"Arxiv具身日报{today}"
        video_tags = "人工智能,具身智能,机器人,模仿学习,强化学习,自动驾驶,具身人机"
        video_desc = "\n".join(titles)
        if platforms:
            upload_results = upload_generated_content(
                platforms=platforms,
                video_path=video_path,
                cover_path=cover_path,
                video_title=video_title,
                video_tags=video_tags,
                video_desc=video_desc,
                cn_titles=cn_titles,
                origin_titles=titles,
                summaries=summaries,
                paper_links=paper_links,
                project_links=project_links,
                bilibili_tid=188,
            )
            logging.info("上传结果汇总: %s", upload_results)
        else:
            logging.info("未启用上传平台，跳过自动上传。")
    except Exception as e:
        logging.error("程序运行时发生异常: %s", e)
        raise e
    finally:
        logging.info("程序结束")
        logging.shutdown()
