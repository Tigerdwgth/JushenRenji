#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# JushenRenji docker entrypoint - sub-command dispatcher
#
# Usage (inside container):
#   docker-entrypoint.sh paper-video <args>      python src/main.py <args>
#   docker-entrypoint.sh reply-comments <args>   python -m src.distribution.comments.cli <args>
#   docker-entrypoint.sh fetch-stats <args>      python -m src.distribution.analytics.cli <args>
#   docker-entrypoint.sh sau <args>              third_party SAU venv passthrough
#   docker-entrypoint.sh bash                    debug shell
#   docker-entrypoint.sh --help                  print this help
#
# 启动前自动:
#   1. Xvfb :99 后台跑 (douyin headed 必须)
#   2. export DISPLAY=:99
#   3. 校验 config.yaml / cache 目录可写
# -----------------------------------------------------------------------------
set -euo pipefail

# ----- helpers ---------------------------------------------------------------
log()   { printf '[entrypoint] %s\n' "$*" >&2; }
fatal() { printf '[entrypoint][FATAL] %s\n' "$*" >&2; exit 1; }

print_help() {
    cat <<'HELP'
JushenRenji docker entrypoint

Sub-commands:
    paper-video <args>      Generate manim paper-explainer video and upload.
                            Forwarded to: python src/main.py <args>
    reply-comments <args>   Reply to social comments via LLM (task #3).
                            Forwarded to: python -m src.distribution.comments.cli <args>
    fetch-stats <args>      Pull bilibili/xiaohongshu/douyin creator stats (task #4).
                            Forwarded to: python -m src.distribution.analytics.cli <args>
    sau <args>              Passthrough to social-auto-upload venv (e.g. headed login).
                            Forwarded to: third_party/social-auto-upload/.venv/bin/sau <args>
    bash                    Drop into an interactive shell for debugging.
    --help | -h             Show this help.

Environment variables:
    XVFB_DISPLAY            Virtual display (default :99).
    DASHSCOPE_API_KEY       Override config.yaml.
    LLM_API_KEY             Override config.yaml.
    HTTPS_PROXY / NO_PROXY  Proxy split (clash for general, direct for DashScope).
HELP
}

# ----- 启动 Xvfb -------------------------------------------------------------
start_xvfb() {
    local display="${XVFB_DISPLAY:-:99}"
    if ! command -v Xvfb >/dev/null 2>&1; then
        log "Xvfb not installed, skip (douyin upload will fail in headed mode)"
        return 0
    fi
    if pgrep -f "Xvfb ${display}" >/dev/null 2>&1; then
        log "Xvfb ${display} already running"
    else
        log "starting Xvfb ${display} 1920x1080x24"
        # nolisten tcp + ac: 安全 + 任意 client 可连
        Xvfb "${display}" -screen 0 1920x1080x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
        # 等 Xvfb 起来 (典型 < 1s)
        for _ in 1 2 3 4 5; do
            if pgrep -f "Xvfb ${display}" >/dev/null 2>&1; then break; fi
            sleep 0.3
        done
        if ! pgrep -f "Xvfb ${display}" >/dev/null 2>&1; then
            fatal "Xvfb failed to start, see /tmp/xvfb.log"
        fi
    fi
    export DISPLAY="${display}"
    log "DISPLAY=${DISPLAY}"
}

# ----- 校验运行时挂载 --------------------------------------------------------
check_mounts() {
    if [[ ! -f /app/config.yaml ]]; then
        log "WARN: /app/config.yaml not mounted; falling back to env vars only"
    fi
    for d in /app/cache /app/output /app/data; do
        if [[ ! -w "${d}" ]]; then
            fatal "${d} not writable - mount it as a volume (-v ./${d##*/}:${d})"
        fi
    done
}

# ----- 子命令 dispatcher -----------------------------------------------------
main() {
    if [[ $# -eq 0 ]]; then
        print_help; exit 0
    fi

    local cmd="$1"; shift || true

    case "${cmd}" in
        --help|-h|help)
            print_help; exit 0
            ;;
        bash|sh)
            log "interactive shell"
            exec bash "$@"
            ;;
        paper-video)
            check_mounts
            start_xvfb
            log "exec: python src/main.py $*"
            exec python /app/src/main.py "$@"
            ;;
        reply-comments)
            check_mounts
            start_xvfb
            log "exec: python -m src.distribution.comments.cli $*"
            exec python -m src.distribution.comments.cli "$@"
            ;;
        fetch-stats)
            check_mounts
            start_xvfb
            log "exec: python -m src.distribution.analytics.cli $*"
            exec python -m src.distribution.analytics.cli "$@"
            ;;
        sau)
            check_mounts
            start_xvfb
            local sau_venv="${SAU_VENV:-/app/third_party/social-auto-upload/.venv}"
            if [[ ! -x "${sau_venv}/bin/sau" ]]; then
                fatal "SAU CLI not found at ${sau_venv}/bin/sau"
            fi
            log "exec: ${sau_venv}/bin/sau $*"
            exec "${sau_venv}/bin/sau" "$@"
            ;;
        *)
            log "Unknown sub-command: ${cmd}"
            print_help; exit 2
            ;;
    esac
}

main "$@"
