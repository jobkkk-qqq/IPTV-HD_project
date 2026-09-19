#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPG 源适配器：把外部 EPG 的 channel id 重写成本列表的 tvg-id。

为什么需要：
  51zmt（老张的EPG）更新及时（当天数据、1MB、2 秒下完），但频道用数字 id：
      <channel id="1"><display-name>CCTV1</display-name>
  而本项目的列表用 tvg-id="CCTV-1"（带连字符）。播放器按 id 严格匹配，
  对不上就显示不出节目单。

做法：
  规范化比对 EPG 的 display-name 与列表的 tvg-name（忽略大小写与所有非字母数字汉字字符，
  于是 "CCTV1" == "CCTV-1" == "cctv 1"），建立 旧id → 列表 tvg-id 映射，
  重写 <channel>/<programme> 的 id；未匹配上的频道整块丢弃（顺带把 1MB 瘦身到数百 KB）。

用法：
  python3 epg_convert.py <result.m3u> <输入epg.xml> <输出epg.xml>
  可加第 4 参数 --stats 打印匹配统计
"""

import re
import sys


def norm(s: str) -> str:
    """规范化频道名：小写 + 去掉非字母数字汉字字符，但保留 '+'。

    保留 '+' 很关键：51zmt 里 CCTV5 与 CCTV5+ 是两个频道，
    若剥掉 '+' 两者会撞成同一个 id。
    """
    return re.sub(r"[^0-9a-z\u4e00-\u9fff+]+", "", s.lower())


def build_name_index(m3u_path: str) -> dict:
    """从 M3U 列表建立 规范化频道名 → tvg-id 索引。"""
    idx = {}
    with open(m3u_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "tvg-id=" not in line:
                continue
            m_id = re.search(r'tvg-id="([^"]*)"', line)
            if not m_id or not m_id.group(1):
                continue
            tid = m_id.group(1)
            m_name = re.search(r'tvg-name="([^"]*)"', line)
            if m_name and m_name.group(1):
                idx.setdefault(norm(m_name.group(1)), tid)
            idx.setdefault(norm(tid), tid)
            # 也允许用节目单显示名匹配 tvg-id 本身
    return idx


def convert(m3u_path: str, src_path: str, out_path: str, stats: bool = False) -> dict:
    name2id = build_name_index(m3u_path)

    with open(src_path, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # ① 解析 channel 定义，决定保留哪些、id 怎么改（同一目标 id 只保留一次）
    id_map = {}
    kept_channels = []
    used_ids = set()
    chan_pat = re.compile(
        r'<channel\s+id="([^"]*)"[^>]*>\s*<display-name[^>]*>([^<]*)</display-name>\s*</channel>',
        re.S,
    )
    for m in chan_pat.finditer(content):
        old_id, disp = m.group(1), m.group(2).strip()
        target = name2id.get(norm(disp))
        if not target:
            continue
        id_map[old_id] = target
        if target in used_ids:
            continue  # 多个源频道映射到同一列表 id → 只取第一个
        used_ids.add(target)
        kept_channels.append(
            f'  <channel id="{target}">\n    <display-name lang="zh">{disp}</display-name>\n  </channel>'
        )

    if not id_map:
        raise SystemExit("ERROR: 没有任何频道匹配上（列表与 EPG 的命名规范差异过大）")

    # ② programme：只保留匹配到的频道，id 换成列表用的 id
    #    注意 channel 属性可能出现在任意位置（51zmt 放在属性末尾）
    kept_prog = []
    prog_pat = re.compile(r'<programme\s+([^>]*?)>\s*(.*?)\s*</programme>', re.S)
    for m in prog_pat.finditer(content):
        attrs, body = m.group(1), m.group(2)
        m_ch = re.search(r'channel="([^"]*)"', attrs)
        if not m_ch:
            continue
        new_ch = id_map.get(m_ch.group(1))
        if not new_ch:
            continue
        new_attrs = re.sub(r'channel="[^"]*"', f'channel="{new_ch}"', attrs)
        kept_prog.append(f'  <programme {new_attrs}>\n    {body.strip()}\n  </programme>')

    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">\n'
        '<tv generator-info-name="epg_convert (51zmt → 本列表 tvg-id 映射)">\n'
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(kept_channels))
        f.write("\n")
        f.write("\n".join(kept_prog))
        f.write("\n</tv>\n")

    result = {
        "channels_total": len(chan_pat.findall(content)) if False else content.count("<channel "),
        "channels_kept": len(kept_channels),
        "programmes_kept": len(kept_prog),
        "lines_in_index": len(name2id),
    }
    if stats:
        print(f"  列表索引条目: {result['lines_in_index']}")
        print(f"  保留频道: {result['channels_kept']} / EPG 总频道 {result['channels_total']}")
        print(f"  保留节目条目: {result['programmes_kept']}")
    return result


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    show = "--stats" in sys.argv
    convert(sys.argv[1], sys.argv[2], sys.argv[3], stats=show)


if __name__ == "__main__":
    main()
