---
name: paper-search
description: Use when the user wants to search arXiv (by topic, by venue/year) or HuggingFace Daily Papers for academic papers from inside the JushenRenji repo. Returns structured JSON with arxiv_id, title, abstract, url, github_repo, project_page, etc. Useful for picking topics for paper-explainer videos or feeding the manim engine.
---

# Paper Search

## Overview

This skill exposes three discovery commands from the `JushenRenji` repo as a JSON-stdout CLI you can call from opencode / Bash:

| Tool | Purpose |
|---|---|
| `arxiv_search`      | Search arXiv by topic phrase + categories + recency window |
| `arxiv_by_venue`    | Search arXiv by venue (RSS/NeurIPS/CoRL/ICLR/ICRA/CVPR/...) and year via the `co:` (comments) field |
| `hf_daily_papers`   | Today's HuggingFace Daily Papers leaderboard |

All three return the same JSON contract:

```json
{
  "ok": true,
  "count": 10,
  "papers": [
    {
      "arxiv_id": "2410.24164",
      "title": "...",
      "abstract": "...",
      "url": "https://arxiv.org/abs/2410.24164",
      "submitted_date": "2026-01-08",
      "upvotes": 0,
      "github_repo": null,
      "project_page": null,
      "source": "arxiv_venue"
    }
  ]
}
```

On error: `{"ok": false, "error": "<msg>", "papers": []}` and exit code 1.

## Cross-conda invocation pattern

You MUST run the command inside the `paperagent` conda env from the repo root:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate paperagent
cd ~/Projects/VlogCutter/JushenRenji
python -m src.discovery_sources.cli <subcommand> [args...]
```

The CLI auto-applies the network workaround when `JSR_NETWORK_PROFILE=gsjts` is in the env (clash proxy + IPv4-only — needed on the GSJts box). Set it once via `export JSR_NETWORK_PROFILE=gsjts` if you hit network failures from this host.

## Tool 1: arxiv_search

Search arXiv recent papers by a topic phrase + cs categories + recency window.

### Input

| Flag | Type | Default | Description |
|---|---|---|---|
| `--query`      | string  | (required) | Topic phrase, gets wrapped as `abs:"<phrase>"` server-side |
| `--days`       | int     | 7          | Keep only `submitted_date >= now - days` |
| `--limit`      | int     | 30         | Max papers to fetch |
| `--categories` | string  | `cs.RO,cs.CV` | Comma-separated arxiv `cat:` filter |

### Bash example

```bash
python -m src.discovery_sources.cli arxiv-search \
  --query "diffusion policy" \
  --days 14 \
  --limit 20 \
  --categories "cs.RO,cs.LG"
```

## Tool 2: arxiv_by_venue

Search arXiv accepted-paper notes by venue + year. **Best-effort** — arxiv `co:` (comments) field is not normalized: authors write `Accepted to RSS 2025`, `To appear at NeurIPS 2025`, `RSS 2025`, `RSS'25`, etc. We OR all four typical variants. Recall is not guaranteed; precision is high.

### Input

| Flag | Type | Default | Description |
|---|---|---|---|
| `--venue`              | string | (required) | `RSS` / `NeurIPS` / `CoRL` / `ICLR` / `ICRA` / `CVPR` / `ICCV` / `ECCV` / etc. (case sensitive — pass it as the venue conventionally writes it) |
| `--year`               | int    | (required) | 4-digit year (e.g. `2025`) |
| `--limit`              | int    | 50         | Max papers to fetch |
| `--include-submitted`  | flag   | off        | Also match `submitted to <venue> <year>` (default: accepted-only) |
| `--categories`         | string | `cs.RO,cs.CV,cs.LG,cs.AI` | Comma-separated arxiv `cat:` filter |

### Known venue strings

Use these exact strings (no extra punctuation):

```
RSS         (Robotics: Science and Systems)
NeurIPS     (or "NeurIPS" — note no space inside)
CoRL        (Conference on Robot Learning)
ICLR
ICML
ICRA
IROS
CVPR
ICCV
ECCV
RSS Workshop   (matches "RSS Workshop 2025" comments)
```

Non-canonical strings (e.g. "rss") still work but recall is worse.

### Bash example

```bash
python -m src.discovery_sources.cli arxiv-by-venue \
  --venue RSS --year 2025 --limit 20

# Also include "submitted to ..." (less precise)
python -m src.discovery_sources.cli arxiv-by-venue \
  --venue NeurIPS --year 2025 --limit 50 --include-submitted
```

## Tool 3: hf_daily_papers

Pull HuggingFace Daily Papers leaderboard (today's hot papers, with upvotes / github_repo / project_page).

### Input

| Flag | Type | Default | Description |
|---|---|---|---|
| `--limit` | int | 30 | Max papers to fetch |

### Bash example

```bash
python -m src.discovery_sources.cli hf-daily --limit 20
```

## Typical scenarios

### "Find RSS 2025 accepted papers that have GitHub"

```bash
python -m src.discovery_sources.cli arxiv-by-venue \
  --venue RSS --year 2025 --limit 50 \
  | jq '.papers[] | select(.github_repo != null) | {title, arxiv_id, github_repo}'
```

(GitHub repo is rarely populated for arxiv-only entries — for repos use `arxiv_search` and post-filter, or pull HF Daily.)

### "Find recent latent-action papers in cs.RO"

```bash
python -m src.discovery_sources.cli arxiv-search \
  --query "latent action" --days 7 --limit 30 --categories "cs.RO"
```

### "Today's HF Daily papers, top 10"

```bash
python -m src.discovery_sources.cli hf-daily --limit 10 \
  | jq '.papers[] | {title, upvotes, github_repo}'
```

## Output contract details

Each paper object in `papers[]`:

| Field | Type | Description |
|---|---|---|
| `arxiv_id`        | string         | e.g. `"2410.24164"` (no version suffix) |
| `title`           | string         | Single-line, leading/trailing whitespace stripped |
| `abstract`        | string         | Full abstract |
| `url`             | string         | `https://arxiv.org/abs/<arxiv_id>` |
| `submitted_date`  | string         | `YYYY-MM-DD` (from arxiv `updated` or `published`) |
| `upvotes`         | int            | HF upvote count, 0 for arxiv sources |
| `github_repo`     | string \| null | HF only; arxiv has no github metadata |
| `project_page`    | string \| null | HF only |
| `source`          | string         | `"hf"` / `"arxiv"` / `"arxiv_venue"` |

## Error handling

The CLI never crashes on network failures. On error, stdout is still valid JSON:

```json
{"ok": false, "error": "RuntimeError: simulated network down", "papers": []}
```

Exit code is 1 when `ok=false`, 0 otherwise. **Always parse stdout JSON before reading exit code.**

## Limitations

- `co:` (comments) field on arxiv is best-effort. Some accepted papers don't list the venue in their abstract/comments. If you need an authoritative list, use the conference's official accepted-papers page (out of scope).
- HF Daily only returns papers HF has indexed; the upvote count is "live" so re-running gives different ordering.
- The CLI assumes the `paperagent` conda env is active (uses `feedparser`, `requests`, `pyyaml`).
