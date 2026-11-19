"""Tiny HTTP server with Range support and optional throttling, for tests."""
import http.server
import os
import re
import sys
import time
import threading


def make_handler(root, ranges=True, throttle=0):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            import urllib.parse; path = os.path.join(root, urllib.parse.unquote(self.path.lstrip("/").split("?")[0]))
            if not os.path.isfile(path):
                self.send_error(404)
                return
            size = os.path.getsize(path)
            start, end = 0, size - 1
            rng = self.headers.get("Range")
            status = 200
            if ranges and rng:
                m = re.match(r"bytes=(\d+)-(\d*)", rng)
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                status = 206
            self.send_response(status)
            self.send_header("Content-Length", str(end - start + 1))
            if path.endswith(".html"):
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif path.endswith(".mp4"):
                self.send_header("Content-Type", "video/mp4")
            else:
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(path))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if ranges:
                self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                try:
                    while left > 0:
                        chunk = f.read(min(32768, left))
                        self.wfile.write(chunk)
                        left -= len(chunk)
                        if throttle:
                            time.sleep(len(chunk) / throttle)
                except (BrokenPipeError, ConnectionResetError):
                    pass
    return H


def serve(root, port, ranges=True, throttle=0):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(root, ranges, throttle))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


if __name__ == "__main__":
    serve(sys.argv[1], int(sys.argv[2]))
    while True:
        time.sleep(3600)
