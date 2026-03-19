import glob
import logging
import os
from typing import Dict, List, Optional

from .bilibili import upload as upload_bilibili
from .xiaohongshu import publish_note as upload_xiaohongshu_note
from .xiaohongshu import publish_video as upload_xiaohongshu_video

logger = logging.getLogger(__name__)

DEFAULT_PLATFORMS = ["bilibili", "xiaohongshu"]
VALID_PLATFORMS = set(DEFAULT_PLATFORMS)

# 小红书默认话题标签
XHS_DEFAULT_TAGS = ["具身智能", "VLA"]


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
    summaries: Optional[List[str]] = None,
) -> str:
    """构建小红书文案：论文原名 + 中文摘要。"""
    lines = []
    # 逐篇论文展示：原名 + 中文摘要
    num_papers = max(len(origin_titles or []), len(cn_titles or []))
    for i in range(num_papers):
        # 论文原名（英文标题）
        if origin_titles and i < len(origin_titles):
            lines.append(f"📄 {origin_titles[i]}")
        # 中文标题
        if cn_titles and i < len(cn_titles):
            lines.append(f"中文标题：{cn_titles[i]}")
        # 中文摘要
        if summaries and i < len(summaries) and summaries[i]:
            lines.append(f"摘要：{summaries[i][:300]}")
        if i < num_papers - 1:
            lines.append("")  # 论文之间空行分隔
    content = "\n".join(lines).strip()
    return content[:1000]


def _build_bilibili_desc(
    video_desc: str,
    cn_titles: Optional[List[str]],
    origin_titles: Optional[List[str]],
    summaries: Optional[List[str]] = None,
) -> str:
    """构建B站视频描述：论文原名 + 中文摘要。"""
    lines = []
    num_papers = max(len(origin_titles or []), len(cn_titles or []))
    for i in range(num_papers):
        if origin_titles and i < len(origin_titles):
            lines.append(f"论文：{origin_titles[i]}")
        if summaries and i < len(summaries) and summaries[i]:
            # B站描述限制较宽，多给一些摘要
            lines.append(f"摘要：{summaries[i][:500]}")
        if i < num_papers - 1:
            lines.append("")
    if not lines:
        # 兜底：使用原始 video_desc
        return video_desc[:2000] if video_desc else ""
    content = "\n".join(lines).strip()
    return content[:2000]


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
    summaries: Optional[List[str]] = None,
    bilibili_tid: int = 188,
    xhs_tags: Optional[List[str]] = None,
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
            bili_desc = _build_bilibili_desc(
                video_desc=video_desc,
                cn_titles=cn_titles,
                origin_titles=origin_titles,
                summaries=summaries,
            )
            bv_id = upload_bilibili(
                video_path=video_path,
                title=video_title,
                tags=video_tags,
                desc=bili_desc,
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
        xhs_title = _build_xhs_title(video_title=video_title, cn_titles=cn_titles)
        xhs_content = _build_xhs_content(
            video_desc=video_desc,
            cn_titles=cn_titles,
            origin_titles=origin_titles,
            summaries=summaries,
        )
        # 合并默认标签和自定义标签（去重保序）
        final_tags = list(XHS_DEFAULT_TAGS)
        if xhs_tags:
            for t in xhs_tags:
                if t not in final_tags:
                    final_tags.append(t)

        # 优先尝试视频上传，失败则降级为图文上传
        video_uploaded = False
        if video_path and os.path.exists(video_path):
            try:
                publish_result = upload_xiaohongshu_video(
                    title=xhs_title,
                    content=xhs_content,
                    video_path=video_path,
                    cover_path=cover_path,
                    tags=final_tags,
                )
                if publish_result:
                    note_id = publish_result.get("note_id") if isinstance(publish_result, dict) else None
                    results["xiaohongshu"] = {"ok": True, "id": note_id, "type": "video"}
                    video_uploaded = True
                else:
                    logger.warning("小红书视频上传返回空结果，降级为图文上传")
            except Exception as exc:
                logger.warning("小红书视频上传失败，降级为图文上传: %s", exc)

        if not video_uploaded:
            try:
                images = _collect_xhs_images(cover_path)
                if not images:
                    raise FileNotFoundError("小红书上传缺少可用图片（封面与 ./pic/*.png 均不存在）")

                publish_result = upload_xiaohongshu_note(
                    title=xhs_title,
                    content=xhs_content,
                    images=images,
                    tags=final_tags,
                )
                if publish_result:
                    note_id = publish_result.get("note_id") if isinstance(publish_result, dict) else None
                    results["xiaohongshu"] = {"ok": True, "id": note_id, "type": "note"}
                else:
                    results["xiaohongshu"] = {"ok": False, "error": "发布返回空结果"}
            except Exception as exc:
                logger.exception("小红书图文上传失败")
                results["xiaohongshu"] = {"ok": False, "error": str(exc)}

    return results
