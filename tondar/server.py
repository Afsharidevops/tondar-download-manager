"""Local HTTP API used by the browser extension (127.0.0.1 only).

Web pages cannot use it: every request must carry the X-Tondar-Client header
(which forces a CORS pre-flight that we never approve) and requests whose
Origin is a normal http(s) web site are rejected.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION
from .qt import QtCore, Signal
from .media import probe_media, MediaError


class Bridge(QtCore.QObject):
    """Signals delivered to the GUI thread."""
    download_requested = Signal(dict)
    media_download_requested = Signal(dict)
    links_requested = Signal(list)
    activate_requested = Signal(str)


class ApiServer:
    def __init__(self, settings, bridge, cache):
        self.settings = settings
        self.bridge = bridge
        self.media_cache = cache       # url -> probe result (shared with GUI)
        self.httpd = None

    def start(self):
        port = int(self.settings["api_port"])
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _allowed(self):
                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(("chrome-extension://", "moz-extension://")):
                    return False
                return self.headers.get("X-Tondar-Client") == "1"

            def _json(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):           # never approve pre-flights from web pages
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                if not self._allowed():
                    return self._json(403, {"error": "forbidden"})
                if self.path == "/ping":
                    s = server.settings
                    return self._json(200, {
                        "app": "tondar", "version": VERSION,
                        "capture_extensions": s["capture_extensions"],
                        "capture_min_size_kb": s["capture_min_size_kb"],
                        "media_panel": s["media_panel_enabled"],
                    })
                self._json(404, {"error": "not found"})

            def do_POST(self):
                if not self._allowed():
                    return self._json(403, {"error": "forbidden"})
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    data = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    return self._json(400, {"error": "bad json"})
                if self.path == "/download":
                    if not str(data.get("url", "")).startswith(("http://", "https://", "ftp://")):
                        return self._json(400, {"error": "bad url"})
                    server.bridge.download_requested.emit(data)
                    return self._json(200, {"ok": True})
                if self.path == "/links":
                    links = [l for l in data.get("links", []) if isinstance(l, dict)]
                    server.bridge.links_requested.emit(links)
                    return self._json(200, {"ok": True})
                if self.path == "/media/formats":
                    url = data.get("url", "")
                    try:
                        res = server.media_cache.get(url) or probe_media(url, server.settings)
                        server.media_cache[url] = res
                        return self._json(200, res)
                    except MediaError as e:
                        return self._json(200, {"error": str(e)})
                    except Exception as e:  # noqa: BLE001
                        return self._json(200, {"error": f"{type(e).__name__}: {e}"})
                if self.path == "/media/download":
                    server.bridge.media_download_requested.emit(data)
                    return self._json(200, {"ok": True})
                self._json(404, {"error": "not found"})

        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError as e:
            print(f"API port {port} busy: {e}")
            return False
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return True

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
