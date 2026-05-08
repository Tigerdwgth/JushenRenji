"""Blog URL 输入源.

把网页抓成 paperagent_workflow.skip_main_video 期待的 cache 形态:
- ``./cache/paper_text.txt`` (供 LLM 4-scene 脚本)
- ``./pic/{1..N}.png`` (供 manim load_pipeline_images, 命名严格匹配 re 排序)
- ``./cache/blog_clips/{i}.mp4`` (待 main.py ffmpeg concat 追加到最终视频)
- ``./cache/blog_meta.json`` (debug)

老 paper-link (arxiv) 路径完全不动. 复用 ``website_video_pipeline.py``
的 fetch_page_html / SPA Next.js payload 解码套路, 复用 BS4 抓 video/img.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}

DEFAULT_PAGE_TIMEOUT = 30
DEFAULT_ASSET_TIMEOUT = 120
DEFAULT_MAX_IMAGES = 5
DEFAULT_MAX_VIDEOS = 3
ICON_MIN_AREA = 100 * 100  # 小于该面积视为 icon, 过滤
SUPPORTED_VIDEO_EXTS = (".mp4", ".webm")
ARTICLE_TAGS = ("article", "main")
PARAGRAPH_TAGS = ("p", "h1", "h2", "h3", "h4", "li")


class BlogFetchError(RuntimeError):
    """blog 抓取/解析失败 (网络 / SPA / 内容为空 等)."""


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch_page_html(url: str, *, timeout: int = DEFAULT_PAGE_TIMEOUT,
                    _session: Optional[requests.Session] = None) -> str:
    """GET HTML; 失败 raise BlogFetchError."""
    if not url or not url.startswith(("http://", "https://")):
        raise BlogFetchError(f"无效 URL: {url}")
    session = _session or requests.Session()
    try:
        resp = session.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise BlogFetchError(f"获取页面失败 {url}: {exc}") from exc
    if not resp.text or len(resp.text) < 100:
        raise BlogFetchError(f"页面内容过短或为空: {url}")
    return resp.text


def _decode_next_payload(raw_html: str) -> str:
    """复用 website_video_pipeline 套路, 解码 Next.js inline JSON 转义."""
    return raw_html.replace("\\/", "/").replace("\\\"", '"').replace("\\n", "\n")


# ---------------------------------------------------------------------------
# Body text
# ---------------------------------------------------------------------------

def extract_body_text(soup: BeautifulSoup) -> str:
    """优先抓 <article>/<main> 内的段落; fallback 全 <p>."""
    container = None
    for tag in ARTICLE_TAGS:
        container = soup.find(tag)
        if container:
            break
    target = container or soup
    pieces: List[str] = []
    for el in target.find_all(PARAGRAPH_TAGS):
        text = el.get_text(separator=" ", strip=True)
        if text and len(text) > 8:  # 过滤超短 (导航/分类标签)
            pieces.append(text)
    body = "\n\n".join(pieces).strip()
    return body


def extract_meta_field(soup: BeautifulSoup, html: str, *, prop: str = "",
                       name: str = "") -> str:
    """抓 <meta property="..."> 或 <meta name="...">."""
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
    if name:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def extract_title(soup: BeautifulSoup, html: str) -> str:
    """<title> > og:title > <h1>."""
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if t:
            return t
    og = extract_meta_field(soup, html, prop="og:title")
    if og:
        return og
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            return t
    return ""


def extract_published_date(soup: BeautifulSoup, html: str) -> str:
    """article:published_time > <time datetime> > today."""
    ts = extract_meta_field(soup, html, prop="article:published_time")
    if ts:
        return ts[:10]
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag and time_tag.get("datetime"):
        return time_tag["datetime"][:10]
    return datetime.datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Image / Video URL extraction
# ---------------------------------------------------------------------------

def _parse_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(re.findall(r"\d+", str(value))[0])
    except (ValueError, IndexError):
        return None


def extract_image_urls(soup: BeautifulSoup, base_url: str,
                       *, max_n: int = DEFAULT_MAX_IMAGES) -> List[str]:
    """所有 <img>: 按 width*height 排序 (无 attr 退化按 DOM 顺序), 过滤 icon."""
    candidates: List[Tuple[int, int, str]] = []  # (area, dom_order, url)
    for idx, img in enumerate(soup.find_all("img")):
        src = (img.get("src") or "").strip()
        if not src:
            srcset = (img.get("srcset") or "").strip()
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        if not src or src.startswith("data:"):
            continue
        url = urljoin(base_url, src)
        w = _parse_int(img.get("width"))
        h = _parse_int(img.get("height"))
        if w and h and w * h < ICON_MIN_AREA:
            continue  # 小图标
        area = (w or 0) * (h or 0)
        candidates.append((area, idx, url))
    # 有 area 的优先按 area desc; 无 area 的按 dom_order
    with_area = sorted(
        [c for c in candidates if c[0] > 0], key=lambda c: -c[0]
    )
    without_area = sorted(
        [c for c in candidates if c[0] == 0], key=lambda c: c[1]
    )
    ordered = [u for _, _, u in (with_area + without_area)]
    # 去重保序
    seen = set()
    out = []
    for u in ordered:
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= max_n:
            break
    return out


def extract_video_urls(soup: BeautifulSoup, base_url: str,
                       html: str = "",
                       *, max_n: int = DEFAULT_MAX_VIDEOS) -> List[str]:
    """所有 <video>/<source> mp4/webm. SPA 兜底从 inline JSON 抓 mp4 URL."""
    out: List[str] = []
    for video_tag in soup.find_all("video"):
        url = video_tag.get("src", "").strip()
        if not url:
            for src_tag in video_tag.find_all("source"):
                cand = (src_tag.get("src") or "").strip()
                if cand:
                    url = cand
                    break
        if not url:
            continue
        url = urljoin(base_url, url)
        if not url.lower().endswith(SUPPORTED_VIDEO_EXTS):
            continue  # 跳过 m3u8 / 其他 stream 格式
        if url not in out:
            out.append(url)
    # SPA 兜底: 从 inline JSON 抓
    if not out and html:
        decoded = _decode_next_payload(html)
        for pattern in [
            r'<source[^>]+src="(https?://[^"]+\.(?:mp4|webm))"',
            r'"(?:src|videoUrl|video_url|url)":"(https?://[^"]+\.(?:mp4|webm))"',
        ]:
            for m in re.finditer(pattern, decoded):
                u = m.group(1)
                if u not in out:
                    out.append(u)
                if len(out) >= max_n:
                    break
            if len(out) >= max_n:
                break
    return out[:max_n]


# ---------------------------------------------------------------------------
# Asset download
# ---------------------------------------------------------------------------

def _download_binary(url: str, dest: Path,
                     *, timeout: int = DEFAULT_ASSET_TIMEOUT,
                     _session: Optional[requests.Session] = None) -> bool:
    """流式下载二进制到 dest; 成功返回 True. 失败 log + return False (不 raise, 单文件失败不阻断)."""
    session = _session or requests.Session()
    try:
        resp = session.get(url, headers=HEADERS, stream=True, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("[blog] 下载失败 %s: %s", url, exc)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[blog] 写入失败 %s: %s", dest, exc)
        return False
    if dest.stat().st_size == 0:
        logger.warning("[blog] 下载文件为空, 删除 %s", dest)
        try:
            dest.unlink()
        except Exception:
            pass
        return False
    return True


# ---------------------------------------------------------------------------
# Top-level API
# ---------------------------------------------------------------------------

def fetch_blog_assets(url: str,
                      *, timeout: int = DEFAULT_PAGE_TIMEOUT,
                      _session: Optional[requests.Session] = None) -> Dict:
    """抓 blog HTML 解析后返回 metadata + 资源 URL 列表 (不下载)."""
    html = fetch_page_html(url, timeout=timeout, _session=_session)
    soup = BeautifulSoup(html, "html.parser")
    title = extract_title(soup, html)
    description = (
        extract_meta_field(soup, html, prop="og:description")
        or extract_meta_field(soup, html, name="description")
    )
    body_text = extract_body_text(soup)
    if not body_text:
        # SPA / 纯 JS 渲染时 body 抓不到, 用 description 兜底
        body_text = description or title
    if not body_text or len(body_text) < 50:
        raise BlogFetchError(
            f"blog 文本内容过少 (可能是 SPA 渲染), len={len(body_text)}: {url}"
        )
    image_urls = extract_image_urls(soup, url)
    video_urls = extract_video_urls(soup, url, html=html)
    published_date = extract_published_date(soup, html)
    return {
        "page_url": url,
        "title": title or url,
        "description": description,
        "body_text": body_text,
        "image_urls": image_urls,
        "video_urls": video_urls,
        "published_date": published_date,
    }


def materialize_blog_as_paper_cache(
    url: str,
    *,
    cache_dir: str = "./cache",
    pic_dir: str = "./pic",
    clips_dir: str = "./cache/blog_clips",
    max_images: int = DEFAULT_MAX_IMAGES,
    max_videos: int = DEFAULT_MAX_VIDEOS,
    _session: Optional[requests.Session] = None,
    _fetch_fn=None,  # 测试注入: 跳过 fetch_blog_assets, 直接给 dict
) -> Dict:
    """抓 blog → 写 paper_text.txt + ./pic/{i}.png + blog_clips/{i}.mp4.

    返回 dict 含 paper_text / image_paths / clip_paths / meta, 供
    paperagent_workflow.generate_daily_arxiv_summary 的 blog 分支消费.
    """
    if _fetch_fn is not None:
        meta = _fetch_fn(url)
    else:
        meta = fetch_blog_assets(url, _session=_session)

    cache_p = Path(cache_dir)
    pic_p = Path(pic_dir)
    clips_p = Path(clips_dir)
    cache_p.mkdir(parents=True, exist_ok=True)
    pic_p.mkdir(parents=True, exist_ok=True)
    clips_p.mkdir(parents=True, exist_ok=True)

    # 1. paper_text.txt — 头加 title/description, 防止 LLM 拿不到上下文
    paper_text = ""
    if meta.get("title"):
        paper_text += f"标题: {meta['title']}\n\n"
    if meta.get("description"):
        paper_text += f"摘要: {meta['description']}\n\n"
    paper_text += meta.get("body_text", "")
    paper_text_path = cache_p / "paper_text.txt"
    paper_text_path.write_text(paper_text, encoding="utf-8")

    # 2. 下载图片 → ./pic/{1..N}.png (匹配 manim_engine.load_pipeline_images
    #    L498-500 的 re.findall(r"\d+") 排序)
    image_paths: List[str] = []
    image_urls = (meta.get("image_urls") or [])[:max_images]
    for i, img_url in enumerate(image_urls, start=1):
        # 用 .png 后缀(manim_engine 期望), 不论实际格式; 因为后续只是 ManimImageMobject 加载
        # ManimCE 自动识别格式
        dest = pic_p / f"{i}.png"
        if _download_binary(img_url, dest, _session=_session):
            image_paths.append(str(dest))

    # 3. 下载视频 → ./cache/blog_clips/{i}.mp4
    clip_paths: List[str] = []
    video_urls = (meta.get("video_urls") or [])[:max_videos]
    for i, vid_url in enumerate(video_urls):
        dest = clips_p / f"{i}.mp4"
        if _download_binary(vid_url, dest, _session=_session):
            clip_paths.append(str(dest))

    # 4. blog_meta.json (debug + arxiv_id 派生)
    arxiv_id_substitute = "blog-" + hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    meta_record = {
        "url": url,
        "title": meta.get("title"),
        "description": meta.get("description"),
        "published_date": meta.get("published_date"),
        "image_urls": image_urls,
        "video_urls": video_urls,
        "image_paths": image_paths,
        "clip_paths": clip_paths,
        "paper_text_path": str(paper_text_path),
        "arxiv_id_substitute": arxiv_id_substitute,
    }
    (cache_p / "blog_meta.json").write_text(
        json.dumps(meta_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(
        "[blog] 资源就绪: %d 图 %d 视频; paper_text=%d 字; arxiv_id_sub=%s",
        len(image_paths), len(clip_paths), len(paper_text), arxiv_id_substitute,
    )
    return meta_record
