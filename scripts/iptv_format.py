#!/usr/bin/env python3
"""
IPTV M3U 格式标准化模板
用法: python3 iptv_format.py <输入.m3u> [输出.m3u] [输出.txt]
  默认输出: result_clean.m3u + result_clean.txt

将任何 M3U 格式化为统一风格:
  - 头部: #EXTM3U x-tvg-url="http://192.168.1.111:PORT/playback.xml" catchup=...
  - 分组: 去除 emoji 图标 (📺央视→央视, ☘️广东→广东 等)
  - 去重: 同名频道只保留第一个
  - 双输出: M3U + TXT (Diyp/百川格式)
"""

import re, sys, os as _os
from collections import Counter

# ========== 配置区：改这里 ==========
# 可通过环境变量覆盖
PORT = _os.environ.get('IPTV_PORT', "3568")
SERVER_IP = _os.environ.get('IPTV_SERVER_IP', "localhost")
_BASE = _os.environ.get('CACHE_DIR', '/data')
# ===================================

# Emoji → 干净分组的映射表
EMOJI_CLEAN = {
    "📺央视频道": "央视",     "📡卫视频道": "卫视",
    "💰央视付费频道": "付费", "☘️广东频道": "广东",
    "☘️浙江频道": "浙江",     "☘️北京频道": "北京",
    "☘️上海频道": "上海",     "☘️江苏频道": "江苏",
    "☘️陕西频道": "陕西",     "☘️河南频道": "河南",
    "☘️海南频道": "海南",     "☘️广西频道": "广西",
    "☘️福建频道": "福建",     "☘️湖南频道": "湖南",
    "☘️山东频道": "山东",     "☘️山西频道": "山西",
    "☘️安徽频道": "安徽",     "☘️黑龙江频道": "黑龙江",
    "☘️新疆频道": "新疆",     "🌊港·澳·台": "港澳台",
    "🎬电影频道": "电影",     "🎮游戏频道": "游戏",
    "🎵音乐频道": "音乐",     "🏀体育频道": "体育",
    "🏛经典剧场": "剧场",     "🪁动画频道": "动画",
}

def clean_group_name(name):
    """清理分组名: 去除 emoji"""
    if name in EMOJI_CLEAN:
        return EMOJI_CLEAN[name]
    # 兜底: 用正则去除所有 emoji
    cleaned = re.sub(
        r'[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F'
        r'\U0001F680-\U0001F6FF\u2600-\u27BF'
        r'\U0000FE00-\U0000FE0F\u00A9\u00AE'
        r'☘️💰🌊🎬🎮🎵🏀🏛🪁]', '', name
    ).strip()
    return cleaned if cleaned else name


def parse_m3u(filepath):
    """解析 M3U 文件, 返回 [(extinf, url), ...]"""
    entries = []
    cur = None
    with open(filepath, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n\r')
            if line.startswith('#EXTINF:'):
                cur = line
            elif line.startswith('http') and cur:
                entries.append((cur, line))
                cur = None
    return entries


def format_entries(entries):
    """
    标准化处理:
    1. 去除 emoji 分组名
    2. 同名频道去重 (保留第一个)
    3. 保留 tvg-id, tvg-name, tvg-logo
    """
    seen = set()
    output = []

    for extinf, url in entries:
        name = extinf.split(",")[-1].strip() if "," in extinf else ""
        if not name or name in seen:
            continue
        seen.add(name)

        # 提取字段
        tid = (re.search(r'tvg-id="([^"]*)"', extinf) or [None, name]).group(1)
        tvg_name = (re.search(r'tvg-name="([^"]*)"', extinf) or [None, name]).group(1)
        logo = (re.search(r'tvg-logo="([^"]*)"', extinf) or [None, ""]).group(1)
        grp = clean_group_name(
            (re.search(r'group-title="([^"]*)"', extinf) or [None, "其他"]).group(1)
        )

        output.append((tid, tvg_name, logo, grp, name, url))

    return output


def build_m3u(output, port=PORT, ip=SERVER_IP):
    """生成 3566 风格 M3U 内容"""
    header = (
        f'#EXTM3U x-tvg-url="http://{ip}:{port}/playback.xml"'
        f' catchup="append"'
        f' catchup-source="?playbackbegin=${{(b)yyyyMMddHHmmss}}'
        f'&playbackend=${{(e)yyyyMMddHHmmss}}"\n'
    )
    lines = [header]
    for tid, tname, logo, grp, cname, url in output:
        lines.append(
            f'#EXTINF:-1 tvg-id="{tid}" tvg-name="{tname}"'
            f' tvg-logo="{logo}" group-title="{grp}",{cname}'
        )
        lines.append(url)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_txt(output):
    """生成 Diyp/百川 格式 TXT 内容"""
    return "\n".join(f"{cname},{url}" for *_, cname, url in output) + "\n"


def main():
    # 解析参数
    input_file = sys.argv[1] if len(sys.argv) > 1 else f"{_BASE}/result_hd.m3u"
    output_m3u = sys.argv[2] if len(sys.argv) > 2 else f"{_BASE}/result.m3u"
    output_txt = sys.argv[3] if len(sys.argv) > 3 else f"{_BASE}/result.txt"

    if not os.path.exists(input_file):
        print(f"❌ 输入文件不存在: {input_file}")
        sys.exit(1)

    # 解析 → 格式化
    entries = parse_m3u(input_file)
    print(f"解析: {len(entries)} 条")

    output = format_entries(entries)
    print(f"格式化 (去重后): {len(output)} 个频道")

    # 写 M3U
    m3u_content = build_m3u(output)
    with open(output_m3u, 'w', encoding='utf-8') as f:
        f.write(m3u_content)
    print(f"✅ M3U: {output_m3u}")

    # 写 TXT
    txt_content = build_txt(output)
    with open(output_txt, 'w', encoding='utf-8') as f:
        f.write(txt_content)
    print(f"✅ TXT: {output_txt}")

    # 统计分组
    groups = Counter(g for *_, g, _, _ in output)
    print(f"\n分组 ({len(groups)}):")
    for g, c in sorted(groups.items()):
        print(f"  {g}: {c}")


if __name__ == '__main__':
    main()
