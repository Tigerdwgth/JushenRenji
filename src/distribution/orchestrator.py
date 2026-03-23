import glob
import logging
import os
from typing import Dict, List, Optional

try:
    from .bilibili import upload as _upload_bilibili_impl
    _BILIBILI_IMPORT_ERROR = None
except Exception as exc:
    _upload_bilibili_impl = None
    _BILIBILI_IMPORT_ERROR = exc

try:
    from .xiaohongshu import publish_note as _upload_xiaohongshu_note_impl
    from .xiaohongshu import publish_video as _upload_xiaohongshu_video_impl
    _XHS_IMPORT_ERROR = None
except Exception as exc:
    _upload_xiaohongshu_note_impl = None
    _upload_xiaohongshu_video_impl = None
    _XHS_IMPORT_ERROR = exc

logger = logging.getLogger(__name__)

DEFAULT_PLATFORMS = ["bilibili", "xiaohongshu"]
VALID_PLATFORMS = set(DEFAULT_PLATFORMS)

# 小红书默认话题标签
XHS_DEFAULT_TAGS = ["具身智能", "VLA"]
XHS_CONTENT_LIMIT = 300
BILIBILI_DESC_LIMIT = 250
XHS_SUMMARY_LIMIT = 90
BILIBILI_SUMMARY_LIMIT = 60


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


def _clean_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _truncate_text(value: str, max_len: int) -> str:
    text = _clean_text(value)
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len == 1:
        return text[:1]
    return text[: max_len - 1].rstrip() + "…"


def _append_line_with_limit(lines: List[str], line: str, total_limit: int) -> bool:
    if not line:
        return True
    candidate = "\n".join(lines + [line]).strip()
    if len(candidate) <= total_limit:
        lines.append(line)
        return True
    return False


def _build_compact_description(
    *,
    video_desc: str,
    cn_titles: Optional[List[str]],
    origin_titles: Optional[List[str]],
    paper_links: Optional[List[str]],
    project_links: Optional[List[str]],
    summaries: Optional[List[str]],
    total_limit: int,
    summary_limit: int,
    include_cn_titles: bool = False,
) -> str:
    lines: List[str] = []
    num_papers = max(
        len(cn_titles or []),
        len(origin_titles or []),
        len(paper_links or []),
        len(project_links or []),
        len(summaries or []),
    )

    for i in range(num_papers):
        cn_title = _clean_text(cn_titles[i]) if cn_titles and i < len(cn_titles) else ""
        title = _clean_text(origin_titles[i]) if origin_titles and i < len(origin_titles) else ""
        paper_link = _clean_text(paper_links[i]) if paper_links and i < len(paper_links) else ""
        project_link = _clean_text(project_links[i]) if project_links and i < len(project_links) else ""
        summary = _clean_text(summaries[i]) if summaries and i < len(summaries) else ""

        for line in (
            f"中文标题：{cn_title}" if include_cn_titles and cn_title else "",
            f"论文标题：{title}" if title else "",
            f"论文链接：{paper_link}" if paper_link else "",
            f"项目链接：{project_link}" if project_link else "",
        ):
            if not _append_line_with_limit(lines, line, total_limit):
                return "\n".join(lines).strip()

        if summary:
            existing = "\n".join(lines).strip()
            remaining = total_limit - len(existing) - (1 if existing else 0) - len("摘要：")
            summary_text = _truncate_text(summary, min(summary_limit, remaining))
            if summary_text and not _append_line_with_limit(lines, f"摘要：{summary_text}", total_limit):
                return "\n".join(lines).strip()

    content = "\n".join(lines).strip()
    if content:
        return content
    return _truncate_text(video_desc, total_limit)


def _build_xhs_content(
    video_desc: str,
    cn_titles: Optional[List[str]],
    origin_titles: Optional[List[str]],
    summaries: Optional[List[str]] = None,
    paper_links: Optional[List[str]] = None,
    project_links: Optional[List[str]] = None,
) -> str:
    """构建小红书文案：仅保留论文名，且控制为精简简介。"""
    return _build_compact_description(
        video_desc=video_desc,
        cn_titles=cn_titles,
        origin_titles=origin_titles,
        paper_links=paper_links,
        project_links=project_links,
        summaries=summaries,
        total_limit=XHS_CONTENT_LIMIT,
        summary_limit=XHS_SUMMARY_LIMIT,
        include_cn_titles=True,
    )


def _build_bilibili_desc(
    video_desc: str,
    cn_titles: Optional[List[str]],
    origin_titles: Optional[List[str]],
    summaries: Optional[List[str]] = None,
    paper_links: Optional[List[str]] = None,
    project_links: Optional[List[str]] = None,
) -> str:
    """构建B站视频简介：仅保留论文名，并压缩为上传限制内。"""
    return _build_compact_description(
        video_desc=video_desc,
        cn_titles=cn_titles,
        origin_titles=origin_titles,
        paper_links=paper_links,
        project_links=project_links,
        summaries=summaries,
        total_limit=BILIBILI_DESC_LIMIT,
        summary_limit=BILIBILI_SUMMARY_LIMIT,
    )


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
    paper_links: Optional[List[str]] = None,
    project_links: Optional[List[str]] = None,
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
                paper_links=paper_links,
                project_links=project_links,
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
            paper_links=paper_links,
            project_links=project_links,
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
