import os
import json
import datetime
import logging
import argparse

from env_setup import apply_network_workarounds, fetch_arxiv_by_id, parse_arxiv_link
apply_network_workarounds()
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
        "--paper-link",
        type=str,
        default=None,
        help="Direct arxiv URL (e.g. https://arxiv.org/abs/2410.11758). Bypasses --filename date guessing.",
    )
    parser.add_argument(
        "--filename",
        type=str,
        help="The filename to process, e.g., 'cs.RO' for robotics papers. or a paper tile"
    )
    parser.add_argument(
        "--discover",
        type=str,
        default=None,
        help="Auto-pick a paper for the given topic via opencode + heuristics. Mutually exclusive with --paper-link / --filename.",
    )
    parser.add_argument(
        "--discover-sources",
        type=str,
        default="hf,arxiv",
        help="Comma-separated discovery sources (default: hf,arxiv).",
    )
    parser.add_argument(
        "--discover-profile",
        type=str,
        default=None,
        help="Path to discovery profile yaml (default: config/discovery_profile.yaml).",
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
        paper_link = getattr(args, "paper_link", None)
        discover_topic = getattr(args, "discover", None)
        if discover_topic and (paper_link or filename):
            raise ValueError("--discover 与 --paper-link / --filename 互斥，请只传一个")
        today_dt = datetime.datetime.now()
        today = today_dt.strftime(r"%Y-%m-%d")
        if discover_topic:
            from src.paper_discovery import discover_top_paper, DiscoveryError
            sources_raw = getattr(args, "discover_sources", "hf,arxiv") or "hf,arxiv"
            sources = [s.strip() for s in sources_raw.split(",") if s.strip()]
            try:
                pick = discover_top_paper(
                    topic=discover_topic,
                    sources=sources,
                    profile_path=getattr(args, "discover_profile", None),
                )
            except DiscoveryError as e:
                raise RuntimeError("[discover] 选题失败: %s" % e)
            paper_link = pick["url"]
            args.paper_link = paper_link
            logging.info("[discover] picked %s (score=%.2f, reason=%s) -> %s",
                         pick["arxiv_id"], float(pick["score"]),
                         (pick["reason"] or "")[:80], paper_link)
        if paper_link:
            arxiv_id = parse_arxiv_link(paper_link)
            meta = fetch_arxiv_by_id(arxiv_id)
            filename = meta["title"]
            yesterday = meta["submitted_date"] or meta["updated_date"]
            logging.info("[paper-link] id=%s title=%s date=%s", arxiv_id, filename[:80], yesterday)
        else:
            if not filename:
                raise ValueError("必须给 --discover <topic> / --paper-link <url> / --filename <query> 之一")
            weekday = today_dt.weekday()
            delta_days = {0: 3, 6: 2, 5: 1}.get(weekday, 1)
            yesterday = (today_dt - datetime.timedelta(days=delta_days)).strftime(r"%Y-%m-%d")
            logging.info("今天是%s, 查询论文日期是%s", today, yesterday)
        path, titles, cn_titles, summaries, paper_links, project_links = generate_daily_arxiv_summary(
            query=filename,
            max_papers=1,
            date=str(yesterday),
            long_or_short=video_length,
            target_duration=target_duration,
            paper_link=paper_link,
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
                _manim_aid = locals().get("arxiv_id") or None
                engine = ManimEngine(
                    paper_text=paper_text,
                    structured_plan=structured_plan,
                    output_dir="./output/manim",
                    arxiv_id=_manim_aid,
                )
                manim_path = engine.run(
                    tts=manim_tts,
                    quality=manim_quality,
                    fmt=manim_fmt,
                )
                if manim_path:
                    logging.info("Manim 演示视频已生成: %s", manim_path)
                    print(f"Manim output: {manim_path}")
                    # 将 Manim 演示拼接到主视频前面
                    try:
                        from moviepy import VideoFileClip, concatenate_videoclips
                        manim_clip = VideoFileClip(manim_path)
                        main_clip = VideoFileClip(path)
                        # 统一分辨率：将 Manim 视频缩放到主视频尺寸
                        if manim_clip.size != main_clip.size:
                            manim_clip = manim_clip.resized(main_clip.size)
                        combined = concatenate_videoclips([manim_clip, main_clip], method="compose")
                        combined_path = path  # 覆盖原视频
                        combined.write_videofile(combined_path, codec="libx264", preset="ultrafast",
                                                 audio_codec="aac", logger=None)
                        manim_clip.close()
                        main_clip.close()
                        combined.close()
                        # faststart remux so moov box is at the front (required for XHS streaming)
                        import subprocess as _sp
                        fs_path = combined_path + ".fs.mp4"
                        _sp.check_call(["/usr/bin/ffmpeg", "-v", "warning", "-y",
                                        "-i", combined_path, "-c", "copy",
                                        "-movflags", "+faststart", fs_path])
                        os.replace(fs_path, combined_path)
                        logging.info("Manim 演示已合并到主视频 (+faststart): %s", combined_path)
                    except Exception as e:
                        logging.warning("Manim 视频合并失败，将单独保留: %s", e)
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
        # B站标题限制80字符，超出则截断
        if len(video_title) > 78:
            video_title = video_title[:77] + "…"
            logging.info("标题截断为80字符以内: %s", video_title)
        video_tags = "人工智能,具身智能,机器人,模仿学习,强化学习,自动驾驶,具身人机"
        video_desc = "\n".join(titles)
        try:
            base_mp4 = os.path.splitext(path)[0]
            with open(base_mp4 + "_meta.json", "w", encoding="utf-8") as _mf:
                import json as _j
                _j.dump({
                    "path": path,
                    "titles": titles,
                    "cn_titles": cn_titles,
                    "summaries": summaries,
                    "paper_links": paper_links,
                    "project_links": project_links,
                }, _mf, ensure_ascii=False, indent=2)
            logging.info("meta saved: %s", base_mp4 + "_meta.json")
        except Exception as _e:
            logging.warning("meta save failed: %s", _e)
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
