import hashlib
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.range_server import serve  # noqa: E402
from tondar.engine import HttpDownloader, SpeedLimiter, probe  # noqa: E402
from tondar.models import DownloadItem  # noqa: E402

SETTINGS = {"max_connections": 8, "retries": 3, "timeout": 10, "proxy": "",
            "use_system_proxy": False, "user_agent": "test"}

root = tempfile.mkdtemp()
data = os.urandom(20 * 1024 * 1024 + 12345)
with open(os.path.join(root, "f.bin"), "wb") as f:
    f.write(data)
want = hashlib.sha256(data).hexdigest()
serve(root, 18081, ranges=True, throttle=3_000_000)   # 3 MB/s per connection
serve(root, 18082, ranges=False)


def run(port, limit=0, pause_after=None):
    out = tempfile.mkdtemp()
    it = DownloadItem(url=f"http://127.0.0.1:{port}/f.bin", filename="f.bin", save_dir=out)
    done = threading.Event()
    result = {}

    def cb(eng, status, err):
        result["status"], result["err"] = status, err
        done.set()
    lim = SpeedLimiter(lambda: limit)
    t0 = time.time()
    eng = HttpDownloader(it, SETTINGS, lim, cb)
    eng.start()
    if pause_after:
        time.sleep(pause_after)
        eng.stop()
        done.wait(30)
        print("  paused:", result, "segments", len(it.segments), "downloaded", it.downloaded)
        assert result["status"] == "stopped"
        done.clear()
        eng = HttpDownloader(it, SETTINGS, lim, cb)
        eng.start()
    snap_max = 0
    while not done.wait(0.2):
        snap_max = max(snap_max, len(eng.snapshot()))
    dt = time.time() - t0
    assert result["status"] == "completed", result
    got = hashlib.sha256(open(it.path, "rb").read()).hexdigest()
    assert got == want, "hash mismatch"
    print(f"  ok in {dt:.1f}s, max segments seen {snap_max}")
    return dt


print("probe:", probe("http://127.0.0.1:18081/f.bin"))
print("segmented (server throttled 3MB/s per connection):")
dt = run(18081)
assert dt < 4, "segmentation should beat single-connection 7s"
print("pause + resume:")
run(18081, pause_after=0.4)
print("no range support (single connection):")
run(18082)
print("global speed limit 4 MB/s:")
dt = run(18081, limit=4 * 1024 * 1024)
assert 4.0 < dt < 7.5, dt
print("ALL ENGINE TESTS PASSED")
