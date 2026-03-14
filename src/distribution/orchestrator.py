import glob
import logging
import os
from typing import Dict, List, Optional

from .bilibili import upload as upload_bilibili
from .xiaohongshu import publish_note as upload_xiaohongshu_note

logger = logging.getLogger(__name__)

DEFAULT_PLATFORMS = ["bilibili", "xiaohongshu"]
VALID_PLATFORMS = set(DEFAULT_PLATFORMS)


def parse_platforms(raw_platforms: Optional[str]) -> List[str]:
    """Parse `--platforms` argument into known platform identifiers."""
    if raw_platforms is None:
        return DEFAULT_PLATFORMS.copy()

    value = raw_platforms.strip().lower()
    if not value or value == "none":
        return []

    results: List[str] = []
    for item in value.split(","):
        platform = item.strip()
        if not platform or platform == "none":
            continue
        if platform in VALID_PLATFORMS:
            if platform not in results:
                results.append(platform)
        else:
            logger.warning("忽略未知平台: %s", platform)
    return results


def _build_xhs_title(video_title: str, cn_titles: Optional[List[str]]) -> str:
    if cn_titles:
        return cn_titles[0][:20]
    if video_title:
        return video_title[:20]
    return "Arxiv论文速览"


def _build_xhs_content(
    video_desc: str,
    cn_titles: Optional[List[str]],
    origin_titles: Optional[List[str]],
) -> str:
    lines = ["今日论文图文速览："]
    if cn_titles:
        lines.append("中文标题：" + "；".join(cn_titles[:5]))
    if origin_titles:
        lines.append("英文标题：" + "；".join(origin_titles[:5]))
    if video_desc:
        lines.append("")
        lines.append(video_desc.strip())
    content = "\n".join(lines).strip()
    return content[:1000]


def _collect_xhs_images(cover_path: Optional[str], max_images: int = 8) -> List[str]:
    images: List[str] = []
    seen = set()

    def add_if_exists(path: str) -> None:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path) and abs_path not in seen:
            images.append(abs_path)
            seen.add(abs_path)

    if cover_path:
        add_if_exists(cover_path)

    for path in sorted(glob.glob("./pic/*.png")):
        add_if_exists(path)
        if len(images) >= max_images:
            break

    return images


def upload_generated_content(
    platforms: List[str],
    video_path: str,
    cover_path: Optional[str],
    video_title: str,
    video_tags: str,
    video_desc: str,
    cn_titles: Optional[List[str]] = None,
    origin_titles: Optional[List[str]] = None,
    bilibili_tid: int = 188,
) -> Dict[str, Dict[str, object]]:
    """
    Upload generated assets to selected platforms.

    Returns a per-platform result summary without raising on single-platform failures.
    """
    results: Dict[str, Dict[str, object]] = {}

    if "bilibili" in platforms:
        try:
            if not video_path or not os.path.exists(video_path):
                raise FileNotFoundError(f"视频文件不存在: {video_path}")
            bv_id = upload_bilibili(
                video_path=video_path,
                title=video_title,
                tags=video_tags,
                desc=video_desc,
                cover_path=cover_path,
                tid=bilibili_tid,
            )
            if bv_id:
                results["bilibili"] = {"ok": True, "id": bv_id}
            else:
                results["bilibili"] = {"ok": False, "error": "上传返回空结果"}
        except Exception as exc:
            logger.exception("B站上传失败")
            results["bilibili"] = {"ok": False, "error": str(exc)}

    if "xiaohongshu" in platforms:
        try:
            images = _collect_xhs_images(cover_path)
            if not images:
                raise FileNotFoundError("小红书上传缺少可用图片（封面与 ./pic/*.png 均不存在）")

            xhs_title = _build_xhs_title(video_title=video_title, cn_titles=cn_titles)
            xhs_content = _build_xhs_content(
                video_desc=video_desc,
                cn_titles=cn_titles,
                origin_titles=origin_titles,
            )

            publish_result = upload_xiaohongshu_note(
                title=xhs_title,
                content=xhs_content,
                images=images,
            )
            if publish_result:
                note_id = publish_result.get("note_id") if isinstance(publish_result, dict) else None
                results["xiaohongshu"] = {"ok": True, "id": note_id}
            else:
                results["xiaohongshu"] = {"ok": False, "error": "发布返回空结果"}
        except Exception as exc:
            logger.exception("小红书图文上传失败")
            results["xiaohongshu"] = {"ok": False, "error": str(exc)}

    return results
