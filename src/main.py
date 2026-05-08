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
    parser.add_argument(
        "--blog-url",
        type=str,
        default=None,
        help="Generic blog/article URL (e.g. https://www.genesis.ai/blog/...). "
             "Mutually exclusive with --paper-link / --filename / --discover. "
             "Pipeline 抓取 HTML 文本 + 图片 + 视频, 嵌入最终 mp4.",
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
        blog_url = getattr(args, "blog_url", None)
        # 四选一互斥
        _given = sum(1 for x in (paper_link, filename, discover_topic, blog_url) if x)
        if _given > 1:
            raise ValueError(
                "--paper-link / --filename / --discover / --blog-url 互斥, 请只传一个"
            )
        if blog_url:
            # blog 模式: 没 LaTeX 源码 → 关掉 figure_grounded, 走 caption-only baseline
            os.environ["PAPERIFY_DISABLE_FIGURE_GROUNDED"] = "1"
            # 防御: blog 模式开头主动删 cached_pdf.pdf, 防 paper-link 残留误触发兜底
            try:
                if os.path.exists("./cache/cached_pdf.pdf"):
                    os.remove("./cache/cached_pdf.pdf")
            except Exception as _e:
                logging.warning("[blog-url] 清理旧 cached_pdf.pdf 失败: %s", _e)
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
        elif blog_url:
            # blog 模式: 提前抓 metadata 用于 filename / yesterday;
            # generate_daily_arxiv_summary 内部还会 materialize 写 cache.
            from src.blog_pipeline import fetch_blog_assets
            _blog_meta = fetch_blog_assets(blog_url)
            filename = _blog_meta["title"]
            yesterday = _blog_meta.get("published_date") or today
            arxiv_id = "blog-" + __import__("hashlib").md5(blog_url.encode()).hexdigest()[:8]
            logging.info("[blog-url] title=%s date=%s images=%d videos=%d",
                         (filename or "")[:80], yesterday,
                         len(_blog_meta.get("image_urls", [])),
                         len(_blog_meta.get("video_urls", [])))
        else:
            if not filename:
                raise ValueError("必须给 --discover <topic> / --paper-link <url> / --filename <query> / --blog-url <url> 之一")
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
            skip_main_video=manim_mode,
            blog_url=blog_url,
        )
        if manim_mode:
            # manim-only 模式: path 此时是预定路径还不存在, 由后续 ManimEngine 写入
            logging.info("已跳过主视频合成 (manim-only 模式), 预定路径: %s", path)
        else:
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
                    # 把 Gemini cover.png prepend 成视频前 2 秒静止帧 (含静音音轨),
                    # 再 concat manim_path. 这样平台 (小红书/抖音) 自动取首帧时
                    # 拿到的就是设计封面, 而不是 manim 第一帧的淡入黑屏.
                    # B 站仍走显式 cover_path 上传, 不依赖此处.
                    try:
                        import subprocess as _sp
                        _proj_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
                        os.makedirs(_proj_cache, exist_ok=True)
                        _cover_path = path.replace(".mp4", ".png")
                        _final_tmp = os.path.join(_proj_cache, os.path.basename(path) + ".cover_prepend.mp4")
                        if os.path.exists(_cover_path):
                            # cover.png + 静音 → 2s segment + concat manim_path → final
                            # concat filter 会重编码 (~5-10s 额外耗时), 但保证 codec 一致
                            _cover_seg = os.path.join(_proj_cache, "_cover_seg.mp4")
                            _sp.check_call([
                                "/usr/bin/ffmpeg", "-v", "warning", "-y",
                                "-loop", "1", "-framerate", "30", "-i", _cover_path,
                                "-f", "lavfi", "-t", "0.04", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                "-frames:v", "1", "-c:a", "aac", "-shortest", _cover_seg,
                            ])
                            _sp.check_call([
                                "/usr/bin/ffmpeg", "-v", "warning", "-y",
                                "-i", _cover_seg, "-i", manim_path,
                                "-filter_complex",
                                "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                                "-map", "[v]", "-map", "[a]",
                                "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                                "-movflags", "+faststart", _final_tmp,
                            ])
                            os.replace(_final_tmp, path)
                            try:
                                os.remove(_cover_seg)
                            except Exception:
                                pass
                            logging.info("Cover prepend (1 frame) + Manim 拼接成功: %s", path)
                        # blog 模式: 在 path 末尾追加 ./cache/blog_clips/*.mp4 (单 clip ≤30s, 总 ≤90s)
                        try:
                            import glob as _gl
                            _clip_files = sorted(
                                _gl.glob("./cache/blog_clips/*.mp4"),
                                key=lambda p: int(__import__("re").findall(r"\d+", os.path.basename(p))[0])
                                if __import__("re").findall(r"\d+", os.path.basename(p)) else 0,
                            )
                            if _clip_files:
                                _budget_remaining = 90  # 秒
                                _normalized_clips = []
                                for _ci, _clip in enumerate(_clip_files):
                                    if _budget_remaining <= 5:
                                        break
                                    _per_clip = min(30, _budget_remaining)
                                    _norm = os.path.join(_proj_cache, f"_blog_clip_norm_{_ci}.mp4")
                                    try:
                                        _sp.check_call([
                                            "/usr/bin/ffmpeg", "-v", "warning", "-y",
                                            "-t", str(_per_clip), "-i", _clip,
                                            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                                                   "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                                            "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                            "-c:a", "aac", "-ar", "44100", "-ac", "2",
                                            "-shortest", _norm,
                                        ])
                                        _normalized_clips.append(_norm)
                                        _budget_remaining -= _per_clip
                                    except Exception as _norm_e:
                                        logging.warning("blog clip 归一化失败 %s: %s", _clip, _norm_e)
                                if _normalized_clips:
                                    # concat path + 所有 normalized clips
                                    _inputs = ["-i", path]
                                    for _c in _normalized_clips:
                                        _inputs.extend(["-i", _c])
                                    _n = 1 + len(_normalized_clips)
                                    _filter = "".join(f"[{i}:v][{i}:a]" for i in range(_n)) + f"concat=n={_n}:v=1:a=1[v][a]"
                                    _final2 = os.path.join(_proj_cache, os.path.basename(path) + ".with_blog.mp4")
                                    _sp.check_call([
                                        "/usr/bin/ffmpeg", "-v", "warning", "-y",
                                        *_inputs, "-filter_complex", _filter,
                                        "-map", "[v]", "-map", "[a]",
                                        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                                        "-movflags", "+faststart", _final2,
                                    ])
                                    os.replace(_final2, path)
                                    for _c in _normalized_clips:
                                        try: os.remove(_c)
                                        except Exception: pass
                                    logging.info("追加 blog clips %d 段, 共 %ds: %s",
                                                 len(_normalized_clips), 90 - _budget_remaining, path)
                        except Exception as _blog_append_e:
                            logging.warning("blog clips append 失败 (主视频不受影响): %s", _blog_append_e)
                        else:
                            # 无 Gemini 封面: 退化为原 ffmpeg copy + faststart (manim 直出)
                            logging.warning("未找到 Gemini 封面 %s, 跳过 prepend, 直接 copy manim", _cover_path)
                            _sp.check_call(["/usr/bin/ffmpeg", "-v", "warning", "-y",
                                            "-i", manim_path, "-c", "copy",
                                            "-movflags", "+faststart", _final_tmp])
                            os.replace(_final_tmp, path)
                    except Exception as e:
                        logging.warning("Cover prepend 失败, 退化原始 manim copy: %s", e)
                        try:
                            import subprocess as _sp_fb
                            _sp_fb.check_call(["/usr/bin/ffmpeg", "-v", "warning", "-y",
                                               "-i", manim_path, "-c", "copy",
                                               "-movflags", "+faststart", path])
                        except Exception as e2:
                            logging.error("Manim 替换主视频失败 (无可用兜底): %s", e2)
                else:
                    logging.error("Manim 演示视频生成失败")
            else:
                logging.error("无法获取论文数据，Manim 生成跳过")
        logging.info("英文标题列表: %s", titles)
        logging.info("中文标题列表: %s", cn_titles)
        print(path)

        video_path = path
        cover_path = path.replace(".mp4", ".png")
        # 若没有显式封面 (manim-only 模式不会产 cover), 从主视频抽首帧 (跳 0.5s 避开 fade-in 黑屏)
        if not os.path.exists(cover_path) and os.path.exists(video_path):
            try:
                import subprocess as _cov_sp
                _cov_sp.check_call([
                    "/usr/bin/ffmpeg", "-y", "-v", "warning",
                    "-ss", "0.5", "-i", video_path, "-vframes", "1", cover_path,
                ])
                logging.warning("未找到 Gemini/DashScope 设计封面, 降级为 ffmpeg 抽首帧: %s", cover_path)
            except Exception as _cov_e:
                logging.warning("首帧封面抽取失败 (上传将不带封面): %s", _cov_e)
                if os.path.exists(cover_path):
                    try:
                        os.remove(cover_path)
                    except Exception:
                        pass
        video_title = cn_titles[0] if len(titles) == 1 else f"Arxiv具身日报{today}"
        # B站标题限制80字符，超出则截断
        if len(video_title) > 78:
            video_title = video_title[:77] + "…"
            logging.info("标题截断为80字符以内: %s", video_title)
        # 关键词改为每篇论文 LLM 动态生成（多论文日报合并去重）
        tags_per_platform = None
        try:
            from src.llm_tools.llm_agent import generate_video_tags, merge_video_tags
            tag_dicts = []
            for _i, _en_t in enumerate(titles):
                tag_dicts.append(generate_video_tags(
                    cn_title=cn_titles[_i] if _i < len(cn_titles) else "",
                    en_title=_en_t,
                    abstract=summaries[_i] if _i < len(summaries) else "",
                ))
            tags_per_platform = merge_video_tags(tag_dicts) if len(tag_dicts) > 1 else (tag_dicts[0] if tag_dicts else None)
            logging.info("生成关键词: %s", tags_per_platform)
        except Exception as _tag_e:
            logging.warning("关键词动态生成失败, 走 orchestrator 兜底: %s", _tag_e)
        # B站需要 str (逗号分隔), 优先用动态 tags 的 bilibili 列表
        if tags_per_platform and tags_per_platform.get("bilibili"):
            video_tags = ",".join(tags_per_platform["bilibili"])
        else:
            video_tags = "具身智能,VLA,机器人,AI论文,大模型,前沿科技,arXiv"
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
                tags_per_platform=tags_per_platform,
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
