---
name: account-ops
description: 具身人机三平台 (B站 / 小红书 / 抖音) 账号运营运维：定时跑评论自动回复 (LLM 互动话术 + 风控随机化)、拉取创作者中心数据写 sqlite + 推飞书多维表格、巡检 cookie 是否失效。当用户提到"运营这周的视频/查粉丝评论/拉一下数据/B站 cookie 又掉了"等场景时使用。
---

# Account-Ops: 三平台账号运营

## Overview

JushenRenji 项目除了 paper → video 生产链路，还有一条独立的"账号运营"侧链，分两个子模块：

1. **评论自动回复** (`src/distribution/comments/`) — 拉每个平台最近 N 条视频的新评论，LLM 生成活泼回复，节流 1-60s 随机化降风控，sqlite 防重复
2. **创作者中心数据** (`src/distribution/analytics/`) — 拉播放量 / 点赞 / 涨粉等指标，存 sqlite，可推飞书 Bitable 看板

本 skill 只做"运维触发"，不动业务逻辑代码。

## Argument Parsing

参数即子动作。支持：

- `reply` — 跑一次评论回复巡检（默认全平台、最近 168h、最多 10 条视频）
- `reply --dry-run` — 演练，不真的发评论
- `reply --platforms bilibili` — 单平台
- `stats fetch` — 拉一次创作者中心快照写 sqlite
- `stats summary` — 打印近 7 天数据汇总
- `stats summary --days 30` — 按天数定制
- `cookies` — 巡检三平台 cookie 是否失效，给报告

## Fixed Environment Facts

- conda env: `paperagent`，路径 `~/miniconda3/etc/profile.d/conda.sh`
- 工程根: `~/Projects/VlogCutter/JushenRenji`
- 必须用 `python -m src.distribution.comments.cli ...` / `python -m src.distribution.analytics.cli ...` 模块方式跑（不要直接 `python src/distribution/.../cli.py`，相对 import 会炸）
- 代理分流：clash 7890 走外网，aliyun / 127.0.0.1 NO_PROXY 直连（`env_setup.apply_network_workarounds` 已封装）
- `cache/published_papers.json` 是数据源（每次 main.py 跑完追加），`cache/post_ids.json` 是评论模块需要的 video → BV/note_id/aweme_url 映射，没填会自动跳过 (post, platform) 对，不报错
- B 站 cookie 在 `config.yaml` 的 `bilibili.cookies`（容易失效，code=-101 就是过期了）
- 小红书走 `xpzouying/xiaohongshu-mcp` docker 服务，cookie 在 mcp 容器里持久化
- 抖音走 SAU venv (`thirdparty/social-auto-upload/.venv`) + Xvfb headed Chrome，cookie 在 `cache/douyin_cookies.json`（不存在就是没扫过码）

## Steps to Execute

### Action: reply

```bash
ssh GSJts 'source ~/miniconda3/etc/profile.d/conda.sh && conda activate paperagent && cd ~/Projects/VlogCutter/JushenRenji && python -m src.distribution.comments.cli --platforms <PLATFORMS> --max-posts 10 [--dry-run] 2>&1 | tail -80'
```

Cookie 失效时该平台会日志报错跳过，**不要硬重试**。判定标准：

- B 站: `code=-101 账号未登录` → 报告给用户：`config.yaml bilibili.cookies` 过期，需重登
- 抖音: `cookie 文件不存在` 或 `登录页跳转` → 在 macair 跑 SAU 扫码登录脚本
- 小红书: `MCP session 失败` → 检查 `docker compose logs xhs-mcp`

### Action: stats fetch / summary

```bash
# fetch 写 sqlite
ssh GSJts 'source ~/miniconda3/etc/profile.d/conda.sh && conda activate paperagent && cd ~/Projects/VlogCutter/JushenRenji && python -m src.distribution.analytics.cli fetch --max-posts 20 2>&1 | tail -40'

# summary 打印近 N 天 ASCII 表
ssh GSJts 'source ~/miniconda3/etc/profile.d/conda.sh && conda activate paperagent && cd ~/Projects/VlogCutter/JushenRenji && python -m src.distribution.analytics.cli summary --days 7'
```

数据存 `~/Projects/VlogCutter/JushenRenji/cache/analytics.sqlite`（默认）。如果用户要推飞书 Bitable，下一步用 `stats_store` + `lark_uploader` 模块组合；目前 `lark_uploader.py` 还是 stub，需要先在 `config.yaml` 配 `lark.app_id / app_secret / app_token / table_id` 才能生效。

### Action: cookies (巡检)

```bash
ssh GSJts 'source ~/miniconda3/etc/profile.d/conda.sh && conda activate paperagent && cd ~/Projects/VlogCutter/JushenRenji && python3 -c "
import json, os, sys
sys.path.insert(0, \"src\")
report = {}
# B 站
try:
    from distribution.bilibili import _load_cookies, _check_login
    cookies = _load_cookies()
    ok, msg = _check_login(cookies)
    report[\"bilibili\"] = {\"ok\": ok, \"msg\": msg}
except Exception as e:
    report[\"bilibili\"] = {\"ok\": False, \"msg\": str(e)}
# 抖音
report[\"douyin\"] = {\"ok\": os.path.exists(\"cache/douyin_cookies.json\"),
                     \"msg\": \"cookie 文件 \" + (\"存在\" if os.path.exists(\"cache/douyin_cookies.json\") else \"不存在\")}
# 小红书 (mcp 容器健康)
import subprocess
r = subprocess.run([\"docker\", \"ps\", \"--filter\", \"name=xhs-mcp\", \"--format\", \"{{.Status}}\"], capture_output=True, text=True)
report[\"xiaohongshu\"] = {\"ok\": \"Up\" in (r.stdout or \"\"), \"msg\": (r.stdout or r.stderr or \"\").strip() or \"docker 未启动\"}
print(json.dumps(report, ensure_ascii=False, indent=2))
"'
```

## Important Notes

- 评论回复每平台单日上限由 `cli.py` 内部控制，触顶就停；不要试图绕过
- 数据分析 cron 推荐每日 09:00：`0 9 * * * cd ~/Projects/VlogCutter/JushenRenji && /home/jdh/miniconda3/envs/paperagent/bin/python -m src.distribution.analytics.cli fetch >> tmp/analytics_fetch.log 2>&1`
- 临时脚本一律放项目 `./tmp/` 下，禁止 `/tmp/`（CLAUDE.md 全局规则）
- 给用户看的报告（cookie 巡检、stats summary）原样贴出 stdout 即可，不需要二次包装
- 失败的不重试硬推（CLAUDE.md "失败的不推" 原则）
- 抖音和 B 站 cookie 失效是常态，把状态如实告知用户即可
