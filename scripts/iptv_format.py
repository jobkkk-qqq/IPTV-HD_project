#!/usr/bin/env python3
"""
IPTV M3U 格式标准化（双环境兼容版）
- 替换为 3566 同款干净文件头（含 catchup）
- 去 emoji 分组
- 去重：同名同组只保留第一个
- 移除 🕘️更新时间 垃圾条目
- 双输出：M3U + TXT

用法（三参数，兼容 sync.sh 的调用方式）:
  python3 iptv_format.py <input.m3u> [output.m3u] [output.txt]
无参数时默认从 DATA_DIR 读 result_hd.m3u → result.m3u/result.txt

路径解析：
- 容器内（CACHE_DIR=/data）：路径以 /data 为准
- 宿主机（无 CACHE_DIR）：默认 /novel/DATA/AppData/iptv-hd/data
- 显式传入的参数优先，绝不硬编码覆盖
"""
import re
import os
import sys

# 双环境路径：CACHE_DIR 环境变量优先（容器内 sync.sh 设置），否则宿主机默认
BASE_DIR = os.environ.get("CACHE_DIR", "/novel/DATA/AppData/iptv-hd/data")
SERVER_IP = os.environ.get("IPTV_SERVER_IP", "192.168.1.111")
PORT = os.environ.get("IPTV_PORT", "3568")

# emoji → 中文分组映射
GROUP_MAP = {
    "📺央视频道": "央视",
    "📡卫视频道": "卫视",
    "💰央视付费频道": "付费",
    "☘️广东频道": "广东",
    "☘️浙江频道": "浙江",
    "☘️北京频道": "北京",
    "☘️上海频道": "上海",
    "☘️江苏频道": "江苏",
    "☘️山东频道": "山东",
    "☘️陕西频道": "陕西",
    "☘️河南频道": "河南",
    "☘️海南频道": "海南",
    "☘️广西频道": "广西",
    "☘️福建频道": "福建",
    "☘️湖南频道": "湖南",
    "☘️湖北频道": "湖北",
    "☘️四川频道": "四川",
    "☘️重庆频道": "重庆",
    "☘️天津频道": "天津",
    "☘️河北频道": "河北",
    "☘️山西频道": "山西",
    "☘️辽宁频道": "辽宁",
    "☘️吉林频道": "吉林",
    "☘️黑龙江频道": "黑龙江",
    "☘️安徽频道": "安徽",
    "☘️江西频道": "江西",
    "☘️云南频道": "云南",
    "☘️贵州频道": "贵州",
    "☘️甘肃频道": "甘肃",
    "☘️青海频道": "青海",
    "☘️宁夏频道": "宁夏",
    "☘️内蒙古频道": "内蒙古",
    "☘️新疆频道": "新疆",
    "☘️西藏频道": "西藏",
    "🌊港·澳·台": "港澳台",
    "🎬电影频道": "电影",
    "🏀体育频道": "体育",
    "🎵音乐频道": "音乐",
    "🎮游戏频道": "游戏",
    "🪁动画频道": "动画",
    "🏛经典剧场": "剧场",
    "🕘️更新时间": None,  # 移除该组
}

# 3566 同款文件头
M3U_HEADER = (
    '#EXTM3U '
    f'x-tvg-url="http://{SERVER_IP}:{PORT}/playback.xml" '
    'catchup="append" '
    'catchup-source="?playbackbegin=${(b)yyyyMMddHHmmss}&playbackend=${(e)yyyyMMddHHmmss}"'
)


def clean_group(group_title):
    """将 emoji 分组名转为中文"""
    for emoji_name, clean_name in GROUP_MAP.items():
        if emoji_name == group_title:
            return clean_name
    # 尝试部分匹配
    for emoji_name, clean_name in GROUP_MAP.items():
        if emoji_name in group_title or group_title in emoji_name:
            return clean_name
    return group_title


def parse_m3u(content):
    """解析 M3U，返回 (header_line, list of (extinf, url))"""
    lines = content.strip().split('\n')
    header = lines[0] if lines[0].startswith('#EXTM3U') else M3U_HEADER

    entries = []
    i = 1 if lines[0].startswith('#EXTM3U') else 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF'):
            extinf = line
            if i + 1 < len(lines):
                url = lines[i + 1].strip()
                entries.append((extinf, url))
                i += 2
                continue
        i += 1
    return header, entries


def deduplicate(entries):
    """去重：同名同组只保留第一个"""
    seen = set()
    result = []
    for extinf, url in entries:
        # 提取 tvg-name 和 group-title
        name_m = re.search(r'tvg-name="([^"]*)"', extinf)
        group_m = re.search(r'group-title="([^"]*)"', extinf)
        name = name_m.group(1) if name_m else ""
        group = group_m.group(1) if group_m else ""
        key = (name, group)
        if key not in seen:
            seen.add(key)
            result.append((extinf, url))
    return result


def filter_clean(entries):
    """移除垃圾条目（🕘️更新时间组、空名称等）"""
    result = []
    for extinf, url in entries:
        group_m = re.search(r'group-title="([^"]*)"', extinf)
        group = group_m.group(1) if group_m else ""
        name_m = re.search(r'tvg-name="([^"]*)"', extinf)
        name = name_m.group(1) if name_m else ""

        # 移除更新时间组
        if '更新时间' in group or '更新' in name:
            continue
        # 移除空名称
        if not name.strip():
            continue
        # 移除纯日期作为名称的
        if re.match(r'^\d{4}-\d{2}-\d{2}', name):
            continue
        result.append((extinf, url))
    return result


def clean_extinf(extinf):
    """清理 EXTINF 行：替换 emoji 分组名"""
    def replace_group(m):
        old = m.group(1)
        new = clean_group(old)
        if new is None:
            return 'group-title="__REMOVE__"'
        return f'group-title="{new}"'

    extinf = re.sub(r'group-title="([^"]*)"', replace_group, extinf)
    return extinf


def build_m3u(header, entries):
    """生成 M3U 内容"""
    lines = [header]
    for extinf, url in entries:
        extinf_clean = clean_extinf(extinf)
        if '__REMOVE__' in extinf_clean:
            continue
        lines.append(extinf_clean)
        lines.append(url)
    return '\n'.join(lines)


def build_txt(entries):
    """生成 TXT 内容（Diyp/百川格式: 频道名,url）"""
    lines = []
    for extinf, url in entries:
        name_m = re.search(r'group-title="([^"]*)"', extinf)
        display_m = re.search(r',([^,]*)$', extinf)
        group = name_m.group(1) if name_m else ""
        display = display_m.group(1).strip() if display_m else ""
        group_clean = clean_group(group)
        if group_clean is None:
            continue
        lines.append(f"{display},{url}")
    return '\n'.join(lines)


def main():
    # 三参数兼容：input [output.m3u] [output.txt]（sync.sh 就是这么调的）
    if len(sys.argv) >= 2:
        input_path = sys.argv[1]
    else:
        input_path = os.path.join(BASE_DIR, "result_hd.m3u")
        if not os.path.exists(input_path):
            input_path = os.path.join(BASE_DIR, "result.m3u")

    if len(sys.argv) >= 3:
        m3u_path = sys.argv[2]
    else:
        m3u_path = os.path.join(BASE_DIR, "result.m3u")

    if len(sys.argv) >= 4:
        txt_path = sys.argv[3]
    else:
        txt_path = os.path.join(BASE_DIR, "result.txt")

    if not os.path.exists(input_path):
        print(f"输入文件不存在: {input_path}")
        sys.exit(1)

    print(f"读取: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    header, entries = parse_m3u(content)
    print(f"解析到 {len(entries)} 条")

    entries = filter_clean(entries)
    print(f"过滤后: {len(entries)} 条")

    entries = deduplicate(entries)
    print(f"去重后: {len(entries)} 条")

    # 用 3566 同款文件头
    header = M3U_HEADER

    # 输出 M3U
    m3u_content = build_m3u(header, entries)
    with open(m3u_path, 'w', encoding='utf-8') as f:
        f.write(m3u_content)
    print(f"M3U 输出: {m3u_path} ({len(entries)} 条, {len(m3u_content)} bytes)")

    # 输出 TXT
    txt_content = build_txt(entries)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(txt_content)
    print(f"TXT 输出: {txt_path} ({len(txt_content)} bytes)")

    print("完成！")


if __name__ == '__main__':
    main()
