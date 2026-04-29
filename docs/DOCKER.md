# JushenRenji - Docker 化使用指南

本文档描述如何使用 Docker 运行 JushenRenji 的三条 pipeline:
1. `paper-video` — 论文 → manim 讲解视频 → B站/小红书/抖音上传
2. `reply-comments` — LLM 自动回复评论 (Roadmap Task #3)
3. `fetch-stats` — 创作者中心数据抓取 + 飞书表格推送 (Roadmap Task #4)

> 镜像基于 `mambaorg/micromamba:1.5-jammy` (Ubuntu 22.04 + micromamba)。
> 选 micromamba 而不是 miniconda 是因为它解 deps 速度快 5–10 倍且镜像小约 200MB,
> 而 paperagent env 有 280+ 个 pip 包,用 conda solver 经常 hang。

---

## 1. 前置条件 (host)

* Linux + Docker >= 24 + docker compose v2 (Linux 才能用 host network 兜底)
* 宿主机有 clash 在 `127.0.0.1:7890` (HTTP/SOCKS5)
* 项目已 clone 到 `JushenRenji/`,`config.yaml` 已配置 (从 `config.example.yaml` 复制)
* 抖音 cookie:首次必须在 macair (有 GUI 的机器) 跑 SAU headed 登录获取,
  scp 到 `cache/douyin_cookies.json`,容器只复用不能登录 (服务器无 GUI)

---

## 2. Build

```bash
cd JushenRenji
# 默认 profile (bridge + host-gateway, 推荐)
docker compose --profile default build

# build 时间预计 15-30 min, 镜像约 6-8 GB
# (paperagent env 含 torch/torchvision/cuda runtime, 是大头)
```

构建过程拆成 6 个 cache 友好的 layer:
1. apt 系统依赖 (xvfb / ffmpeg / tesseract / chromium runtime libs)
2. micromamba env 创建 (从 `environment.yml`)
3. SAU repo clone
4. SAU venv + 编辑安装
5. patchright + chromium 下载到 `/opt/ms-playwright/`
6. 项目源码 COPY

---

## 3. 首次运行准备

### 3.1 配置 `config.yaml`

```yaml
bilibili_cookies:
  sessdata: "..."
  bili_jct: "..."
  dedeuserid: "..."
  dedeuserid_ckmd5: "..."
dashscope_api_key: sk-xxxx
llm_api_key: sk-xxxx
gemini_api_key: AIzaSy...
output_language: zh
tessdata_prefix: /usr/share/tesseract-ocr/4.00/tessdata/
font_path: /app/font/SIMHEI.TTF
tts_model: cosyvoice-v2
tts_voice: longxiaochun_v2
```

> 也可以用 `.env` 文件 (推荐) — `docker compose` 会自动加载,
> 然后 `DASHSCOPE_API_KEY` / `LLM_API_KEY` 会通过 environment 注入,
> `config.yaml` 字段会被环境变量覆盖。

### 3.2 抖音 cookie (一次性, 非常关键)

抖音风控对 headless 极严,**容器内不能登录**,必须在有 GUI 的机器拿 cookie:

```bash
# 在 macair 上 (有 GUI):
cd ~/Projects/VlogCutter/third_party/social-auto-upload
.venv/bin/sau douyin login   # 弹出 chrome, 扫码登录

# 拿到 cookies.json 后, scp 到服务器:
scp cookies/douyin_xxx.json GSJts:~/Projects/VlogCutter/JushenRenji/cache/douyin_cookies.json
```

容器通过 `./cache:/app/cache` mount 直接复用,无需重新 build。

### 3.3 B站 cookie

`bilibili_cookies` 字段已写在 `config.yaml`,失效时用 biliup 刷新即可,
不依赖容器。

---

## 3.4 小红书 MCP 自动启动

`docker compose --profile default up -d` 会一键拉起 `xhs-mcp` 容器
(镜像 `xpzouying/xiaohongshu-mcp`,监听 18060,只在本机回环暴露
`127.0.0.1:18060`)。`paper-video` / `reply-comments` 通过 docker bridge
网络以 service name `xhs-mcp` 互访,容器内环境变量
`XHS_MCP_URL=http://xhs-mcp:18060/mcp` 已注入。

挂载目录:
```
./tmp/xhs/data    -> /app/data    (cookies.json 写入位置, 持久化登录态)
./tmp/xhs/images  -> /app/images  (上传图片中转目录)
```

首次扫码登录:
```bash
docker compose --profile default up -d xhs-mcp
docker compose --profile default run --rm paper-video \
    python -m src.distribution.xiaohongshu --login
# 终端输出二维码图片路径, 用 macair 打开扫码即可
```

宿主机直跑(非 docker 场景)的 fallback:
* 不设 `XHS_MCP_URL` 时,`src.distribution.xiaohongshu.MCP_SERVER_URL`
  自动回退到 `http://localhost:18060/mcp`。
* 仍可单独 `docker run -d -p 18060:18060 xpzouying/xiaohongshu-mcp:latest`
  独立启动,与宿主机直跑的 paperagent venv 配合使用。

健康检查:
```bash
curl -fsS http://127.0.0.1:18060/health
docker compose ps xhs-mcp   # 看 STATUS 列是否 "(healthy)"
```

---

## 4. 运行

### 4.1 paper-video

```bash
# 生成视频 + 上传到 B站
docker compose --profile default run --rm paper-video \
    --paper-link https://arxiv.org/abs/2602.11075 \
    --platforms bilibili \
    --manim --manim-tts

# 多平台同时上传
docker compose --profile default run --rm paper-video \
    --paper-link https://arxiv.org/abs/2602.11075 \
    --platforms bilibili,xiaohongshu,douyin \
    --manim --manim-tts
```

输出:
* `output/<日期>_<标题>.mp4` — 最终视频
* `cache/<paper_id>/...` — 中间产物 (audio / subtitles / images)

### 4.2 reply-comments (Task #3)

```bash
docker compose --profile default run --rm reply-comments \
    --platforms bilibili,xiaohongshu \
    --max-replies 20
```

> CLI 由 Task #3 实现,这里只 reference 模块路径
> `src.distribution.comments.cli`。

### 4.3 fetch-stats (Task #4)

```bash
# 拉过去 7 天数据并推送飞书
docker compose --profile default run --rm fetch-stats \
    summary --days 7 --push-feishu
```

数据落地 `data/creator_stats.db` (sqlite, host volume mount)。

### 4.4 SAU CLI 直通 (调试)

```bash
docker compose --profile default run --rm \
    --entrypoint /app/docker-entrypoint.sh paper-video sau --help
```

---

## 5. 网络模式

### 5.1 默认: bridge + host-gateway (推荐)

容器内 `host.docker.internal:7890` 走宿主机 clash。
DashScope (`dashscope.aliyuncs.com`) 在 `NO_PROXY` 里,直连。

### 5.2 备选: host network

```bash
docker compose --profile host-net run --rm paper-video-host \
    --paper-link https://arxiv.org/abs/2602.11075 --platforms bilibili --manim
```

适合:
* 跑在 GPU 服务器只有 IPv6 出网,需要绕开 docker bridge 自动 IPv6
* 想用 `127.0.0.1:7890` 而不是 `host.docker.internal`
* 需要 host 上的 systemd resolved / mdns 等

---

## 6. 排查

### 6.1 Xvfb 没起来

```bash
docker compose --profile default run --rm --entrypoint bash paper-video
# 容器内
Xvfb :99 -screen 0 1920x1080x24 &
DISPLAY=:99 xdpyinfo | head
```

`docker-entrypoint.sh` 会自动检测,启动失败会 abort。
日志在容器内 `/tmp/xvfb.log`。

### 6.2 chromium 缺 .so

如果改基础镜像或升级 patchright,可能新增动态库依赖:

```bash
docker compose run --rm --entrypoint bash paper-video
ldd /opt/ms-playwright/chromium-*/chrome-linux/chrome | grep 'not found'
```

把缺的包加进 Dockerfile 的 `apt install` 列表。

### 6.3 DashScope 'socket is already closed'

参考 `MEMORY: project_gsjts_dashscope_ipv6` — 必须强制 IPv4。
docker-compose.yaml 已把 `dashscope.aliyuncs.com` 加入 `NO_PROXY`,
不走 clash 即可。如果仍翻车,加 `sysctls: net.ipv6.conf.all.disable_ipv6=1`。

### 6.4 cookie 过期

抖音 cookie ~30 天失效,失效后:
1. 在 macair 重新 SAU headed 登录
2. scp 覆盖 `cache/douyin_cookies.json`
3. 不需重 build / 重启容器,下次 run --rm 会自动加载

### 6.5 cache 满了

```bash
du -sh cache/ output/
# 安全清理: arxiv_src 是可重新下载的, 视频文件按需保留
rm -rf cache/arxiv_src/<old-paper>/
```

---

## 7. CI / 服务器定时任务

`fetch-stats` 适合 cron:

```cron
# 每天 02:00 拉昨天数据
0 2 * * * cd /home/jdh/Projects/VlogCutter/JushenRenji && \
    docker compose --profile default run --rm fetch-stats summary --days 1 --push-feishu \
    >> /var/log/jushenrenji-stats.log 2>&1
```

---

## 8. 相关文档

* `README.md` — 项目主文档
* `config.example.yaml` — 配置模板
* `docs/plans/` — 各 Roadmap task 的设计文档
* `LESSONS_LEARNED.md` — 踩坑记录 (DashScope IPv6 / Xvfb / 等)
