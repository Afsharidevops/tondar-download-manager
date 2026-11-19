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
                if self.path == "/media/resolve":
                    return self._json(200, server.resolve(data))
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

    # ------------------------------------------------------------------
    def resolve(self, data):
        """Everything downloadable on a page, for the in-page panel.

        page    - yt-dlp on the page URL (knows ~1800 sites, plus generic <video>/embeds)
        streams - HLS/DASH playlists seen in the tab, resolved to qualities by yt-dlp
        files   - direct video/audio files seen in the tab, with real size and name
        Returns {"title", "entries": [{url, format, label, size, approx, kind}], "error"}
        """
        from concurrent.futures import ThreadPoolExecutor
        from .engine import probe as http_probe

        page = data.get("page", "")
        referer = data.get("referer") or page
        cookies = data.get("cookies", "")
        streams = [s for s in data.get("streams", []) if isinstance(s, str)][:6]
        files = [f for f in data.get("files", []) if isinstance(f, str)][:12]
        s = self.settings

        def media(url, ref):
            if url in self.media_cache:
                return self.media_cache[url]
            res = probe_media(url, s, referer=ref, cookies=cookies)
            self.media_cache[url] = res
            return res

        def file_info(url):
            h = {"User-Agent": s["user_agent"], "Referer": referer}
            if cookies:
                h["Cookie"] = cookies
            return http_probe(url, h, s["proxy"], s["use_system_proxy"], 15)

        with ThreadPoolExecutor(max_workers=6) as pool:
            fut_page = pool.submit(media, page, "") if page else None
            fut_streams = [(u, pool.submit(media, u, referer)) for u in streams]
            fut_files = [(u, pool.submit(file_info, u)) for u in files]
            errors = []
            page_res = None
            if fut_page:
                try:
                    page_res = fut_page.result()
                except Exception as e:  # noqa: BLE001
                    errors.append(str(e))
            entries = []
            title = data.get("title") or ""
            if page_res and page_res.get("options"):
                title = page_res.get("title") or title
                for o in page_res["options"]:
                    entries.append({"url": page, "format": o["id"], "label": o["label"], "size": o.get("size", 0),
                                    "approx": o.get("approx", False), "kind": "media"})
            else:
                seen = {}
                for u, f in fut_streams:
                    try:
                        res = f.result()
                    except Exception as e:  # noqa: BLE001
                        errors.append(str(e))
                        continue
                    for o in res.get("options", []):
                        e = {"url": u, "format": o["id"], "label": o["label"], "size": o.get("size", 0),
                             "approx": o.get("approx", False), "kind": "media", "referer": referer,
                             "height": o.get("height", 0), "type": o.get("type")}
                        # several playlists usually carry the same qualities: keep one per label,
                        # preferring the one with a size
                        old = seen.get(o["label"])
                        if old is None or (not old["size"] and e["size"]):
                            seen[o["label"]] = e
                found = list(seen.values())
                # a master playlist already lists every quality: drop the bare variant playlists
                if any(e["height"] for e in found):
                    found = [e for e in found if e["height"] or e["type"] != "video"]
                entries += sorted(found, key=lambda e: (e["type"] != "video", -(e["height"] or 0), -(e["size"] or 0)))
                for u, f in fut_files:
                    try:
                        info = f.result()
                    except Exception as e:  # noqa: BLE001
                        errors.append(str(e))
                        continue
                    ctype = (info.get("content_type") or "").lower()
                    if ctype.startswith(("text/", "image/")):
                        continue
                    entries.append({"url": u, "format": None, "label": info["filename"], "size": info["size"],
                                    "approx": False, "kind": "file", "referer": referer})
        out = {"title": title, "entries": entries}
        if not entries:
            out["error"] = errors[0] if errors else "No downloadable video found on this page"
        return out

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
