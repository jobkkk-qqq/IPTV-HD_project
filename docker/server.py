#!/usr/bin/env python3
"""Static IPTV source server - serves cached Guovin/iptv-api files"""
import http.server
import os
import sys

PORT = int(os.environ.get("PORT", "3568"))
CACHE_DIR = os.environ.get("CACHE_DIR", "/data")

# ── 可选本地扩展：第三方源合并（不进 git 仓库）──
# docker/merged_local.py 是本机特有的整合逻辑（把 3566 那套咪咕源并进本站列表），
# 由 .gitignore 排除。别人 clone 后没有这个文件 → 合并端点自动不存在，
# 根路径退回只给本站 HD 源，其余功能完全不受影响，所以这里用 try/except 而非硬依赖。
try:
    import merged_local
    HAS_MERGED = True
except ImportError:  # 别人 clone 时没有这个文件 → 合并端点自动消失，其余功能不受影响
    merged_local = None
    HAS_MERGED = False


class CacheHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.rstrip("/") or "/"

        # 路径 → 文件映射。注意 / 、/m3u、/tv.m3u 在合并可用时会被上面的合并路由接管
        # （返回合并结果），不可用时退回这里的 HD 列表。
        file_map = {
            "/": "result.m3u",
            "/m3u": "result.m3u",
            "/tv.m3u": "result.m3u",
            "/hd": "result.m3u",          # 明确只要本站筛选出的 HD 源
            "/hd.m3u": "result.m3u",
            "/txt": "result.txt",
            "/result.txt": "result.txt",
            "/result.m3u": "result.m3u",
            "/tv.txt": "result.txt",
            "/epg.xml": "epg.xml",        # 本站 EPG（XMLTV）—— sync.sh 定期更新
            "/epg.gz": "epg.gz",          # 压缩版（省流量；播放器需支持 gzip EPG）
        }

        # ── 合并列表（需本地扩展）：第三方源 + 本站 HD 源 ──
        # 根路径也走合并 —— 打开域名就该看到全部频道；只要本站 HD 源请用 /hd。
        if merged_local is not None and path in ("/", "/m3u", "/tv.m3u", "/merged", "/all"):
            req_host = self.headers.get("Host") or "localhost"
            # 经 Cloudflare 隧道进来时带 X-Forwarded-Proto: https，
            # 据此把列表里的地址写成 https —— 否则外网播放器拿到 http 明文地址可能拒播。
            scheme = "https" if (self.headers.get("X-Forwarded-Proto") or "").lower() == "https" else "http"
            try:
                content = merged_local.build_merged(req_host, scheme).encode("utf-8")
            except Exception as e:
                self.send_error(500, f"merged build failed: {e}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/x-mpegurl; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Disposition", 'inline; filename="merged.m3u"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # ── 合并 EPG（需本地扩展）──
        if merged_local is not None and path == "/merged.xml":
            xml = merged_local.build_merged_epg()
            if xml is None:
                self.send_error(503, "merged EPG unavailable")
                return
            content = xml.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # ── 第三方源转发（需本地扩展）：/migu/<id> → 302 到真实流地址 ──
        # 这样播放器只认本站一个域名；302 之后由播放器直连源站拉流，
        # 既不经本站中转、也不经 Cloudflare（不产生大流量）。
        if merged_local is not None and path.startswith("/migu/"):
            try:
                status, hdrs, body = merged_local.proxy_path(path)
            except Exception as e:
                self.send_error(502, f"upstream error: {e}")
                return

            location = hdrs.get("Location")
            if location:
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return

            self.send_response(status)
            self.send_header("Content-Type", hdrs.get("Content-Type", "application/octet-stream"))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        filename = file_map.get(path)
        if filename:
            filepath = os.path.join(CACHE_DIR, filename)
            if os.path.exists(filepath):
                if filename.endswith(".m3u"):
                    content_type = "audio/x-mpegurl; charset=utf-8"
                elif filename.endswith(".xml"):
                    content_type = "application/xml; charset=utf-8"
                elif filename.endswith(".gz"):
                    content_type = "application/gzip"
                else:
                    content_type = "text/plain; charset=utf-8"
                with open(filepath, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Disposition", f'inline; filename="{filename}"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        # Status page
        if path == "/status":
            txt_channels = 0
            m3u_channels = 0
            txt_file = os.path.join(CACHE_DIR, "result.txt")
            m3u_file = os.path.join(CACHE_DIR, "result.m3u")
            if os.path.exists(txt_file):
                txt_channels = sum(1 for l in open(txt_file) if ",http" in l)
            if os.path.exists(m3u_file):
                m3u_channels = sum(1 for l in open(m3u_file) if "#EXTINF" in l)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            status = (
                f"IPTV HD Server\n"
                f"Port: {PORT}\n"
                f"HD:   /hd      ({m3u_channels} channels, 本站筛选)\n"
            )
            if HAS_MERGED:
                status += "Merged: / , /m3u  (+ 第三方源, EPG 见 /merged.xml)\n"
            else:
                status += "Merged: 未启用（缺 merged_local.py 本地扩展）\n"
            status += f"TXT:  /txt     ({txt_channels} channels)\n"
            if m3u_channels == 0:
                status += "\nNo data yet. Run: docker exec iptv-hd bash /scripts/sync.sh\n"
            self.wfile.write(status.encode())
            return

        self.send_error(404, "Not found")

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {self.client_address[0]} - {fmt%args}\n")

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PORT), CacheHandler)
    print(f"IPTV Cache Server on port {PORT}")
    print(f"  TXT:    http://192.168.1.111:{PORT}/txt")
    print(f"  HD M3U: http://192.168.1.111:{PORT}/hd")
    if HAS_MERGED:
        print(f"  Merged: http://192.168.1.111:{PORT}/  (含第三方源)")
    else:
        print("  Merged: 未启用（缺 merged_local.py）")
    server.serve_forever()
