#!/bin/bash
# IPTV HD Sync — 容器内版本
# 下载 → ffprobe 高清探测 → 格式标准化
# 用法: docker exec iptv-hd bash /scripts/sync.sh

set -e
set -o pipefail

CACHE_DIR="/data"
UPSTREAM_BASE="https://raw.githubusercontent.com/Guovin/iptv-api/gd/output"
# EPG 源：51zmt（老张的EPG）—— 当天数据、约 1MB、2 秒可下。
# 它的频道用数字 id（id="1" 即 CCTV1），与本列表 tvg-id="CCTV-1" 对不上，
# 所以经 epg_convert.py 做 id 映射后再落地（未匹配频道整块丢弃，顺带瘦身）。
# 注：Guovin 自带的 output/epg/epg.xml 已停更在 2026-08-07，不可用。
EPG_SOURCE_URL="${IPTV_EPG_SOURCE:-http://epg.51zmt.top:8000/e.xml}"
LOG="${CACHE_DIR}/sync-hd.log"

echo "=== IPTV HD Sync $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"

# Step 1: Download source
# 国内直连 raw.githubusercontent 经常超时（2026-09 实测：容器内 60s 读超时），
# 故按 gh-proxy → jsDelivr → 直连 的顺序多通道尝试，第一个成功即用。
echo "[1/4] Downloading source..." | tee -a "$LOG"
python3 -c "
import urllib.request, sys
GH = '${UPSTREAM_BASE}/result.m3u'
MIRRORS = [
    ('gh-proxy', 'https://gh-proxy.com/' + GH),                                # 实时透传，实测 2.5s
    ('jsDelivr', 'https://cdn.jsdelivr.net/gh/Guovin/iptv-api@gd/output/result.m3u'),  # 最快 0.5s，但有 CDN 缓存
    ('direct', GH),
]
last_err = 'n/a'
for name, url in MIRRORS:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        if data.count(b'#EXTINF') < 100:
            last_err = name + ': too few entries (' + str(data.count(b'#EXTINF')) + ')'
            print('  ' + last_err + ' - trying next...', flush=True)
            continue
        with open('${CACHE_DIR}/source.m3u', 'wb') as f:
            f.write(data)
        print('  Downloaded via ' + name + ' (' + str(len(data)//1024) + 'KB)', flush=True)
        sys.exit(0)
    except Exception as e:
        last_err = name + ': ' + type(e).__name__ + ': ' + str(e)
        print('  ' + last_err + ' - trying next...', flush=True)
print('  ERROR: all mirrors failed. last=' + last_err, flush=True)
sys.exit(1)
" 2>&1 | tee -a "$LOG"

SRC=$(grep -c "#EXTINF" "${CACHE_DIR}/source.m3u" 2>/dev/null || echo 0)
echo "  Source: ${SRC} entries" | tee -a "$LOG"
[ "$SRC" -lt 100 ] && echo "ERROR: too few channels (${SRC})" | tee -a "$LOG" && exit 1

# Step 2: Backup source only (绝不覆盖 result.m3u — 防止 Step 4 失败时服务器喂原始源)
echo "[2/4] Backing up source (result.m3u untouched)..." | tee -a "$LOG"
cp "${CACHE_DIR}/source.m3u" "${CACHE_DIR}/source.bak"

# Step 3: ffprobe HD detection
echo "[3/4] ffprobe resolution check (parallel, 20s timeout)..." | tee -a "$LOG"
set +e
CACHE_DIR="$CACHE_DIR" python3 /scripts/probe_hd.py 2>&1 | tee -a "$LOG"
PROBE_RC=${PIPESTATUS[0]}
set -e
if [ "$PROBE_RC" -ne 0 ]; then
    echo "⚠️ [WARN] probe_hd.py exit=${PROBE_RC} — result_hd.m3u may be stale" | tee -a "$LOG"
fi

# Step 4: Format
echo "[4/4] Format using standard template..." | tee -a "$LOG"
python3 /scripts/iptv_format.py \
  "${CACHE_DIR}/result_hd.m3u" \
  "${CACHE_DIR}/result.m3u" \
  "${CACHE_DIR}/result.txt" 2>&1 | tee -a "$LOG"

# Step 4.5: 防退化保护 —— 新结果骤减时保留上一份列表
# 背景（2026-09-19）：清空 ffprobe 缓存后全量重测，1547/1551 源不可达，
# 列表从 88 个频道直接跌到 2 个。IPTV 源集体失效、或探测环境异常（网络/NAT）时，
# 宁可保留一份还能用的旧列表，也不能把它清空 —— 播放器那边会直接变砖。
NEW_CNT=$(grep -c "#EXTINF" "${CACHE_DIR}/result.m3u" 2>/dev/null || echo 0)
if [ -f "${CACHE_DIR}/result.m3u.lastknown" ]; then
    OLD_CNT=$(grep -c "#EXTINF" "${CACHE_DIR}/result.m3u.lastknown" 2>/dev/null || echo 0)
    if [ "$OLD_CNT" -ge 20 ] && [ "$NEW_CNT" -lt $((OLD_CNT / 2)) ]; then
        echo "  [GUARD] 结果骤减 ${OLD_CNT} -> ${NEW_CNT} 频道，判定为源集体不可达，保留上一份列表" | tee -a "$LOG"
        cp "${CACHE_DIR}/result.m3u.lastknown" "${CACHE_DIR}/result.m3u"
        [ -f "${CACHE_DIR}/result_hd.m3u.lastknown" ] && cp "${CACHE_DIR}/result_hd.m3u.lastknown" "${CACHE_DIR}/result_hd.m3u"
        NEW_CNT=$OLD_CNT
    fi
fi
# 记录本次结果供下次比较（只有扛过保护的才成为新的基线）
cp "${CACHE_DIR}/result.m3u" "${CACHE_DIR}/result.m3u.lastknown" 2>/dev/null || true
[ -f "${CACHE_DIR}/result_hd.m3u" ] && cp "${CACHE_DIR}/result_hd.m3u" "${CACHE_DIR}/result_hd.m3u.lastknown" 2>/dev/null || true

# Step 5: EPG（节目单）—— 供本服务 /epg.xml 端点使用
# 先落到临时文件，转换成功才覆盖正式文件，避免下载/转换失败把可用数据清空
echo "[EPG] Updating epg.xml ..." | tee -a "$LOG"
EPG_RAW="/tmp/epg_raw.xml"
rm -f "$EPG_RAW"
python3 -c "
import urllib.request, shutil
try:
    req = urllib.request.Request('${EPG_SOURCE_URL}', headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=180) as r, open('${EPG_RAW}', 'wb') as f:
        shutil.copyfileobj(r, f)
    print('  downloaded OK')
except Exception as e:
    print(f'  download ERROR: {e}')
" 2>&1 | tee -a "$LOG"

if [ -s "$EPG_RAW" ]; then
    if python3 /scripts/epg_convert.py "${CACHE_DIR}/result.m3u" "$EPG_RAW" "${CACHE_DIR}/epg.xml.new" --stats 2>&1 | tee -a "$LOG"; then
        mv "${CACHE_DIR}/epg.xml.new" "${CACHE_DIR}/epg.xml"
        gzip -9 -c "${CACHE_DIR}/epg.xml" > "${CACHE_DIR}/epg.gz"
        echo "  epg.xml + epg.gz updated ($(du -h "${CACHE_DIR}/epg.xml" | cut -f1))" | tee -a "$LOG"
    else
        rm -f "${CACHE_DIR}/epg.xml.new"
        echo "  convert failed - kept old epg.xml" | tee -a "$LOG"
    fi
    rm -f "$EPG_RAW"
else
    echo "  no EPG data - kept old epg.xml" | tee -a "$LOG"
fi

# Staleness check: result_hd.m3u 超过 3 天未更新 → 告警
HD_TS=$(stat -c %Y "${CACHE_DIR}/result_hd.m3u" 2>/dev/null || echo 0)
NOW_TS=$(date +%s)
if [ "$HD_TS" -gt 0 ]; then
    AGE_DAYS=$(( (NOW_TS - HD_TS) / 86400 ))
    if [ "$AGE_DAYS" -ge 3 ]; then
        echo "⚠️ [WARN] result_hd.m3u is ${AGE_DAYS} days old — probe phase likely failed!" | tee -a "$LOG"
    fi
fi

M3U_CNT=$(grep -c "#EXTINF" "${CACHE_DIR}/result.m3u" 2>/dev/null || echo 0)
echo "=== Done → ${M3U_CNT} HD channels ===" | tee -a "$LOG"
