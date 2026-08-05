#!/usr/bin/env python3
"""Probe IPTV URLs with ffprobe, 15s timeout, mark dead links."""
import json, re, os, sys, urllib.request, subprocess, concurrent.futures, time
from urllib.parse import urlparse
from collections import Counter

_BASE = os.environ.get('CACHE_DIR', '/data')
CACHE_FILE = f'{_BASE}/resolution_cache.json'
FILTERED_M3U = f'{_BASE}/result.m3u'
OUTPUT_M3U = f'{_BASE}/result_hd.m3u'
OUTPUT_TXT = f'{_BASE}/result_hd.txt'

HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"}
TIMEOUT = 15  # seconds per URL

# Load cache
cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        cache = json.load(f)
print(f"Cache loaded: {len(cache)} URLs", flush=True)

# Parse filtered M3U
entries = []
cur = None
with open(FILTERED_M3U, encoding='utf-8') as f:
    for line in f:
        line = line.rstrip('\r\n')
        if line.startswith('#EXTINF'):
            cur = line
        elif line.startswith('http') and cur:
            entries.append((cur, line))
            cur = None
print(f"Entries: {len(entries)}", flush=True)

# Unique uncached URLs
seen = set()
to_test = []
for _, url in entries:
    if url not in seen:
        seen.add(url)
        if url not in cache:
            to_test.append(url)
print(f"To probe: {len(to_test)} URLs", flush=True)

def _probe_ts(ts_url, orig_url):
    """Download a TS segment and ffprobe its real resolution. Returns (orig_url, result)."""
    try:
        req2 = urllib.request.Request(ts_url, headers=HEADERS)
        with urllib.request.urlopen(req2, timeout=TIMEOUT) as r:
            data = r.read(524288)

        if len(data) < 500:
            return (orig_url, {"height": 0, "note": "ts_too_small"})

        tmp = '/tmp/_probe.ts'
        with open(tmp, 'wb') as f:
            f.write(data)

        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', tmp],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return (orig_url, {"height": 0, "note": "ffprobe_fail"})

        info = json.loads(result.stdout)
        for s in info.get('streams', []):
            if s.get('codec_type') == 'video':
                h, w = s.get('height', 0), s.get('width', 0)
                return (orig_url, {"height": h, "width": w, "note": f"{w}x{h}"})
        return (orig_url, {"height": 0, "note": "no_video_stream"})
    except Exception:
        return (orig_url, {"height": 0, "note": "ts_fetch_err"})


def probe_url(url):
    """Probe a single URL (connect + find M3U8 content)"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            content = r.read().decode('utf-8', errors='replace')
        
        if '#EXTM3U' in content or '#EXT-X' in content:
            # Find TS segment
            ts_lines = [l for l in content.split('\n') if '.ts' in l and not l.startswith('#')]
            if not ts_lines:
                subs = [l for l in content.split('\n') if '.m3u8' in l and not l.startswith('#')]
                if subs:
                    # Adaptive HLS: probe the highest variant instead of assuming 1080
                    sub_url = subs[0].strip()
                    if not sub_url.startswith('http'):
                        base = url.rsplit('/', 1)[0]
                        if '?' in base: base = base.split('?')[0]
                        sub_url = f"{base}/{sub_url}"
                    try:
                        req3 = urllib.request.Request(sub_url, headers=HEADERS)
                        with urllib.request.urlopen(req3, timeout=TIMEOUT) as r3:
                            sub_content = r3.read().decode('utf-8', errors='replace')
                        sub_ts = [l for l in sub_content.split('\n') if '.ts' in l and not l.startswith('#')]
                        if sub_ts:
                            ts_url = sub_ts[0].strip()
                            if not ts_url.startswith('http'):
                                sub_base = sub_url.rsplit('/', 1)[0]
                                ts_url = f"{sub_base}/{ts_url}"
                            return _probe_ts(ts_url, url)
                        # variant playlist may have resolution in #EXT-X-STREAM-INF
                        m = re.search(r'#EXT-X-STREAM-INF:[^\n]*RESOLUTION=(\d+)x(\d+)', sub_content)
                        if m:
                            return (url, {"height": int(m.group(2)), "width": int(m.group(1)),
                                          "note": f"adaptive_{m.group(1)}x{m.group(2)}"})
                        return (url, {"height": 0, "note": "adaptive_no_ts"})
                    except Exception:
                        return (url, {"height": 0, "note": "adaptive_err"})
                return (url, {"height": 0, "note": "no_ts"})
            
            # Try to download and ffprobe a TS segment
            ts_rel = ts_lines[0].strip()
            base = url.rsplit('/', 1)[0]
            if '?' in base: base = base.split('?')[0]
            ts_url = f"{base}/{ts_rel}" if not ts_rel.startswith('http') else ts_rel
            return _probe_ts(ts_url, url)
        else:
            return (url, {"height": 0, "note": "not_hls"})
    except urllib.error.HTTPError as e:
        code = e.code
        if code in (301, 302, 303, 307, 308):
            return (url, {"height": 0, "note": f"redirect_{code}"})
        return (url, {"height": 0, "note": f"HTTP{code}"})
    except urllib.error.URLError:
        return (url, {"height": 0, "note": "timeout"})
    except Exception as ex:
        return (url, {"height": 0, "note": str(type(ex).__name__)[:15]})

hd_found = 0
dead = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(probe_url, url): url for url in to_test}
    for i, future in enumerate(concurrent.futures.as_completed(futures)):
        url, result = future.result()
        cache[url] = result
        
        if result["height"] >= 1080:
            hd_found += 1
            sys.stdout.write(f"  [{i+1}/{len(to_test)}] ✅ {result['note']:15s} {url[:60]}\n")
        else:
            dead += 1
            if result["note"] not in ("domain_unreachable",):
                sys.stdout.write(f"  [{i+1}/{len(to_test)}] ❌ {result['note']:15s} {url[:60]}\n")
        
        sys.stdout.flush()
        
        # Save cache every 20 results
        if (i+1) % 20 == 0:
            with open(CACHE_FILE, 'w') as f:
                json.dump(cache, f)

# Final save
with open(CACHE_FILE, 'w') as f:
    json.dump(cache, f)

# Filter ≥1080p
kept = []
for extinf, url in entries:
    result = cache.get(url, {})
    if result.get("height", 0) >= 1080:
        kept.append((extinf, url))

# Deduplicate by channel name
seen_names = set()
deduped = []
for extinf, url in kept:
    name = re.search(r'tvg-name="([^"]+)"', extinf)
    name = name.group(1) if name else extinf.split(',')[-1].strip()
    if name not in seen_names:
        seen_names.add(name)
        deduped.append((extinf, url))

# Write M3U
with open(OUTPUT_M3U, 'w', encoding='utf-8') as f:
    f.write('#EXTM3U\n#PLAYLIST: IPTV 1080P+ (ffprobe-verified)\n')
    for extinf, url in deduped:
        f.write(extinf + '\n' + url + '\n')

# Write TXT grouped
with open(OUTPUT_TXT, 'w', encoding='utf-8') as f:
    cg = None
    for extinf, url in deduped:
        g = re.search(r'group-title="([^"]+)"', extinf)
        gn = g.group(1) if g else "其他"
        if gn != cg:
            f.write(f'{gn},#genre#\n')
            cg = gn
        name = re.search(r'tvg-name="([^"]+)"', extinf)
        name = name.group(1) if name else extinf.split(',')[-1].strip()
        f.write(f'{name},{url}\n')

# Stats
total_reachable = sum(1 for v in cache.values() if v.get("height", 0) > 0)
total_hd = sum(1 for v in cache.values() if v.get("height", 0) >= 1080)
print(f"\n{'='*50}", flush=True)
print(f"Cache total: {len(cache)} URLs", flush=True)
print(f"Reachable: {total_reachable}", flush=True)
print(f"Dead/timeout: {len(cache) - total_reachable}", flush=True)
print(f"≥1080p URLs: {total_hd}", flush=True)
print(f"Kept channels: {len(deduped)}", flush=True)
print(f"Saved: {OUTPUT_M3U}", flush=True)

# Groups
groups = Counter()
for extinf, url in deduped:
    g = re.search(r'group-title="([^"]+)"', extinf)
    groups[g.group(1) if g else "其他"] += 1
print(f"\nGroups ({len(groups)}):", flush=True)
for g, c in groups.most_common():
    print(f"  {g}: {c}", flush=True)
