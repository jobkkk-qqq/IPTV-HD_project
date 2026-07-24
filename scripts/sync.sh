#!/bin/bash
# IPTV HD Sync — 容器内版本
# 下载 → ffprobe 高清探测 → 格式标准化
# 用法: docker exec iptv-hd bash /scripts/sync.sh

set -e

CACHE_DIR="/data"
UPSTREAM_BASE="https://raw.githubusercontent.com/Guovin/iptv-api/gd/output"
LOG="${CACHE_DIR}/sync-hd.log"

echo "=== IPTV HD Sync $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"

# Step 1: Download source (用 Python urllib，容器内零额外依赖)
echo "[1/4] Downloading source..." | tee -a "$LOG"
python3 -c "
import urllib.request, sys
url = '${UPSTREAM_BASE}/result.m3u'
out = '${CACHE_DIR}/source.m3u'
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        with open(out, 'wb') as f:
            f.write(r.read())
    print('  Downloaded')
except Exception as e:
    print(f'  ERROR: {e}', flush=True)
    sys.exit(1)
" 2>&1 | tee -a "$LOG"

SRC=$(grep -c "#EXTINF" "${CACHE_DIR}/source.m3u" 2>/dev/null || echo 0)
echo "  Source: ${SRC} entries" | tee -a "$LOG"
[ "$SRC" -lt 100 ] && echo "ERROR: too few channels (${SRC})" | tee -a "$LOG" && exit 1

# Step 2: Copy source directly (no pre-filter)
echo "[2/4] Using all sources (no pre-filter)..." | tee -a "$LOG"
cp "${CACHE_DIR}/source.m3u" "${CACHE_DIR}/result.m3u"

# Step 3: ffprobe HD detection
echo "[3/4] ffprobe resolution check (parallel, 15s timeout)..." | tee -a "$LOG"
CACHE_DIR="$CACHE_DIR" python3 /scripts/probe_hd.py 2>&1 | tee -a "$LOG"

# Step 4: Format using standard template
echo "[4/4] Format using standard template..." | tee -a "$LOG"
python3 /scripts/iptv_format.py \
  "${CACHE_DIR}/result_hd.m3u" \
  "${CACHE_DIR}/result.m3u" \
  "${CACHE_DIR}/result.txt" 2>&1 | tee -a "$LOG"

M3U_CNT=$(grep -c "#EXTINF" "${CACHE_DIR}/result.m3u" 2>/dev/null || echo 0)
echo "=== Done → ${M3U_CNT} HD channels ===" | tee -a "$LOG"
