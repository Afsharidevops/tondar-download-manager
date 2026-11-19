"""Import / export of download lists.

Formats
* .txt   - one address per line (any text: every http/https/ftp URL found is used)
* .ef2   - IDM export file, so lists move between Windows IDM and Tondar:
               <
               https://host/file.zip
               referer: https://host/page
               User-Agent: Mozilla/5.0 ...
               >
* .json  - Tondar list (file names, folders, descriptions, video formats ...)
Cookies are never written to export files.
"""
import json
import os
import re
import time

from . import VERSION
from .models import KIND_MEDIA

URL_RE = re.compile(r"(?:https?|ftp)://[^\s'\"<>]+", re.I)
JSON_FIELDS = ("url", "filename", "save_dir", "category", "description", "referer", "user_agent",
               "size", "kind", "media_format", "media_title", "page_url")


def detect_format(path, head=""):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".ef2", ".json", ".txt"):
        return ext[1:]
    head = head.lstrip()
    if head.startswith("{"):
        return "json"
    if head.startswith("<"):
        return "ef2"
    return "txt"


# ---------------------------------------------------------------- export
def export_items(items, path, fmt=None):
    fmt = fmt or detect_format(path)
    if fmt == "json":
        data = {"app": "tondar", "version": VERSION, "exported": int(time.time()),
                "downloads": [{k: getattr(it, k) for k in JSON_FIELDS} for it in items]}
        text = json.dumps(data, indent=2, ensure_ascii=False)
        newline = "\n"
    elif fmt == "ef2":
        blocks = []
        for it in items:
            lines = ["<", it.page_url if it.kind == KIND_MEDIA else it.url]
            if it.referer:
                lines.append(f"referer: {it.referer}")
            if it.user_agent:
                lines.append(f"User-Agent: {it.user_agent}")
            lines.append(">")
            blocks.append("\r\n".join(lines))
        text = "\r\n".join(blocks) + "\r\n"
        newline = ""
    else:
        text = "\n".join((it.page_url if it.kind == KIND_MEDIA else it.url) for it in items) + "\n"
        newline = "\n"
    with open(path, "w", encoding="utf-8", newline=newline or None) as f:
        f.write(text)
    return len(items)


# ---------------------------------------------------------------- import
def import_file(path):
    """Return a list of link dicts: {url, filename?, referer?, user_agent?, ...}."""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and "://" not in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    fmt = detect_format(path, text[:200])
    if fmt == "json":
        return parse_json(text)
    if fmt == "ef2":
        return parse_ef2(text)
    return parse_txt(text)


def parse_txt(text):
    """Plain URLs anywhere in the text, plus "file-name|url" lines (name chosen by the user)."""
    seen, out = set(), []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = ""
        if "|" in line:
            left, right = line.split("|", 1)
            if URL_RE.match(right.strip()) and not URL_RE.search(left):
                name, line = os.path.basename(left.strip()), right.strip()
        for u in URL_RE.findall(line):
            u = u.rstrip(").,;]")
            if u not in seen:
                seen.add(u)
                out.append({"url": u, "filename": name} if name else {"url": u})
                name = ""
    return out


def parse_ef2(text):
    out = []
    for block in re.findall(r"<\s*\r?\n(.*?)\r?\n\s*>", text, re.S):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines or "://" not in lines[0]:
            continue
        link = {"url": lines[0]}
        for ln in lines[1:]:
            if ":" not in ln:
                continue
            k, v = ln.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k == "referer":
                link["referer"] = v
            elif k == "user-agent":
                link["user_agent"] = v
            elif k in ("filename", "file name"):
                link["filename"] = os.path.basename(v)
            elif k == "cookie":
                link["cookies"] = v
        out.append(link)
    return out


def parse_json(text):
    data = json.loads(text)
    rows = data.get("downloads", data) if isinstance(data, dict) else data
    out = []
    for d in rows:
        if isinstance(d, str):
            d = {"url": d}
        if not isinstance(d, dict) or not URL_RE.match(str(d.get("url", ""))):
            continue
        out.append({k: d[k] for k in JSON_FIELDS if k in d and d[k] not in (None, "")})
    return out
