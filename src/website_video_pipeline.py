import argparse
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from src.config import OUTPUT_DIR
    from src.distribution.orchestrator import parse_platforms
    from src.llm_tools.llm_agent import generate_video_title
    from src.utils.title_cleaner import sanitize_generated_title
except ImportError:
    from config import OUTPUT_DIR
    from distribution.orchestrator import parse_platforms
    try:
        from llm_tools.llm_agent import generate_video_title
    except ImportError:
        generate_video_title = None
    from utils.title_cleaner import sanitize_generated_title

try:
    from src.distribution.bilibili import upload as _upload_bilibili_impl
    _BILIBILI_IMPORT_ERROR = None
except Exception as exc:
    _upload_bilibili_impl = None
    _BILIBILI_IMPORT_ERROR = exc

try:
    from src.distribution.xiaohongshu import (
        publish_note as _upload_xiaohongshu_note_impl,
        publish_video as _upload_xiaohongshu_video_impl,
    )
    _XHS_IMPORT_ERROR = None
except Exception as exc:
    _upload_xiaohongshu_note_impl = None
    _upload_xiaohongshu_video_impl = None
    _XHS_IMPORT_ERROR = exc


logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}

DEFAULT_TAGS = ["机器人", "具身智能", "Physical Intelligence"]
TITLE_KEYWORD_MAP = [
    ("precise manipulation", "精准操作"),
    ("dexterous manipulation", "灵巧操作"),
    ("efficient online rl", "在线强化学习"),
    ("online reinforcement learning", "在线强化学习"),
    ("reinforcement learning", "强化学习"),
    ("online rl", "在线强化学习"),
    ("rl token", "RL Token"),
    ("vision-language-action", "视觉语言动作"),
    ("vla", "VLA"),
    ("robot", "机器人"),
]


def upload_bilibili(*args, **kwargs):
    if _upload_bilibili_impl is None:
        raise RuntimeError("B站上传依赖未安装") from _BILIBILI_IMPORT_ERROR
    return _upload_bilibili_impl(*args, **kwargs)


def upload_xiaohongshu_note(*args, **kwargs):
    if _upload_xiaohongshu_note_impl is None:
        raise RuntimeError("小红书上传依赖未安装") from _XHS_IMPORT_ERROR
    return _upload_xiaohongshu_note_impl(*args, **kwargs)


def upload_xiaohongshu_video(*args, **kwargs):
    if _upload_xiaohongshu_video_impl is None:
        raise RuntimeError("小红书上传依赖未安装") from _XHS_IMPORT_ERROR
    return _upload_xiaohongshu_video_impl(*args, **kwargs)


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "website-video"


def _contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _decode_next_payload(raw_html: str) -> str:
    return raw_html.replace("\\/", "/").replace("\\\"", '"').replace("\\n", "\n")


def fetch_page_html(url: str, timeout: int = 30) -> str:
    session = requests.Session()
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def extract_page_metadata(html: str, page_url: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    decoded = _decode_next_payload(html)

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        title = title_match.group(1).strip() if title_match else ""

    description = ""
    desc_tag = soup.find("meta", attrs={"name": "description"})
    if desc_tag:
        description = (desc_tag.get("content") or "").strip()

    cover_url = None
    cover_tag = soup.find("meta", attrs={"property": "og:image"})
    if cover_tag and cover_tag.get("content"):
        cover_url = urljoin(page_url, cover_tag["content"].strip())

    paper_url = None
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if href.lower().endswith(".pdf"):
            paper_url = urljoin(page_url, href)
            break

    video_url = None
    patterns = [
        r'\$L17.*?"src":"(https://[^"]+\.(?:mp4|webm|m3u8))"',
        r'<source src="(https://[^"]+\.(?:mp4|webm|m3u8))"',
        r'"src":"(https://[^"]+\.(?:mp4|webm|m3u8))"',
    ]
    for pattern in patterns:
        match = re.search(pattern, decoded, re.DOTALL)
        if match:
            video_url = match.group(1)
            break

    if not video_url:
        raise RuntimeError(f"未能从页面中解析出顶部主视频: {page_url}")

    return {
        "page_url": page_url,
        "title": title,
        "description": description,
        "cover_url": cover_url,
        "paper_url": paper_url,
        "video_url": video_url,
    }


def _guess_extension(url: str, content_type: str = "") -> str:
    path_ext = Path(urlparse(url).path).suffix
    if path_ext:
        return path_ext
    ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    return ext or ".bin"


def download_asset(url: str, dest_dir: Path, filename_stem: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    response = session.get(url, headers=HEADERS, stream=True, timeout=120)
    response.raise_for_status()

    ext = _guess_extension(url, response.headers.get("content-type", ""))
    output_path = dest_dir / f"{_sanitize_filename(filename_stem)}{ext}"

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 512):
            if chunk:
                f.write(chunk)

    if output_path.stat().st_size == 0:
        raise RuntimeError(f"下载文件为空: {url}")

    return output_path


def _build_bilibili_desc(metadata: Dict[str, Optional[str]]) -> str:
    lines = []
    if metadata.get("cn_title"):
        lines.append(f"中文标题：{metadata['cn_title'].strip()}")
    if metadata.get("title"):
        lines.append(f"论文标题：{metadata['title'].strip()}")
    return "\n".join(line for line in lines if line).strip()[:2000]


def _build_xhs_content(metadata: Dict[str, Optional[str]]) -> str:
    lines = []
    if metadata.get("cn_title"):
        lines.append(f"中文标题：{metadata['cn_title'].strip()}")
    if metadata.get("title"):
        lines.append(f"论文标题：{metadata['title'].strip()}")
    return "\n".join(line for line in lines if line).strip()[:1000]


def _build_keyword_fallback_title(metadata: Dict[str, Optional[str]]) -> str:
    source_text = " ".join(
        part.strip() for part in [metadata.get("title") or "", metadata.get("description") or ""] if part
    ).lower()
    keywords: List[str] = []
    for phrase, cn_text in TITLE_KEYWORD_MAP:
        if phrase in source_text and cn_text not in keywords:
            keywords.append(cn_text)

    if len(keywords) >= 2:
        return sanitize_generated_title(f"{keywords[0]}与{keywords[1]}")
    if len(keywords) == 1:
        return sanitize_generated_title(f"{keywords[0]}论文解读")
    return "研究网页视频解读"


def build_publish_title(metadata: Dict[str, Optional[str]]) -> str:
    original_title = (metadata.get("title") or "").strip()
    if _contains_chinese(original_title):
        return original_title[:80]

    if callable(generate_video_title):
        llm_input = "\n".join(
            line
            for line in [
                f"网页标题: {original_title}",
                f"页面描述: {(metadata.get('description') or '').strip()}",
                f"论文链接: {(metadata.get('paper_url') or '').strip()}",
            ]
            if line.strip()
        )
        try:
            candidate = _sanitize_filename((generate_video_title(llm_input) or "").strip())
            candidate = sanitize_generated_title(candidate)
            if _contains_chinese(candidate):
                return candidate[:80]
        except Exception as exc:
            logger.warning("生成中文标题失败，回退关键词标题: %s", exc)

    return _build_keyword_fallback_title(metadata)


def upload_external_video(
    *,
    platforms: List[str],
    video_path: str,
    cover_path: Optional[str],
    metadata: Dict[str, Optional[str]],
    tags: Optional[List[str]] = None,
) -> Dict[str, Dict[str, object]]:
    title = build_publish_title(metadata)
    metadata.setdefault("cn_title", title)
    desc = _build_bilibili_desc(metadata)
    xhs_content = _build_xhs_content(metadata)
    tag_list = tags or DEFAULT_TAGS
    results: Dict[str, Dict[str, object]] = {}

    if "bilibili" in platforms:
        try:
            bvid = upload_bilibili(
                video_path=video_path,
                title=title,
                tags=",".join(tag_list),
                desc=desc,
                cover_path=cover_path,
                tid=188,
            )
            results["bilibili"] = {"ok": bool(bvid), "id": bvid}
        except Exception as exc:
            logger.exception("B站上传失败")
            results["bilibili"] = {"ok": False, "error": str(exc)}

    if "xiaohongshu" in platforms:
        try:
            publish_result = upload_xiaohongshu_video(
                title=title[:20],
                content=xhs_content,
                video_path=video_path,
                cover_path=cover_path,
                tags=tag_list,
            )
            if publish_result:
                note_id = publish_result.get("note_id") if isinstance(publish_result, dict) else None
                results["xiaohongshu"] = {"ok": True, "id": note_id, "type": "video"}
            else:
                raise RuntimeError("小红书视频上传返回空结果")
        except Exception as exc:
            logger.warning("小红书视频上传失败，尝试降级为图文: %s", exc)
            try:
                if not cover_path or not os.path.exists(cover_path):
                    raise RuntimeError("缺少可用于图文降级的封面")
                publish_result = upload_xiaohongshu_note(
                    title=title[:20],
                    content=xhs_content,
                    images=[cover_path],
                    tags=tag_list,
                )
                if publish_result:
                    note_id = publish_result.get("note_id") if isinstance(publish_result, dict) else None
                    results["xiaohongshu"] = {"ok": True, "id": note_id, "type": "note"}
                else:
                    results["xiaohongshu"] = {"ok": False, "error": "小红书图文上传返回空结果"}
            except Exception as inner_exc:
                logger.exception("小红书上传失败")
                results["xiaohongshu"] = {"ok": False, "error": str(inner_exc)}

    return results


def forward_website_video(
    *,
    url: str,
    platforms: Optional[List[str]] = None,
    work_dir: Optional[Path] = None,
) -> Dict[str, object]:
    html = fetch_page_html(url)
    metadata = extract_page_metadata(html, page_url=url)

    work_root = Path(work_dir or OUTPUT_DIR)
    stem = _sanitize_filename(metadata.get("title") or "website-video")
    video_path = download_asset(metadata["video_url"], work_root, stem)
    cover_path = None
    if metadata.get("cover_url"):
        cover_path = download_asset(metadata["cover_url"], work_root, f"{stem}_cover")

    selected_platforms = ["bilibili", "xiaohongshu"] if platforms is None else platforms
    upload_result = upload_external_video(
        platforms=selected_platforms,
        video_path=str(video_path),
        cover_path=str(cover_path) if cover_path else None,
        metadata=metadata,
    )
    return {
        "metadata": metadata,
        "video_path": str(video_path),
        "cover_path": str(cover_path) if cover_path else None,
        "upload": upload_result,
    }


def parse_args(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="Forward website hero video to publishing platforms")
    parser.add_argument("--url", type=str, required=True, help="Research page URL")
    parser.add_argument(
        "--platforms",
        type=str,
        default="bilibili,xiaohongshu",
        help="Upload platforms, comma-separated: bilibili,xiaohongshu or none",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> Dict[str, object]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = parse_args(argv)
    result = forward_website_video(
        url=args.url,
        platforms=parse_platforms(args.platforms),
    )
    logger.info("网页视频转发结果: %s", result["upload"])
    return result


if __name__ == "__main__":
    main()
