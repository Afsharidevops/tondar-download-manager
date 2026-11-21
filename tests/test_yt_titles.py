"""YouTube link titles from anchor text: thumbnail duration, metadata, duplicates."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tondar.ui.dialogs import LinksDialog as D
assert D._yt_title("18:35") == ""
assert D._yt_title("watch") == ""
assert D._yt_title("1:02:03 Long video") == "Long video"
assert D._yt_title("21:57My Experience Switching") == "My Experience Switching"
bad = "The PERFECT Mini Home ServerHardware Haven1.7M • 1y ago"
good = "The PERFECT Mini Home Server"
assert D._title_score(good) > D._title_score(bad) > D._title_score("")
d = D.__new__(D); d.expand = []
rows = d._prepare([
    {"url": "https://www.youtube.com/watch?v=CzCoOkFtHFw&pp=x", "text": "18:35"},
    {"url": "https://www.youtube.com/watch?v=CzCoOkFtHFw", "text": bad},
    {"url": "https://www.youtube.com/watch?v=CzCoOkFtHFw&t=1", "text": good},
    {"url": "https://www.youtube.com/watch?v=-WEW0_XulSA", "text": ""},
])
vids = [r for r in rows if r.get("yt") == "video"]
assert [r["title"] for r in vids] == [good, ""], [r["title"] for r in vids]
print("ALL YT TITLE TESTS PASSED")
