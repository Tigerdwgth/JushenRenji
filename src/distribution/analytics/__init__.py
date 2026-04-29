"""创作者中心数据聚合模块.

三平台 (B站 / 小红书 / 抖音) 视频统计数据抓取 + sqlite 存储 + CLI 汇总.

公开 API:
    - fetch_bilibili_stats(bv_id, ...) -> dict
    - fetch_xhs_stats(note_id, xsec_token, ...) -> dict
    - fetch_douyin_stats(account_file, max_posts=20, ...) -> list[dict]
    - upsert_stats(platform, post_id, fetch_date, raw_json=..., **stats) -> None
    - get_recent(platform=None, days=7) -> list[dict]
    - summary_table(platform=None, days=7) -> str

CLI:
    python -m src.distribution.analytics.cli fetch [--platforms ...] [--max-posts N]
    python -m src.distribution.analytics.cli summary [--platforms ...] [--days N]
"""
from .bilibili_stats import fetch_video_stats as fetch_bilibili_stats
from .douyin_stats import fetch_creator_stats as fetch_douyin_stats
from .stats_store import (
    DEFAULT_DB_PATH,
    get_recent,
    init_db,
    summary_table,
    upsert_stats,
)
from .xhs_stats import fetch_note_stats as fetch_xhs_stats

__all__ = [
    "fetch_bilibili_stats",
    "fetch_xhs_stats",
    "fetch_douyin_stats",
    "upsert_stats",
    "get_recent",
    "summary_table",
    "init_db",
    "DEFAULT_DB_PATH",
]
