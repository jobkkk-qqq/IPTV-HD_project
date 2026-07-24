#!/usr/bin/env python3
"""Static IPTV source server - serves cached Guovin/iptv-api files"""
import http.server
import os
import sys

PORT = int(os.environ.get("PORT", "3568"))
CACHE_DIR = os.environ.get("CACHE_DIR", "/data")

class CacheHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.rstrip("/") or "/"
        
        # Map paths to files
        file_map = {
            "/": "result.m3u",       # Root returns M3U (PotPlayer compat)
            "/txt": "result.txt",
            "/m3u": "result.m3u",
            "/result.txt": "result.txt",
            "/result.m3u": "result.m3u",
            "/tv.txt": "result.txt",
            "/tv.m3u": "result.m3u",
        }
        
        filename = file_map.get(path)
        if filename:
            filepath = os.path.join(CACHE_DIR, filename)
            if os.path.exists(filepath):
                content_type = "audio/x-mpegurl; charset=utf-8" if filename.endswith(".m3u") else "text/plain; charset=utf-8"
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
                f"M3U:  /m3u     ({m3u_channels} channels)\n"
                f"TXT:  /txt     ({txt_channels} channels)\n"
            )
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
    print(f"  TXT: http://192.168.1.111:{PORT}/txt")
    print(f"  M3U: http://192.168.1.111:{PORT}/m3u")
    server.serve_forever()
