"""Discovery 数据源子包：HF Daily Papers + arxiv recent。"""
from .hf_papers import fetch_hf_daily
from .arxiv_recent import fetch_arxiv_recent

__all__ = ["fetch_hf_daily", "fetch_arxiv_recent"]
