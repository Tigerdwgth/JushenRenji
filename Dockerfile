# syntax=docker/dockerfile:1.6
# JushenRenji - paper-to-video + multi-platform distribution
# Base: micromamba on Ubuntu 22.04 (jammy). Faster dep solving than miniconda.
FROM mambaorg/micromamba:1.5-jammy AS base

# ---- root: install system deps ----
USER root
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Single layer: apt update + install + cleanup, keeps image small.
# Xvfb     - douyin headed Chrome MUST have a virtual display
# ffmpeg   - moviepy / manim video pipeline
# tesseract-ocr + chi-sim/eng - figure OCR
# libgl1 / libglib - opencv-python runtime
# libnss3 / libdrm2 / libxkbcommon0 / libxcomposite1 / libxdamage1 / libxrandr2
#   libxcursor1 / libxshmfence1 / libgbm1 / libasound2 / libatk-bridge2.0-0
#   libcairo2 / libpango-1.0-0 - patchright / chromium runtime
# fonts-noto-cjk - manim CJK subtitle fallback
# git / curl / ca-certificates - clone SAU + HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb ffmpeg \
        tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
        libgl1 libglib2.0-0 \
        libnss3 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxrandr2 libxcursor1 libxshmfence1 libgbm1 libasound2 \
        libatk-bridge2.0-0 libatk1.0-0 libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
        fonts-noto-cjk fonts-liberation \
        git curl ca-certificates gnupg \
        build-essential pkg-config \
        libpango1.0-dev libcairo2-dev python3-dev \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ---- pip 国内镜像 (容器内无法走 host clash 代理) ----
RUN mkdir -p /etc && \
    echo "[global]" > /etc/pip.conf && \
    echo "index-url = https://pypi.tuna.tsinghua.edu.cn/simple" >> /etc/pip.conf && \
    echo "extra-index-url = https://download.pytorch.org/whl/cpu" >> /etc/pip.conf && \
    echo "trusted-host = pypi.tuna.tsinghua.edu.cn pypi.org download.pytorch.org mirrors.aliyun.com" >> /etc/pip.conf

# ---- micromamba env: paperagent ----
ENV MAMBA_ROOT_PREFIX=/opt/conda \
    PATH=/opt/conda/envs/paperagent/bin:$PATH

# Step 1: conda 创建空 env (只装 python+pip, 跳过 nodejs 6 旧版)
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba env create -f /tmp/environment.yml \
    && micromamba clean --all --yes \
    && rm /tmp/environment.yml

# Step 2: uv pip 装 pip 包 (uv 多线程下载 ~10x 比 pip 快, 解决清华 mirror 单连接慢的问题)
# --no-deps 绕过严格 resolver, 沿用 host 已验证的版本组合
RUN /opt/conda/envs/paperagent/bin/pip install --no-cache-dir uv==0.4.30
COPY --chown=$MAMBA_USER:$MAMBA_USER requirements_pip.txt /tmp/requirements_pip.txt
RUN /opt/conda/envs/paperagent/bin/uv pip install \
        --python /opt/conda/envs/paperagent/bin/python \
        --no-deps \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        --index-strategy unsafe-best-match \
        -r /tmp/requirements_pip.txt \
    && rm /tmp/requirements_pip.txt

# ---- Node.js 20 (NodeSource) + opencode CLI ----
# opencode-ai (npm 包) 提供 manim 代码生成的 headless LLM bridge
# 使用 NodeSource 二进制源 (apt) 比 conda nodejs 6 新得多
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version

# 配置 npm 使用淘宝镜像 (容器内无 clash 代理)
RUN npm config set registry https://registry.npmmirror.com \
    && npm install -g opencode-ai@1.4.1 \
    && opencode --version

# COPY opencode 配置 (含 deepseek API key + provider config) 给 mambauser
# 注意 docker/opencode/ 在 .gitignore 里, 不会进 git, 但会进 build context
# opencode 配置: 容器 entrypoint 以 root 跑, opencode 找 $HOME/.config/opencode
COPY docker/opencode /root/.config/opencode
# 同步给 mambauser (debug shell 时也能用)
COPY --chown=$MAMBA_USER:$MAMBA_USER docker/opencode /home/mambauser/.config/opencode


# ---- SAU (social-auto-upload) - third-party repo, isolated venv ----
# Mirrors host layout: third_party/social-auto-upload/.venv (Python 3.10).
ARG SAU_REPO=https://gh-proxy.com/https://github.com/dreammis/social-auto-upload.git
ARG SAU_REF=main
RUN mkdir -p /app/third_party && cd /app/third_party \
    && git clone --depth 1 --branch "${SAU_REF}" "${SAU_REPO}" social-auto-upload \
    && cd social-auto-upload \
    && /opt/conda/envs/paperagent/bin/python -m venv .venv \
    && /opt/conda/envs/paperagent/bin/uv pip install \
        --python .venv/bin/python \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        --index-strategy unsafe-best-match \
        -e .

# ---- patchright / chromium ----
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN /app/third_party/social-auto-upload/.venv/bin/patchright install --with-deps chromium \
    && chmod -R a+rx /opt/ms-playwright

# ---- project source ----
WORKDIR /app
# .dockerignore excludes cache/output/cookies/config.yaml etc.
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app/

# Mount points (volumes shadow these at runtime; build-time stub keeps perms).
RUN mkdir -p /app/cache /app/output /app/data /app/pic \
    && chmod +x /app/docker-entrypoint.sh

# tessdata path - config.yaml tessdata_prefix can override.
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata/ \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    XVFB_DISPLAY=:99 \
    DISPLAY=:99 \
    SAU_VENV=/app/third_party/social-auto-upload/.venv

# ---- numpy 2 兼容性补丁 ----
# matplotlib 3.8.3 用 numpy 1 编译, 与 numpy 2.2 不兼容; 升级到 3.9 (向后兼容)
RUN /opt/conda/envs/paperagent/bin/uv pip install \
        --python /opt/conda/envs/paperagent/bin/python \
        --no-deps \
        --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
        --index-strategy unsafe-best-match \
        matplotlib==3.9.4

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["--help"]
