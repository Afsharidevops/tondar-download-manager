#!/usr/bin/env python3
"""Stand-in for tdl in tests: same command line, no Telegram."""
import json, os, sys, time
a = sys.argv[1:]
def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default
store = opt("--storage", "").split("path=")[-1]
authed = os.path.exists(os.path.join(store, "authed"))
if "version" in a:
    print("Version: 0.20.4\nCommit: fake"); sys.exit(0)
if "login" in a:
    os.makedirs(store, exist_ok=True); open(os.path.join(store, "authed"), "w").write("1")
    print("Login successfully! ID: 1, Username: test"); sys.exit(0)
if not authed:
    print("\x1b[31mError: not authorized. please login first\x1b[0m"); sys.exit(1)
if a[:0] or "ls" in a:
    print("[]"); sys.exit(0)
if "export" in a:
    out = opt("-o")
    doc = lambda mid, name, size, mime, dur: {"id": mid, "type": "message", "file": name, "date": 1763650000 + mid,
        "text": f"🔥 سریال شمشیر و سکوت\nقسمت {mid}\nکیفیت 720p",
        "raw": {"ID": mid, "Media": {"Flags": 1, "Document": {"ID": 9, "FileReference": "AAA=", "MimeType": mime, "Size": size,
                "Thumbs": [{"Type": "m", "W": 320, "H": 180, "Size": 9999}],
                "Attributes": [{"Duration": dur, "W": 1280, "H": 720}, {"FileName": name}]}}}}
    msgs = [doc(11, "5771234.mp4", 300000, "video/mp4", 4155.5), doc(12, "Sword.and.Silence.S01E02.mp4", 200000, "video/mp4", 3600),
            {"id": 13, "type": "message", "file": "13.jpg", "text": "poster",
             "raw": {"ID": 13, "Media": {"Photo": {"Sizes": [{"Type": "x", "W": 800, "H": 600, "Size": 54321}]}}}},
            doc(14, "song.mp3", 5000, "audio/mpeg", 200)]
    if opt("-T") == "id":
        lo = int(opt("-i").split(",")[0]); msgs = [m for m in msgs if m["id"] == lo]
    json.dump({"id": 777 if "-c" not in a else 1234567890, "messages": msgs}, open(out, "w"), ensure_ascii=False)
    print("done"); sys.exit(0)
if "dl" in a:
    d, name, url = opt("-d"), opt("--template"), opt("-u")
    if url is None:                                   # -f export list
        j = json.load(open(opt("-f"), encoding="utf-8"))
        assert j["id"] and j["messages"][0]["type"] == "message"
        url = f"tg/{j['id']}/{j['messages'][0]['id']}"
    size = 300000 if url.endswith("/11") else 200000
    if url.endswith("/99"):
        print("\x1b[31mError: resolve message: message not found\x1b[0m"); sys.exit(1)
    tmp = os.path.join(d, name + ".tmp")
    with open(tmp, "wb") as f:
        for i in range(10):
            f.write(b"x" * (size // 10)); f.flush(); print(f"{name} ... {i*10}%", flush=True); time.sleep(0.3)
    os.rename(tmp, os.path.join(d, name)); sys.exit(0)
print("unknown", a); sys.exit(2)
