"""三平台评论拉取与自动回复模块.

子模块:
- replied_db: sqlite 去重存储
- reply_engine: 统一 LLM 回复生成 + 文本清洗
- bilibili_comments / xhs_comments / douyin_comments: 平台 adapter
- cli: 统一入口

调用方式 (paperagent venv):
    python -m src.distribution.comments.cli \
        --platforms bilibili,xiaohongshu,douyin \
        [--max-posts 10] [--dry-run]

设计原则:
1. 默认 dry-run, 不真发回复
2. 每平台日上限: B站 50 / 小红书 15 / 抖音 20
3. 评论之间随机 sleep 1-60s 防风控
4. 跨 venv subprocess 模式 (xhs/douyin) 与 distribution/douyin.py 同款
"""
from . import replied_db, reply_engine  # noqa: F401
