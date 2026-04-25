"""``--discover`` 前置选题模块。

入口 ``discover_top_paper`` 完成：候选拉取（HF + arxiv）、硬过滤、去重、
opencode 主路打分（kill switch / 失败均自动回退）、启发式备选、D1 fallback。

设计原则：
- 与 manim_engine 解耦，不复用 ``ManimEngine._opencode_generate``，但 subprocess
  pattern 抄一份独立函数 ``_run_opencode_with_pipe``。
- 失败优雅降级：网络/解析/opencode 失败均不抛，主流程在最后一刻才抛
  ``DiscoveryError``。
- 缓存 append-only：``cache/published_papers.json`` 记录已出片论文，去重用。

关键约束（与 spec 同步）:
- D1: 候选全过滤掉 → 回退 "arxiv ``fallback_arxiv_query`` 过去 7 天第 1 条"，warning 日志
- D2: ``--discover`` 与 ``--filename`` / ``--paper-link`` 互斥（main.py 强制）
- D3: 去重 = arxiv_id 严格 + ``difflib.SequenceMatcher.ratio() >= 0.85`` 模糊
- D4: opencode 失败自动降级本地启发式
"""
from __future__ import annotations

import datetime
import difflib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# =====================================================================
# 公共数据结构
# =====================================================================

@dataclass
class Candidate:
    arxiv_id: str
    title: str
    abstract: str
    url: str
    submitted_date: str  # YYYY-MM-DD
    upvotes: int
    github_repo: Optional[str]
    project_page: Optional[str]
    source: str  # "hf" / "arxiv"


class DiscoveryError(Exception):
    """选题完全失败时抛出（含 D1 fallback 也失败的情况）。"""


# =====================================================================
# 路径 helpers
# =====================================================================

def _project_root() -> str:
    """src/paper_discovery.py 上两级 = 项目根。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _state_path() -> str:
    """cache/published_papers.json 绝对路径。"""
    return os.path.join(_project_root(), "cache", "published_papers.json")


def _candidates_snapshot_path() -> str:
    return os.path.join(_project_root(), "cache", "discovery_candidates.json")


def _default_profile_path() -> str:
    return os.path.join(_project_root(), "config", "discovery_profile.yaml")


# =====================================================================
# Profile 加载
# =====================================================================

_PROFILE_DEFAULTS = {
    "topics": ["embodied", "VLA", "imitation learning", "robot", "manipulation", "world model"],
    "exclude_keywords": ["A Survey on", "A Survey of", "Benchmark for", "Benchmarking", "Evaluation of"],
    "require_github": True,
    "weights": {
        "topic_match": 3,
        "recent_7d": 2,
        "has_github": 2,
        "has_project_page": 2,
        "upvotes_bonus": 0.1,
        "author_boost": 1,
    },
    "author_boost_list": ["Pieter Abbeel", "Sergey Levine", "Chelsea Finn", "Jitendra Malik"],
    "min_score": 3.0,
    "opencode_model": "",
    "fallback_arxiv_query": "cs.RO",
}


def _load_profile(path: Optional[str] = None) -> dict:
    """读取 yaml profile，缺失字段回退到默认值。"""
    import yaml

    p = path or _default_profile_path()
    data = {}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:  # noqa: BLE001
            logger.warning("[discovery] load profile failed: %s, fallback default", e)
            data = {}
    else:
        logger.warning("[discovery] profile not found at %s, using defaults", p)

    # merge defaults（浅 merge，weights 子字典做一层 merge）
    out = dict(_PROFILE_DEFAULTS)
    out.update({k: v for k, v in data.items() if v is not None})
    if "weights" in data and isinstance(data["weights"], dict):
        weights = dict(_PROFILE_DEFAULTS["weights"])
        weights.update(data["weights"])
        out["weights"] = weights
    return out


def _resolve_opencode_model(profile: dict) -> str:
    """profile.opencode_model 为空时读 config.yaml.opencode_model。"""
    name = (profile.get("opencode_model") or "").strip()
    if name:
        return name
    config_path = os.path.join(_project_root(), "config.yaml")
    if not os.path.exists(config_path):
        return ""
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return (cfg.get("opencode_model") or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery] read config.yaml.opencode_model failed: %s", e)
        return ""


# =====================================================================
# 候选拉取
# =====================================================================

def _gather_candidates(topic: str, sources: list, profile: dict) -> list:
    """根据 sources 列表拉对应数据源，统一返回 list[Candidate]。"""
    from src.discovery_sources import fetch_hf_daily, fetch_arxiv_recent

    all_candidates = []
    src_set = {s.strip().lower() for s in (sources or []) if s and s.strip()}

    if "hf" in src_set:
        all_candidates.extend(fetch_hf_daily(limit=30) or [])
    if "arxiv" in src_set:
        # 用 profile.fallback_arxiv_query 之外的更宽松默认 tags（cs.RO + cs.CV）
        all_candidates.extend(fetch_arxiv_recent(tags=["cs.RO", "cs.CV"], days=7, limit=30) or [])

    # 同 arxiv_id 去重（优先保留 hf，因为带 upvote/github 信息更全）
    seen = {}
    for c in all_candidates:
        if c.arxiv_id not in seen:
            seen[c.arxiv_id] = c
        else:
            # 若已存在 arxiv 源、新来 hf，则覆盖
            if seen[c.arxiv_id].source == "arxiv" and c.source == "hf":
                seen[c.arxiv_id] = c
    deduped = list(seen.values())
    logger.info("[discovery] gathered %d unique candidates from %s",
                len(deduped), sorted(src_set))
    return deduped


# =====================================================================
# 硬过滤
# =====================================================================

def _prefilter(candidates: list, profile: dict) -> list:
    """硬过滤：require_github + exclude_keywords。"""
    require_github = bool(profile.get("require_github", True))
    excludes = [str(s).lower() for s in (profile.get("exclude_keywords") or [])]
    out = []
    for c in candidates:
        title_lc = (c.title or "").lower()
        if any(s and s in title_lc for s in excludes):
            logger.debug("[discovery] filter excluded by keyword: %s", c.title[:60])
            continue
        if require_github and not (c.github_repo and str(c.github_repo).strip()):
            logger.debug("[discovery] filter excluded (no github): %s", c.title[:60])
            continue
        out.append(c)
    logger.info("[discovery] prefilter: %d -> %d", len(candidates), len(out))
    return out


# =====================================================================
# 去重（已发布过的）
# =====================================================================

_FUZZY_TITLE_RATIO = 0.85


def _normalize_title(t: str) -> str:
    if not t:
        return ""
    t = t.lower()
    t = re.sub(r"[\s\W_]+", " ", t)
    return t.strip()


def _load_published(state_path: str) -> list:
    if not os.path.exists(state_path):
        return []
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery] load published state failed: %s", e)
        return []


def _dedupe_against_published(candidates: list, state_path: str) -> list:
    """去掉已发布过的（arxiv_id 严格 + title fuzzy >= 0.85）。"""
    pub = _load_published(state_path)
    if not pub:
        return list(candidates)
    pub_ids = {(p.get("arxiv_id") or "").strip() for p in pub if p.get("arxiv_id")}
    pub_titles = [_normalize_title(p.get("title") or "") for p in pub]
    out = []
    for c in candidates:
        if c.arxiv_id and c.arxiv_id in pub_ids:
            logger.debug("[discovery] dedupe (id): %s", c.arxiv_id)
            continue
        ct = _normalize_title(c.title)
        max_ratio = 0.0
        for pt in pub_titles:
            if not pt:
                continue
            r = difflib.SequenceMatcher(None, ct, pt).ratio()
            if r > max_ratio:
                max_ratio = r
                if max_ratio >= _FUZZY_TITLE_RATIO:
                    break
        if max_ratio >= _FUZZY_TITLE_RATIO:
            logger.debug("[discovery] dedupe (fuzzy %.2f): %s", max_ratio, c.title[:60])
            continue
        out.append(c)
    logger.info("[discovery] dedupe published: %d -> %d", len(candidates), len(out))
    return out


# =====================================================================
# 启发式打分
# =====================================================================

def _heuristic_score(c: Candidate, profile: dict, topic: str) -> tuple:
    """返回 (score: float, reason: str)。"""
    weights = profile.get("weights") or {}
    topics = [str(t).lower() for t in (profile.get("topics") or []) if t]
    boost_list = [str(a).lower() for a in (profile.get("author_boost_list") or []) if a]
    score = 0.0
    parts = []

    # topic 命中
    text_lc = ((c.title or "") + " " + (c.abstract or "")).lower()
    if topic:
        topic_lc = topic.lower().strip()
        if topic_lc and topic_lc in text_lc:
            score += float(weights.get("topic_match", 3))
            parts.append("user_topic")
    hits = 0
    for t in topics:
        if t and t in text_lc:
            hits += 1
    if hits:
        score += float(weights.get("topic_match", 3)) * min(hits, 3) / 3.0
        parts.append("topic_match*%d" % hits)

    # 7 天内
    if c.submitted_date:
        try:
            dt = datetime.datetime.strptime(c.submitted_date[:10], "%Y-%m-%d")
            if (datetime.datetime.now() - dt).days <= 7:
                score += float(weights.get("recent_7d", 2))
                parts.append("recent_7d")
        except Exception:  # noqa: BLE001
            pass

    if c.github_repo:
        score += float(weights.get("has_github", 2))
        parts.append("github")
    if c.project_page:
        score += float(weights.get("has_project_page", 2))
        parts.append("project_page")
    if c.upvotes:
        score += float(weights.get("upvotes_bonus", 0.1)) * min(int(c.upvotes), 20)
        parts.append("upvotes=%d" % c.upvotes)

    # 作者 boost：HF 数据没保留作者；abstract 偶尔会出现作者署名，简单全文匹配
    abstract_lc = (c.abstract or "").lower()
    if any(name and name in abstract_lc for name in boost_list):
        score += float(weights.get("author_boost", 1))
        parts.append("author_boost")

    return score, "+".join(parts) if parts else "no_signal"


def _heuristic_rank(candidates: list, profile: dict, topic: str) -> dict:
    """启发式排序，返回 top-1。

    候选全部 < ``min_score`` → 返回字典里 reason="below_min_score" 由调用方触发 D1。
    """
    if not candidates:
        return {"score": 0.0, "reason": "empty", "candidate": None}
    scored = []
    for c in candidates:
        s, reason = _heuristic_score(c, profile, topic)
        scored.append((s, reason, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_reason, top_c = scored[0]
    min_score = float(profile.get("min_score", 0.0))
    if top_score < min_score:
        logger.warning("[discovery] heuristic top score %.2f < min_score %.2f",
                       top_score, min_score)
        return {"score": top_score, "reason": "below_min_score", "candidate": None}
    return {"score": top_score, "reason": "heuristic:" + top_reason, "candidate": top_c}


# =====================================================================
# opencode 主路打分
# =====================================================================

_DISCOVERY_PROMPT_TEMPLATE = """你是学术论文选题专家。请从下面候选论文中按用户偏好挑出**最适合做讲解视频**的一篇。

# 用户主题（必须命中）
{topic}

# 偏好（按重要性排序）
- 命中主题词: {topic_words}
- 有 github 仓库（开源代码）
- 有 project page（演示页）
- 提交日期在过去 7 天
- 知名作者: {authors}
- 排除：{excludes}

# 候选清单（共 {n} 篇）
{candidates_block}

# 任务
1. 从候选中挑 **1** 篇 best-fit
2. 给一个 1-10 的整数分数（满分 10）
3. 给 1 句话中文理由

返回**严格 JSON**（不要 markdown 代码块外层包裹外的额外内容；JSON 内字段值不要换行），格式：
```json
{{"index": <int>, "score": <int>, "reason": "<str>"}}
```
"""


def _build_discovery_prompt(candidates: list, profile: dict, topic: str) -> str:
    topics = profile.get("topics") or []
    excludes = profile.get("exclude_keywords") or []
    authors = profile.get("author_boost_list") or []
    blocks = []
    for i, c in enumerate(candidates):
        title = (c.title or "").replace("\n", " ").strip()
        # 截 abstract 防止 prompt 过长
        abstract = (c.abstract or "").replace("\n", " ").strip()[:400]
        blocks.append(
            "[{i}] arxiv_id={aid} | source={src} | upvotes={uv} | github={gh} | project_page={pp} | date={dt}\n  title: {ti}\n  abstract: {ab}".format(
                i=i,
                aid=c.arxiv_id,
                src=c.source,
                uv=c.upvotes,
                gh=("yes" if c.github_repo else "no"),
                pp=("yes" if c.project_page else "no"),
                dt=c.submitted_date,
                ti=title,
                ab=abstract,
            )
        )
    return _DISCOVERY_PROMPT_TEMPLATE.format(
        topic=topic,
        topic_words=", ".join(topics),
        authors=", ".join(authors),
        excludes=", ".join(excludes),
        n=len(candidates),
        candidates_block="\n\n".join(blocks),
    )


def _run_opencode_with_pipe(prompt_text: str, opencode_model: str,
                            timeout_sec: int = 180) -> str:
    """以 pipe 模式调 ``opencode run -m <model> -``。

    抄自 ``manim_engine._opencode_generate`` 但独立解耦：
    - prompt 写到 cache/_discovery_prompt.txt（不污染 src 目录）
    - wrapper bash 同样写到 cache/_discovery_wrap.sh
    - 失败/超时返回空串，调用方走 fallback
    """
    if not opencode_model:
        logger.warning("[discovery] opencode_model not configured, skip opencode")
        return ""

    cache_dir = os.path.join(_project_root(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    prompt_file = os.path.join(cache_dir, "_discovery_prompt.txt")
    wrapper = os.path.join(cache_dir, "_discovery_wrap.sh")

    try:
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        with open(wrapper, "w", encoding="utf-8") as wf:
            wf.write("#!/bin/bash\n")
            wf.write("export PATH=/usr/local/bin:$PATH\n")
            # pipe 模式：避免长 prompt 在 shell 命令行展开卡死
            wf.write('cat "{p}" | opencode run -m {m} -\n'.format(
                p=prompt_file, m=opencode_model))
        os.chmod(wrapper, 0o755)
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery] write opencode wrapper failed: %s", e)
        return ""

    env = os.environ.copy()
    # 与 manim_engine 一致：opencode 不走系统代理
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)

    try:
        r = subprocess.run(
            ["bash", wrapper], capture_output=True, text=True,
            timeout=timeout_sec, env=env, cwd=_project_root(),
        )
        out = r.stdout or r.stderr or ""
    except subprocess.TimeoutExpired:
        logger.warning("[discovery] opencode timeout after %ds", timeout_sec)
        return ""
    except FileNotFoundError as e:
        logger.warning("[discovery] opencode binary not found: %s", e)
        return ""
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery] opencode run failed: %s", e)
        return ""

    # 去 ANSI
    out = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out or "")
    return out


def _parse_opencode_json(raw: str) -> Optional[dict]:
    """提取 ```json...``` 或裸 {...}，返回 dict 或 None。"""
    if not raw:
        return None
    s = raw.strip()
    # 优先抽 ```json ... ``` 块
    m = re.search(r"```json\s*\n(.*?)\n```", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 其次抽任意 ```...``` 块
    m = re.search(r"```\s*\n(.*?)\n```", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 最后裸 {...}
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _opencode_rank(candidates: list, profile: dict, topic: str,
                   opencode_model: str) -> Optional[dict]:
    """opencode 选题主路。

    返回 {"score", "reason", "candidate"}；失败 / kill switch / 解析失败均返回 None。
    """
    if os.environ.get("JSR_DISCOVERY_DISABLE_OPENCODE", "").strip() in ("1", "true", "True"):
        logger.info("[discovery] JSR_DISCOVERY_DISABLE_OPENCODE=1, skip opencode")
        return None
    if not candidates:
        return None
    if not opencode_model:
        logger.info("[discovery] no opencode_model, skip opencode")
        return None

    prompt = _build_discovery_prompt(candidates, profile, topic)
    raw = _run_opencode_with_pipe(prompt, opencode_model)
    if not raw:
        return None
    parsed = _parse_opencode_json(raw)
    if not parsed:
        logger.warning("[discovery] opencode JSON parse failed; raw head=%s",
                       (raw or "")[:300])
        return None

    try:
        idx = int(parsed.get("index"))
        score = float(parsed.get("score", 0))
        reason = str(parsed.get("reason") or "").strip() or "opencode_pick"
    except (TypeError, ValueError) as e:
        logger.warning("[discovery] opencode JSON shape invalid: %s | %s", e, parsed)
        return None

    if idx < 0 or idx >= len(candidates):
        logger.warning("[discovery] opencode index %d out of range (0..%d)",
                       idx, len(candidates) - 1)
        return None

    return {
        "score": score,
        "reason": "opencode:" + reason,
        "candidate": candidates[idx],
    }


# =====================================================================
# D1 fallback
# =====================================================================

def _d1_fallback(profile: dict, topic: str, state_path: str) -> Optional[Candidate]:
    """候选全过滤掉 → 强制取 arxiv ``fallback_arxiv_query`` 过去 7 天第 1 条。

    去重已发布的也要走一遍；都用完 → 返回 None。
    """
    from src.discovery_sources import fetch_arxiv_recent
    tag = (profile.get("fallback_arxiv_query") or "cs.RO").strip()
    logger.warning("[discovery] D1 fallback: arxiv tag=%s past 7 days", tag)
    cands = fetch_arxiv_recent(tags=[tag], days=7, limit=30) or []
    cands = _dedupe_against_published(cands, state_path)
    if not cands:
        return None
    # 选第一条（已按 lastUpdatedDate desc 排序）
    return cands[0]


# =====================================================================
# 状态写入（出片成功后）
# =====================================================================

def _append_published(state_path: str, result: dict) -> None:
    """append-only 写入 published_papers.json，幂等（同 arxiv_id 跳过）。

    result 至少含 {arxiv_id, title}；可选 {date, video_path}。
    """
    if not result or not result.get("arxiv_id"):
        return
    aid = str(result["arxiv_id"]).strip()
    title = (result.get("title") or "").strip()
    date = (result.get("date") or "").strip() or datetime.datetime.now().strftime("%Y-%m-%d")
    video_path = (result.get("video_path") or "").strip()

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    pub = _load_published(state_path)
    if any((p.get("arxiv_id") or "").strip() == aid for p in pub):
        logger.info("[discovery] state already has %s, skip append", aid)
        return
    pub.append({
        "arxiv_id": aid,
        "title": title,
        "date": date,
        "video_path": video_path,
    })
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(pub, f, ensure_ascii=False, indent=2)
        logger.info("[discovery] state appended: %s -> %s", aid, state_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery] state write failed: %s", e)


# =====================================================================
# 顶层入口
# =====================================================================

def _save_candidates_snapshot(candidates: list) -> None:
    """调试用：每次 discover 写一份候选快照到 cache/discovery_candidates.json。"""
    try:
        path = _candidates_snapshot_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in candidates], f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        logger.warning("[discovery] save candidates snapshot failed: %s", e)


def discover_top_paper(
    topic: str,
    sources: list = None,
    profile_path: Optional[str] = None,
    n: int = 1,
) -> dict:
    """选题入口。

    Returns:
        dict: {"url", "arxiv_id", "title", "score", "reason", "source"}

    Raises:
        DiscoveryError: 全失败（连 D1 fallback 都拿不到）
    """
    if not topic or not str(topic).strip():
        raise DiscoveryError("topic 不能为空")
    sources = sources or ["hf", "arxiv"]
    profile = _load_profile(profile_path)
    state_path = _state_path()

    # 1. 拉候选
    raw = _gather_candidates(topic, sources, profile)
    _save_candidates_snapshot(raw)
    if not raw:
        logger.warning("[discovery] no candidates from sources, go D1 fallback")
        c = _d1_fallback(profile, topic, state_path)
        if not c:
            raise DiscoveryError("no candidates and D1 fallback failed")
        return {
            "url": c.url, "arxiv_id": c.arxiv_id, "title": c.title,
            "score": 0.0, "reason": "d1_fallback:empty_sources", "source": c.source,
        }

    # 2. 硬过滤 + 去重
    filtered = _prefilter(raw, profile)
    filtered = _dedupe_against_published(filtered, state_path)
    if not filtered:
        c = _d1_fallback(profile, topic, state_path)
        if not c:
            raise DiscoveryError("all filtered and D1 fallback failed")
        return {
            "url": c.url, "arxiv_id": c.arxiv_id, "title": c.title,
            "score": 0.0, "reason": "d1_fallback:all_filtered", "source": c.source,
        }

    # 3. opencode 主路
    opencode_model = _resolve_opencode_model(profile)
    pick = _opencode_rank(filtered, profile, topic, opencode_model)
    if pick is None:
        # 4. fallback 启发式
        pick = _heuristic_rank(filtered, profile, topic)
        if pick.get("candidate") is None:
            # 启发式低分 / 候选空 → D1
            c = _d1_fallback(profile, topic, state_path)
            if not c:
                raise DiscoveryError("heuristic below min_score and D1 fallback failed")
            return {
                "url": c.url, "arxiv_id": c.arxiv_id, "title": c.title,
                "score": 0.0, "reason": "d1_fallback:heuristic_low",
                "source": c.source,
            }

    c = pick["candidate"]
    return {
        "url": c.url,
        "arxiv_id": c.arxiv_id,
        "title": c.title,
        "score": float(pick["score"]),
        "reason": str(pick["reason"]),
        "source": c.source,
    }
