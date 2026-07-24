#!/bin/bash
# IPTV HD — 容器入口
# 首次启动时后台自动同步，同时启动 HTTP 服务器

# 在后台运行首次同步（仅当 data 为空时）
if [ ! -f /data/result.m3u ] || [ ! -s /data/result.m3u ]; then
    echo "[entrypoint] No data found, running initial sync in background..."
    bash /scripts/sync.sh &
fi

# 启动 HTTP 服务器（前台）
exec python3 /app/server.py
