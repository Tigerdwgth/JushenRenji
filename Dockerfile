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
        git curl ca-certificates \
        build-essential pkg-config \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ---- micromamba env: paperagent ----
ENV MAMBA_ROOT_PREFIX=/opt/conda \
    PATH=/opt/conda/envs/paperagent/bin:$PATH

# Copy environment.yml in its own layer so cache is reused when deps unchanged.
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba env create -f /tmp/environment.yml \
    && micromamba clean --all --yes \
    && rm /tmp/environment.yml

# ---- SAU (social-auto-upload) - third-party repo, isolated venv ----
# Mirrors host layout: third_party/social-auto-upload/.venv (Python 3.10).
ARG SAU_REPO=https://github.com/dreammis/social-auto-upload.git
ARG SAU_REF=main
RUN mkdir -p /app/third_party && cd /app/third_party \
    && git clone --depth 1 --branch "${SAU_REF}" "${SAU_REPO}" social-auto-upload \
    && cd social-auto-upload \
    && /opt/conda/envs/paperagent/bin/python -m venv .venv \
    && .venv/bin/pip install --no-cache-dir --upgrade pip \
    && .venv/bin/pip install --no-cache-dir -e .

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

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["--help"]
