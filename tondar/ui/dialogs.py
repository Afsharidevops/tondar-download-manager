"""All dialogs: Add URL, Download File Info, progress, complete, options, scheduler."""
import os
import re
import subprocess
import threading
import time
import urllib.parse

from .. import APP_NAME, VERSION, APP_URL
from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal, exec_
from ..config import GENERAL, BIN_DIR
from ..models import (human_size, human_speed, human_eta, COMPLETED, ERROR, PAUSED,
                      DOWNLOADING, CONNECTING, KIND_MEDIA, KIND_HTTP)
from ..manager import MAIN_QUEUE
from .. import media
from .. import osutil
from . import icons
from .widgets import SegmentBar

MEDIA_SITE_RE = re.compile(
    r"^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|twitch\.tv|"
    r"instagram\.com|facebook\.com|fb\.watch|twitter\.com|x\.com|tiktok\.com|soundcloud\.com|"
    r"aparat\.com|namasha\.com|telewebion\.com|bilibili\.com|reddit\.com|v\.redd\.it|"
    r"bandcamp\.com|mixcloud\.com|rumble\.com|odysee\.com|ok\.ru|vk\.com|streamable\.com)/", re.I)


def is_media_page(url):
    return bool(MEDIA_SITE_RE.match(url or ""))


def open_path(path):
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


def open_folder(path):
    """Open the containing folder and select the file when the file manager supports it."""
    from ..osutil import open_folder as _open
    if os.path.exists(path) and _open(path):
        return
    open_path(os.path.dirname(path) if os.path.isfile(path) else path)


def _form_label(text):
    lab = QtWidgets.QLabel(text)
    lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lab


# ===========================================================================
class AddUrlDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, url=""):
        super().__init__(parent)
        self.setWindowTitle("Enter new address to download")
        self.setWindowIcon(icons.icon("add"))
        self.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        ic = QtWidgets.QLabel()
        ic.setPixmap(icons.pixmap("add", 40))
        top.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        form = QtWidgets.QGridLayout()
        form.addWidget(QtWidgets.QLabel("Address"), 0, 0)
        self.url = QtWidgets.QComboBox()
        self.url.setEditable(True)
        clip = QtWidgets.QApplication.clipboard().text().strip()
        if not url and re.match(r"^(https?|ftp)://\S+$", clip):
            url = clip
        self.url.setEditText(url)
        form.addWidget(self.url, 0, 1)
        self.auth = QtWidgets.QCheckBox("Use authorization")
        form.addWidget(self.auth, 1, 1)
        self.login = QtWidgets.QLineEdit()
        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        form.addWidget(QtWidgets.QLabel("Login"), 2, 0)
        form.addWidget(self.login, 2, 1)
        form.addWidget(QtWidgets.QLabel("Password"), 3, 0)
        form.addWidget(self.password, 3, 1)
        for w in (self.login, self.password):
            w.setEnabled(False)
        self.auth.toggled.connect(self.login.setEnabled)
        self.auth.toggled.connect(self.password.setEnabled)
        top.addLayout(form, 1)
        lay.addLayout(top)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        if not re.match(r"^(https?|ftp)://", self.url.currentText().strip(), re.I):
            QtWidgets.QMessageBox.warning(self, APP_NAME, "Please enter a valid http://, https:// or ftp:// address.")
            return
        self.accept()

    def value(self):
        url = self.url.currentText().strip()
        headers = {}
        if self.auth.isChecked() and self.login.text():
            import base64
            cred = f"{self.login.text()}:{self.password.text()}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(cred).decode()
        return url, headers


# ===========================================================================
class FileInfoDialog(QtWidgets.QDialog):
    """IDM-style "Download File Info" window shown before every download."""
    PROBING = "Getting file information..."

    def __init__(self, manager, settings, request, parent=None):
        super().__init__(parent)
        self.m, self.s, self.req = manager, settings, dict(request)
        self.info = None
        self.media_info = request.get("media_info")
        self.is_media = bool(request.get("media")) or is_media_page(request.get("url"))
        self.result_item = None
        self.token = object()
        self.setWindowTitle("Download File Info")
        self.setWindowIcon(icons.icon("app"))
        self.setMinimumWidth(620)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        lay = QtWidgets.QHBoxLayout(self)
        self.type_icon = QtWidgets.QLabel()
        self.type_icon.setPixmap(icons.pixmap(GENERAL, 64))
        self.type_icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.type_icon)
        right = QtWidgets.QVBoxLayout()
        lay.addLayout(right, 1)

        g = QtWidgets.QGridLayout()
        g.setColumnStretch(1, 1)
        self.url = QtWidgets.QLineEdit(self.req.get("url", ""))
        self.url.setReadOnly(True)
        g.addWidget(_form_label("URL"), 0, 0)
        g.addWidget(self.url, 0, 1, 1, 2)

        self.category = QtWidgets.QComboBox()
        for c in list(self.s["categories"].keys()) + [GENERAL]:
            self.category.addItem(icons.icon(c), c)
        g.addWidget(_form_label("Category"), 1, 0)
        g.addWidget(self.category, 1, 1, 1, 2)

        self.quality_lbl = _form_label("Quality")
        self.quality = QtWidgets.QComboBox()
        g.addWidget(self.quality_lbl, 2, 0)
        g.addWidget(self.quality, 2, 1, 1, 2)

        self.save_as = QtWidgets.QComboBox()
        self.save_as.setEditable(True)
        browse = QtWidgets.QToolButton()
        browse.setText("...")
        browse.clicked.connect(self._browse)
        g.addWidget(_form_label("Save As"), 3, 0)
        g.addWidget(self.save_as, 3, 1)
        g.addWidget(browse, 3, 2)
        self.remember = QtWidgets.QCheckBox("Remember this path for \"General\" category")
        g.addWidget(self.remember, 4, 1, 1, 2)
        self.desc = QtWidgets.QLineEdit(self.req.get("description", ""))
        g.addWidget(_form_label("Description"), 5, 0)
        g.addWidget(self.desc, 5, 1, 1, 2)
        right.addLayout(g)

        self.size_lbl = QtWidgets.QLabel(self.PROBING)
        f = self.size_lbl.font()
        f.setBold(True)
        self.size_lbl.setFont(f)
        right.addWidget(self.size_lbl)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        self.later_btn = QtWidgets.QPushButton("Download Later")
        self.start_btn = QtWidgets.QPushButton("Start Download")
        self.start_btn.setDefault(True)
        cancel = QtWidgets.QPushButton("Cancel")
        for b in (self.later_btn, self.start_btn, cancel):
            b.setMinimumWidth(120)
            btns.addWidget(b)
        right.addLayout(btns)
        self.later_btn.clicked.connect(lambda: self._finish(start=False))
        self.start_btn.clicked.connect(lambda: self._finish(start=True))
        cancel.clicked.connect(self.reject)
        self.category.currentTextChanged.connect(self._category_changed)
        self.quality.currentIndexChanged.connect(self._quality_changed)

        self._set_filename(self.req.get("filename") or self._guess_name())
        self._show_quality(False)
        self.m.probe_finished.connect(self._on_probe)
        if self.media_info:
            QtCore.QTimer.singleShot(0, lambda: self._on_probe(self.token, self.media_info, None))
        else:
            self._probe()

    # -------------------------------------------------------------
    def _guess_name(self):
        path = urllib.parse.urlsplit(self.req.get("url", "")).path
        return urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1]) or "download"

    def _show_quality(self, show):
        self.quality.setVisible(show)
        self.quality_lbl.setVisible(show)

    def _probe(self):
        self.start_btn.setEnabled(not self.is_media)
        self.later_btn.setEnabled(not self.is_media)
        self.size_lbl.setText("Looking for video/audio on this page..." if self.is_media else self.PROBING)
        headers = {"User-Agent": self.req.get("user_agent") or self.s["user_agent"]}
        if self.req.get("referer"):
            headers["Referer"] = self.req["referer"]
        if self.req.get("cookies"):
            headers["Cookie"] = self.req["cookies"]
        headers.update(self.req.get("headers") or {})
        self.m.probe_async(self.token, self.req["url"], headers, media=self.is_media)

    def _on_probe(self, token, info, error):
        if token is not self.token:
            return
        self.start_btn.setEnabled(True)
        self.later_btn.setEnabled(True)
        if error:
            if self.is_media:
                self.size_lbl.setText("Could not read video: " + error[:200])
                self.start_btn.setEnabled(False)
                self.later_btn.setEnabled(False)
            else:
                self.size_lbl.setText("Size: unknown  (" + error[:120] + ")")
            return
        if self.is_media or "options" in info:
            if self.req.get("title"):
                info = dict(info, title=self.req["title"])
            self.is_media = True
            self.media_info = info
            self.quality.blockSignals(True)
            self.quality.clear()
            pre = self.req.get("media_option")
            sel = 0
            for i, o in enumerate(info["options"]):
                size = (("~" if o.get("approx") else "") + human_size(o["size"])) if o.get("size") else ""
                self.quality.addItem(icons.icon("Music" if o["type"] != "video" else "Video"),
                                     f"{o['label']}" + (f"   ({size})" if size else ""), o)
                if pre and o["id"] == pre:
                    sel = i
            self.quality.setCurrentIndex(sel)
            self.quality.blockSignals(False)
            self._show_quality(True)
            self._quality_changed(sel)
            return
        # plain file
        self.info = info
        ctype = info.get("content_type", "")
        if ctype.startswith("text/html") and not self.req.get("forced_file"):
            # A web page, not a file: try to find a video on it
            self.is_media = True
            self._probe()
            return
        if not self.req.get("filename"):
            self._set_filename(info["filename"])
        size = info["size"]
        self.size_lbl.setText(f"Size: {human_size(size)}" if size > 0 else "Size: unknown")
        if not info["resumable"]:
            self.size_lbl.setText(self.size_lbl.text() + "      (resume not supported)")

    def _quality_changed(self, idx):
        o = self.quality.itemData(idx)
        if not o or not self.media_info:
            return
        name = media.media_filename(self.media_info["title"], o["ext"])
        cat = "Music" if o["type"] in ("audio", "mp3") else "Video"
        self.category.blockSignals(True)
        self.category.setCurrentText(cat)
        self.category.blockSignals(False)
        self.type_icon.setPixmap(icons.pixmap(cat, 64))
        self.save_as.setEditText(str(self.s.dir_for_category(cat) / name))
        self.remember.setText(f"Remember this path for \"{cat}\" category")
        self.size_lbl.setText(f"{self.media_info['title']}\nSize: "
                              + ((("about " if o.get("approx") else "") + human_size(o["size"]))
                                 if o.get("size") else "unknown"))

    def _set_filename(self, name):
        cat = self.s.category_for(name)
        self.category.blockSignals(True)
        self.category.setCurrentText(cat)
        self.category.blockSignals(False)
        self.type_icon.setPixmap(icons.pixmap(cat, 64))
        self.remember.setText(f"Remember this path for \"{cat}\" category")
        self.save_as.setEditText(str(self.s.dir_for_category(cat) / name))

    def _category_changed(self, cat):
        name = os.path.basename(self.save_as.currentText())
        self.save_as.setEditText(str(self.s.dir_for_category(cat) / name))
        self.type_icon.setPixmap(icons.pixmap(cat, 64))
        self.remember.setText(f"Remember this path for \"{cat}\" category")

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save As", self.save_as.currentText())
        if path:
            self.save_as.setEditText(path)

    def _finish(self, start):
        path = os.path.expanduser(self.save_as.currentText().strip())
        if not path or path.endswith("/"):
            return
        save_dir, filename = os.path.split(path)
        cat = self.category.currentText()
        if self.remember.isChecked():
            if self.s.get("use_category_folders") and cat != GENERAL:
                parent = os.path.dirname(save_dir) if os.path.basename(save_dir) == cat else save_dir
                self.s["download_dir"] = parent
            else:
                self.s["download_dir"] = save_dir
            self.s.save()
        common = dict(referer=self.req.get("referer", ""), cookies=self.req.get("cookies", ""),
                      user_agent=self.req.get("user_agent", ""), description=self.desc.text(),
                      headers=self.req.get("headers") or {})
        if self.is_media:
            o = self.quality.currentData()
            if not o:
                return
            it = self.m.new_item(self.req["url"], filename, save_dir, cat, kind=KIND_MEDIA,
                                 media_format=o["id"], media_title=self.media_info["title"],
                                 size=o.get("size") or -1, page_url=self.req["url"],
                                 cookie_jar=self.req.get("cookie_jar"), **common)
        else:
            it = self.m.new_item(self.req["url"], filename, save_dir, cat, kind=KIND_HTTP, **common)
            if self.info:
                it.size = self.info["size"]
                it.resumable = self.info["resumable"]
        self.result_item = it
        self.start_now = start
        self.accept()

    def done(self, r):
        try:
            self.m.probe_finished.disconnect(self._on_probe)
        except Exception:
            pass
        super().done(r)


# ===========================================================================
class ProgressDialog(QtWidgets.QDialog):
    """Per-download status window (status, speed, connection list, segment map)."""
    open_complete = Signal(str)
    refresh_requested = Signal(str)

    def __init__(self, manager, settings, item_id, parent=None):
        super().__init__(None)
        self.m, self.s, self.id = manager, settings, item_id
        self.setWindowIcon(icons.icon("app"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs)

        # --- status tab
        st = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(st)
        self.url_lbl = QtWidgets.QLabel()
        self.url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url_lbl.setWordWrap(False)
        sl.addWidget(self.url_lbl)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sl.addWidget(line)
        grid = QtWidgets.QGridLayout()
        self.vals = {}
        for r, key in enumerate(["Status", "File size", "Downloaded", "Transfer rate",
                                 "Time left", "Resume capability"]):
            grid.addWidget(QtWidgets.QLabel(key), r, 0)
            v = QtWidgets.QLabel()
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(v, r, 1)
            self.vals[key] = v
        grid.setColumnStretch(1, 1)
        sl.addLayout(grid)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        from . import theme
        self.bar.setFixedHeight(12 if theme.is_modern() else 22)
        sl.addWidget(self.bar)

        b = QtWidgets.QHBoxLayout()
        self.details_btn = QtWidgets.QPushButton("<< Hide details")
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.refresh_btn = QtWidgets.QPushButton("Refresh address…")
        self.refresh_btn.setVisible(False)
        self.refresh_btn.clicked.connect(lambda: self.refresh_requested.emit(self.id))
        for btn in (self.details_btn, self.pause_btn, self.cancel_btn, self.refresh_btn):
            btn.setAutoDefault(False)
        b.addWidget(self.details_btn)
        b.addStretch(1)
        b.addWidget(self.refresh_btn)
        b.addWidget(self.pause_btn)
        b.addWidget(self.cancel_btn)
        sl.addLayout(b)

        self.details = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(QtWidgets.QLabel("Start positions and download progress by connections"))
        self.segbar = SegmentBar()
        dl.addWidget(self.segbar)
        self.conns = QtWidgets.QTreeWidget()
        self.conns.setHeaderLabels(["N.", "Downloaded", "Info"])
        self.conns.setRootIsDecorated(False)
        self.conns.setColumnWidth(0, 40)
        self.conns.setColumnWidth(1, 120)
        self.conns.setMinimumHeight(140)
        dl.addWidget(self.conns)
        sl.addWidget(self.details)
        tabs.addTab(st, "Download status")

        # --- speed limiter tab
        sp = QtWidgets.QWidget()
        spl = QtWidgets.QFormLayout(sp)
        self.use_limit = QtWidgets.QCheckBox("Use speed limiter (applies to all downloads)")
        self.use_limit.setChecked(bool(self.s.get("speed_limit_enabled")))
        self.limit = QtWidgets.QSpinBox()
        self.limit.setRange(1, 10_000_000)
        self.limit.setSuffix(" KB/sec")
        self.limit.setValue(int(self.s.get("speed_limit_kbps") or 512))
        spl.addRow(self.use_limit)
        spl.addRow("Maximum download speed", self.limit)
        self.use_limit.toggled.connect(self._limit_changed)
        self.limit.valueChanged.connect(self._limit_changed)
        tabs.addTab(sp, "Speed Limiter")

        # --- on completion tab
        oc = QtWidgets.QWidget()
        ocl = QtWidgets.QVBoxLayout(oc)
        self.show_complete = QtWidgets.QCheckBox("Show download complete dialog")
        self.show_complete.setChecked(bool(self.s.get("show_complete_dialog")))
        self.open_when_done = QtWidgets.QCheckBox("Open the file when done")
        self.shutdown_when_done = QtWidgets.QCheckBox("Turn off computer when done")
        for w in (self.show_complete, self.open_when_done, self.shutdown_when_done):
            ocl.addWidget(w)
        ocl.addStretch(1)
        tabs.addTab(oc, "Options on completion")

        self.details_btn.clicked.connect(self._toggle_details)
        self.pause_btn.clicked.connect(self._pause_resume)
        self.cancel_btn.clicked.connect(self._cancel)
        self.m.item_updated.connect(self._on_update)
        self.m.item_finished.connect(self._on_finished)
        self.m.item_removed.connect(self._on_removed)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._refresh_conns)
        self.timer.start(700)
        self._refresh()
        self._refresh_conns()

    def _limit_changed(self, *_):
        self.s["speed_limit_enabled"] = self.use_limit.isChecked()
        self.s["speed_limit_kbps"] = self.limit.value()
        self.s.save()

    def _toggle_details(self):
        vis = not self.details.isVisible()
        self.details.setVisible(vis)
        self.details_btn.setText("<< Hide details" if vis else "Show details >>")
        QtCore.QTimer.singleShot(0, self.adjustSize)

    def _pause_resume(self):
        it = self.m.items.get(self.id)
        if not it:
            return
        if self.id in self.m.engines:
            self.m.stop(self.id)
        else:
            self.m.start(self.id)

    def _cancel(self):
        if self.id in self.m.engines:
            self.m.stop(self.id)
        self.close()

    def _on_update(self, item_id):
        if item_id == self.id:
            self._refresh()

    def _on_removed(self, item_id):
        if item_id == self.id:
            self.close()

    def _refresh(self):
        it = self.m.items.get(self.id)
        if not it:
            return
        pct = it.progress * 100
        self.setWindowTitle(f"{pct:.0f}% {it.filename}" if it.size > 0 else it.filename)
        self.url_lbl.setText(self.fontMetrics().elidedText(
            it.page_url or it.url, Qt.TextElideMode.ElideMiddle, 520))
        status = it.status
        if status == DOWNLOADING:
            status = "Receiving data..."
        elif status == CONNECTING:
            status = "Connecting..."
        elif status == ERROR:
            status = "Error: " + it.error
        self.vals["Status"].setText(status)
        self.vals["File size"].setText(human_size(it.size) if it.size > 0 else "Unknown")
        self.vals["Downloaded"].setText(f"{human_size(it.downloaded)} ( {pct:.2f} % )" if it.size > 0
                                        else human_size(it.downloaded))
        self.vals["Transfer rate"].setText(human_speed(it.speed))
        self.vals["Time left"].setText(human_eta(it.eta))
        self.vals["Resume capability"].setText("Yes" if (it.resumable or it.kind == KIND_MEDIA) else "No")
        self.bar.setValue(int(it.progress * 1000))
        running = self.id in self.m.engines
        self.refresh_btn.setVisible(it.status == ERROR or bool(it.refresh_wait))
        self.vals["Status"].setWordWrap(True)
        self.pause_btn.setText("Pause" if running else "Resume")
        self.pause_btn.setEnabled(it.status != COMPLETED)

    def _refresh_conns(self):
        it = self.m.items.get(self.id)
        eng = self.m.engines.get(self.id)
        if not it:
            return
        segs = eng.snapshot() if eng else [tuple(s) + (False,) for s in (it.segments or [])]
        self.segbar.update_state(it.size, segs, it.progress)
        self.conns.clear()
        if segs:
            n = 0
            for start, end, pos, active in segs:
                n += 1
                info = "Receiving data..." if active else ("Finished" if pos > end else "")
                QtWidgets.QTreeWidgetItem(self.conns, [str(n), human_size(pos - start), info])
        elif eng:
            QtWidgets.QTreeWidgetItem(self.conns, ["1", human_size(it.downloaded),
                                                   "Receiving data..." if it.kind == KIND_HTTP else
                                                   f"Video engine, {it.connections} parallel fragments"])

    def _on_finished(self, item_id, status):
        if item_id != self.id:
            return
        it = self.m.items.get(self.id)
        if status == COMPLETED and it:
            if self.open_when_done.isChecked():
                open_path(it.path)
            if self.shutdown_when_done.isChecked():
                from ..osutil import power
                power("shutdown")
            if self.show_complete.isChecked() and not self.open_when_done.isChecked():
                self.open_complete.emit(self.id)
            self.close()

    def closeEvent(self, e):
        for sig, slot in ((self.m.item_updated, self._on_update), (self.m.item_finished, self._on_finished),
                          (self.m.item_removed, self._on_removed)):
            try:
                sig.disconnect(slot)
            except Exception:
                pass
        super().closeEvent(e)


# ===========================================================================
class RefreshAddressDialog(QtWidgets.QDialog):
    """Give an unfinished download a new address and continue where it stopped
    (signed links expire, or stop working after the internet connection / IP changes)."""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.it = item
        self.open_page_clicked = False
        self.setWindowTitle("Refresh download address")
        self.setWindowIcon(icons.icon("app"))
        self.setMinimumWidth(640)
        lay = QtWidgets.QVBoxLayout(self)
        pct = f" ({item.progress * 100:.0f}% done)" if item.size > 0 else ""
        title = QtWidgets.QLabel(f"<b>{item.filename}</b>{pct}")
        title.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(title)
        hint = QtWidgets.QLabel(
            "Many sites give each download a temporary link. When it expires (or your internet connection "
            "changes) the server refuses it. Get a fresh link and the download continues from where it stopped:"
            "<ol><li><b>Open the page</b>, play the video / click the download link again, and choose the same "
            "file or quality in Tondar - it will offer to continue this download; or</li>"
            "<li>paste a new address below.</li></ol>")
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(hint)
        form = QtWidgets.QFormLayout()
        old = QtWidgets.QLineEdit(item.page_url or item.url)
        old.setReadOnly(True)
        old.setCursorPosition(0)
        form.addRow("Current address", old)
        self.new = QtWidgets.QLineEdit()
        self.new.setPlaceholderText("https://...")
        clip = QtWidgets.QApplication.clipboard().text().strip()
        if re.match(r"^(https?|ftp)://\S+$", clip) and clip != (item.page_url or item.url):
            self.new.setText(clip)
        form.addRow("New address", self.new)
        lay.addLayout(form)
        b = QtWidgets.QHBoxLayout()
        self.page = item.referer if re.match(r"^https?://", item.referer or "") else ""
        open_page = QtWidgets.QPushButton("Open the page in the browser")
        open_page.setEnabled(bool(self.page))
        open_page.setToolTip(self.page)
        open_page.clicked.connect(self._open_page)
        b.addWidget(open_page)
        b.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        ok = QtWidgets.QPushButton("Use new address && resume")
        ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._ok)
        b.addWidget(cancel)
        b.addWidget(ok)
        lay.addLayout(b)

    def _open_page(self):
        self.open_page_clicked = True
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.page))
        self.reject()

    def _ok(self):
        if not re.match(r"^(https?|ftp)://\S+$", self.new.text().strip()):
            QtWidgets.QMessageBox.warning(self, APP_NAME, "Please enter a valid address.")
            return
        self.accept()

    def value(self):
        return self.new.text().strip()


class CompleteDialog(QtWidgets.QDialog):
    def __init__(self, settings, item, parent=None):
        super().__init__(None)
        self.s, self.it = settings, item
        self.setWindowTitle("Download complete")
        self.setWindowIcon(icons.icon("finished"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumWidth(520)
        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QHBoxLayout()
        ic = QtWidgets.QLabel()
        ic.setPixmap(icons.pixmap(item.category, 48))
        head.addWidget(ic)
        t = QtWidgets.QLabel("<b>Download complete</b><br>"
                             f"Downloaded {human_size(item.size)}")
        head.addWidget(t, 1)
        lay.addLayout(head)
        g = QtWidgets.QFormLayout()
        addr = QtWidgets.QLineEdit(item.page_url or item.url)
        addr.setReadOnly(True)
        g.addRow("Address", addr)
        p = QtWidgets.QLineEdit(item.path)
        p.setReadOnly(True)
        g.addRow("The file saved as", p)
        lay.addLayout(g)
        b = QtWidgets.QHBoxLayout()
        o = QtWidgets.QPushButton("Open")
        ow = QtWidgets.QPushButton("Open with...")
        of = QtWidgets.QPushButton("Open folder")
        c = QtWidgets.QPushButton("Close")
        for w in (o, ow, of):
            b.addWidget(w)
        b.addStretch(1)
        b.addWidget(c)
        lay.addLayout(b)
        self.dont = QtWidgets.QCheckBox("Don't show this dialog again")
        lay.addWidget(self.dont)
        o.clicked.connect(lambda: (open_path(item.path), self.close()))
        of.clicked.connect(lambda: (open_folder(item.path), self.close()))
        ow.clicked.connect(self._open_with)
        c.clicked.connect(self.close)
        c.setDefault(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def _open_with(self):
        cmd, ok = QtWidgets.QInputDialog.getText(self, "Open with", "Program (e.g. vlc, gimp):")
        if ok and cmd.strip():
            subprocess.Popen([cmd.strip(), self.it.path])
            self.close()

    def closeEvent(self, e):
        if self.dont.isChecked():
            self.s["show_complete_dialog"] = False
            self.s.save()
        super().closeEvent(e)


# ===========================================================================
class OptionsDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None, ext_dir=""):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle(f"{APP_NAME} Configuration")
        self.setWindowIcon(icons.icon("options"))
        self.setMinimumSize(640, 480)
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        lay.addWidget(tabs)
        s = settings

        # General
        w = QtWidgets.QWidget()
        f = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(
            "<b>Browser integration</b><br>Install the Tondar extension to capture downloads "
            "and get the <i>Download this video</i> button on YouTube and other sites.<br><br>"
            "<b>Chrome / Chromium / Brave / Edge / Vivaldi:</b> open <code>chrome://extensions</code>, "
            "turn on <i>Developer mode</i>, click <i>Load unpacked</i> and choose:<br>"
            f"<code>{ext_dir}/chrome</code><br><br>"
            + ("<b>Firefox:</b> installed automatically (system policy). Restart Firefox once, "
               "then click the Tondar toolbar icon → <i>Allow access to all websites</i>."
               if osutil.IS_LINUX else
               "<b>Firefox:</b> click <i>Install in Firefox</i> below and confirm. Then click the Tondar "
               "toolbar icon → <i>Allow access to all websites</i>."))
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        f.addWidget(info)
        brow = QtWidgets.QHBoxLayout()
        open_ext = QtWidgets.QPushButton("Open extension folder")
        open_ext.clicked.connect(lambda: open_path(ext_dir))
        brow.addWidget(open_ext)
        self.xpi = os.path.join(ext_dir, "tondar-firefox-signed.xpi")
        ff = QtWidgets.QPushButton("Install in Firefox")
        ff.setEnabled(os.path.exists(self.xpi))
        ff.clicked.connect(self._install_firefox)
        brow.addWidget(ff)
        brow.addStretch(1)
        f.addLayout(brow)
        self.media_panel = QtWidgets.QCheckBox("Show \"Download this video\" panel on web players")
        self.media_panel.setChecked(s["media_panel_enabled"])
        self.clip = QtWidgets.QCheckBox("Monitor clipboard for download links")
        self.clip.setChecked(s["monitor_clipboard"])
        self.tray = QtWidgets.QCheckBox("Keep running in the system tray when the window is closed")
        self.tray.setChecked(s["close_to_tray"])
        self.fileinfo = QtWidgets.QCheckBox("Show \"Download File Info\" dialog before downloading")
        self.fileinfo.setChecked(s["show_file_info_dialog"])
        self.progress = QtWidgets.QCheckBox("Show download progress dialog")
        self.progress.setChecked(s["show_progress_dialog"])
        self.complete = QtWidgets.QCheckBox("Show download complete dialog")
        self.complete.setChecked(s["show_complete_dialog"])
        for x in (self.media_panel, self.clip, self.tray, self.fileinfo, self.progress, self.complete):
            f.addWidget(x)
        nh = QtWidgets.QHBoxLayout()
        nh.addWidget(QtWidgets.QLabel("Desktop notifications:"))
        self.notify = QtWidgets.QComboBox()
        for k, v in (("all", "All (completed and failed downloads)"), ("errors", "Errors only"),
                     ("none", "None")):
            self.notify.addItem(v, k)
        self.notify.setCurrentIndex(max(0, self.notify.findData(s.get("notifications", "all"))))
        nh.addWidget(self.notify)
        nh.addStretch(1)
        f.addLayout(nh)
        th = QtWidgets.QHBoxLayout()
        th.addWidget(QtWidgets.QLabel("Appearance:"))
        self.theme = QtWidgets.QComboBox()
        for k, v in (("auto", "Modern (follow system light/dark)"), ("light", "Modern light"),
                     ("dark", "Modern dark"), ("classic", "Classic")):
            self.theme.addItem(v, k)
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.get("theme", "auto"))))
        th.addWidget(self.theme)
        th.addStretch(1)
        f.addLayout(th)
        f.addStretch(1)
        tabs.addTab(w, "General")

        # File types
        w = QtWidgets.QWidget()
        f = QtWidgets.QVBoxLayout(w)
        f.addWidget(QtWidgets.QLabel("Automatically start downloading the following file types:"))
        self.exts = QtWidgets.QPlainTextEdit(" ".join(s["capture_extensions"]).upper())
        f.addWidget(self.exts)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(QtWidgets.QLabel("Don't capture files smaller than"))
        self.min_size = QtWidgets.QSpinBox()
        self.min_size.setRange(0, 1_000_000)
        self.min_size.setSuffix(" KB")
        self.min_size.setValue(s["capture_min_size_kb"])
        h.addWidget(self.min_size)
        h.addStretch(1)
        f.addLayout(h)
        tabs.addTab(w, "File Types")

        # Save to
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.base = QtWidgets.QLineEdit(str(s.base_dir()))
        bb = QtWidgets.QPushButton("Browse...")
        bb.clicked.connect(self._browse_dir)
        hb = QtWidgets.QHBoxLayout()
        hb.addWidget(self.base)
        hb.addWidget(bb)
        f.addRow("Default download directory", hb)
        self.catdirs = QtWidgets.QCheckBox("Save each category in its own sub-folder (Video, Music, ...)")
        self.catdirs.setChecked(s["use_category_folders"])
        f.addRow(self.catdirs)
        self.cat_table = QtWidgets.QTableWidget(0, 2)
        self.cat_table.setHorizontalHeaderLabels(["Category", "Extensions"])
        self.cat_table.horizontalHeader().setStretchLastSection(True)
        for cat, exts in s["categories"].items():
            r = self.cat_table.rowCount()
            self.cat_table.insertRow(r)
            self.cat_table.setItem(r, 0, QtWidgets.QTableWidgetItem(icons.icon(cat), cat))
            self.cat_table.setItem(r, 1, QtWidgets.QTableWidgetItem(" ".join(exts)))
        f.addRow(self.cat_table)
        tabs.addTab(w, "Save To")

        # Connection
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.maxconn = QtWidgets.QSpinBox()
        self.maxconn.setRange(1, 32)
        self.maxconn.setValue(s["max_connections"])
        f.addRow("Default max. connections number", self.maxconn)
        self.maxsim = QtWidgets.QSpinBox()
        self.maxsim.setRange(1, 20)
        self.maxsim.setValue(s["max_simultaneous"])
        f.addRow("Download files at the same time (queue)", self.maxsim)
        self.timeout = QtWidgets.QSpinBox()
        self.timeout.setRange(5, 600)
        self.timeout.setSuffix(" sec")
        self.timeout.setValue(s["timeout"])
        f.addRow("Connection timeout", self.timeout)
        self.retries = QtWidgets.QSpinBox()
        self.retries.setRange(0, 1000)
        self.retries.setValue(s["retries"])
        f.addRow("Number of retries", self.retries)
        self.ua = QtWidgets.QLineEdit(s["user_agent"])
        f.addRow("User-Agent", self.ua)
        self.port = QtWidgets.QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(s["api_port"])
        f.addRow("Browser extension port (restart needed)", self.port)
        tabs.addTab(w, "Connection")

        # Proxy
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.sysproxy = QtWidgets.QCheckBox("Use system proxy settings (http_proxy / https_proxy)")
        self.sysproxy.setChecked(s["use_system_proxy"])
        f.addRow(self.sysproxy)
        self.proxy = QtWidgets.QLineEdit(s["proxy"])
        self.proxy.setPlaceholderText("http://127.0.0.1:10809   or   socks5://127.0.0.1:10808")
        f.addRow("Manual proxy", self.proxy)
        f.addRow(QtWidgets.QLabel("SOCKS needs: sudo apt install python3-socks"))
        tabs.addTab(w, "Proxy / Socks")

        # Video
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        self.cookies = QtWidgets.QComboBox()
        self.cookies.addItems(["", "chrome", "chromium", "brave", "edge", "firefox", "opera", "vivaldi"])
        self.cookies.setCurrentText(s["ytdlp_cookies_browser"])
        f.addRow("Use cookies from browser (for age-restricted / private videos)", self.cookies)
        self.extra = QtWidgets.QLineEdit(s["ytdlp_extra_args"])
        f.addRow("Extra yt-dlp arguments", self.extra)
        self.tools_lbl = QtWidgets.QLabel()
        f.addRow("Video engine", self.tools_lbl)
        upd = QtWidgets.QPushButton("Install / Update yt-dlp and Deno")
        upd.clicked.connect(self._update_tools)
        f.addRow(upd)
        self.tools_log = QtWidgets.QPlainTextEdit()
        self.tools_log.setReadOnly(True)
        self.tools_log.setMaximumHeight(110)
        f.addRow(self.tools_log)
        tabs.addTab(w, "Video")
        self._refresh_tools()

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _install_firefox(self):
        cmd = osutil.firefox_command()
        if not cmd:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Firefox was not found. Open this file with Firefox to install the add-on:\n" + self.xpi)
            open_folder(self.xpi)
            return
        subprocess.Popen(cmd + [self.xpi], **osutil.subprocess_kwargs())

    def _refresh_tools(self):
        st = media.tools_status()
        def mark(ok):
            return "✔" if ok else "✘"
        self.tools_lbl.setText(
            f"yt-dlp {mark(st['yt-dlp'])} {st['yt-dlp-version']}    "
            f"Deno {mark(st['deno'])}    Node {mark(st['node'])}    ffmpeg {mark(st['ffmpeg'])}")

    def _update_tools(self):
        run_tools_update(self, self.s, self.tools_log, self._refresh_tools)

    def _browse_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Download directory", self.base.text())
        if d:
            self.base.setText(d)

    def _save(self):
        s = self.s
        s["media_panel_enabled"] = self.media_panel.isChecked()
        s["monitor_clipboard"] = self.clip.isChecked()
        s["close_to_tray"] = self.tray.isChecked()
        s["show_file_info_dialog"] = self.fileinfo.isChecked()
        s["show_progress_dialog"] = self.progress.isChecked()
        s["show_complete_dialog"] = self.complete.isChecked()
        s["notifications"] = self.notify.currentData()
        s["theme"] = self.theme.currentData()
        s["capture_extensions"] = sorted({e.lower().lstrip(".") for e in self.exts.toPlainText().split() if e})
        s["capture_min_size_kb"] = self.min_size.value()
        s["download_dir"] = self.base.text().strip()
        s["use_category_folders"] = self.catdirs.isChecked()
        cats = {}
        for r in range(self.cat_table.rowCount()):
            name = self.cat_table.item(r, 0).text().strip()
            exts = self.cat_table.item(r, 1).text().lower().split()
            if name:
                cats[name] = exts
        s["categories"] = cats
        s["max_connections"] = self.maxconn.value()
        s["max_simultaneous"] = self.maxsim.value()
        s["timeout"] = self.timeout.value()
        s["retries"] = self.retries.value()
        s["user_agent"] = self.ua.text().strip() or s["user_agent"]
        s["api_port"] = self.port.value()
        s["use_system_proxy"] = self.sysproxy.isChecked()
        s["proxy"] = self.proxy.text().strip()
        s["ytdlp_cookies_browser"] = self.cookies.currentText()
        s["ytdlp_extra_args"] = self.extra.text().strip()
        s.save()
        self.accept()


class _ToolsWorker(QtCore.QObject):
    log = Signal(str)
    done = Signal(str)


def run_tools_update(parent, settings, log_widget=None, on_done=None):
    w = _ToolsWorker(parent)
    if log_widget is not None:
        w.log.connect(log_widget.appendPlainText)

    def finished(err):
        if err:
            QtWidgets.QMessageBox.warning(parent, APP_NAME,
                                          "Could not update the video engine:\n" + err +
                                          "\n\nIf GitHub is blocked, set a proxy in Options > Proxy.")
        elif log_widget is None:
            QtWidgets.QMessageBox.information(parent, APP_NAME, "Video engine is up to date.")
        if on_done:
            on_done()
    w.done.connect(finished)

    def work():
        try:
            media.install_tools(settings, log=w.log.emit)
            w.done.emit("")
        except Exception as e:  # noqa: BLE001
            w.done.emit(str(e))
    threading.Thread(target=work, daemon=True).start()


# ===========================================================================
class SchedulerDialog(QtWidgets.QDialog):
    def __init__(self, manager, settings, parent=None):
        super().__init__(parent)
        self.m, self.s = manager, settings
        self.setWindowTitle("Scheduler")
        self.setWindowIcon(icons.icon("scheduler"))
        self.setMinimumSize(620, 460)
        sc = settings["scheduler"]
        lay = QtWidgets.QHBoxLayout(self)
        qlist = QtWidgets.QListWidget()
        qlist.addItem(QtWidgets.QListWidgetItem(icons.icon("queue"), MAIN_QUEUE))
        qlist.setCurrentRow(0)
        qlist.setMaximumWidth(170)
        lay.addWidget(qlist)
        right = QtWidgets.QVBoxLayout()
        lay.addLayout(right, 1)
        tabs = QtWidgets.QTabWidget()
        right.addWidget(tabs)

        w = QtWidgets.QWidget()
        f = QtWidgets.QVBoxLayout(w)
        self.enabled = QtWidgets.QCheckBox("Start download on schedule")
        self.enabled.setChecked(sc["enabled"])
        f.addWidget(self.enabled)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(QtWidgets.QLabel("At"))
        self.start_t = QtWidgets.QTimeEdit(QtCore.QTime.fromString(sc["start_time"] or "02:00", "HH:mm"))
        self.start_t.setDisplayFormat("HH:mm")
        h.addWidget(self.start_t)
        h.addStretch(1)
        f.addLayout(h)
        days = QtWidgets.QGroupBox("Daily")
        dl = QtWidgets.QGridLayout(days)
        self.days = []
        for i, d in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]):
            cb = QtWidgets.QCheckBox(d)
            cb.setChecked(i in sc["days"])
            dl.addWidget(cb, i // 4, i % 4)
            self.days.append(cb)
        f.addWidget(days)
        h = QtWidgets.QHBoxLayout()
        self.stop_en = QtWidgets.QCheckBox("Stop download at")
        self.stop_en.setChecked(bool(sc["stop_time"]))
        self.stop_t = QtWidgets.QTimeEdit(QtCore.QTime.fromString(sc["stop_time"] or "07:00", "HH:mm"))
        self.stop_t.setDisplayFormat("HH:mm")
        h.addWidget(self.stop_en)
        h.addWidget(self.stop_t)
        h.addStretch(1)
        f.addLayout(h)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(QtWidgets.QLabel("When done:"))
        self.on_finish = QtWidgets.QComboBox()
        for k, v in (("nothing", "Do nothing"), ("quit", f"Exit {APP_NAME}"),
                     ("suspend", "Suspend computer"), ("shutdown", "Turn off computer")):
            self.on_finish.addItem(v, k)
        self.on_finish.setCurrentIndex(max(0, self.on_finish.findData(sc.get("on_finish", "nothing"))))
        h.addWidget(self.on_finish)
        h.addStretch(1)
        f.addLayout(h)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(QtWidgets.QLabel("Download"))
        self.sim = QtWidgets.QSpinBox()
        self.sim.setRange(1, 20)
        self.sim.setValue(settings["max_simultaneous"])
        h.addWidget(self.sim)
        h.addWidget(QtWidgets.QLabel("files at the same time"))
        h.addStretch(1)
        f.addLayout(h)
        f.addStretch(1)
        tabs.addTab(w, "Schedule")

        w = QtWidgets.QWidget()
        f = QtWidgets.QVBoxLayout(w)
        self.files = QtWidgets.QTreeWidget()
        self.files.setHeaderLabels(["File name", "Size", "Status"])
        self.files.setRootIsDecorated(False)
        self.files.setColumnWidth(0, 280)
        f.addWidget(self.files)
        tabs.addTab(w, "Files in the queue")
        self._fill_files()

        b = QtWidgets.QHBoxLayout()
        start = QtWidgets.QPushButton(icons.icon("start_queue"), "Start now")
        stop = QtWidgets.QPushButton(icons.icon("stop_queue"), "Stop")
        apply_ = QtWidgets.QPushButton("Apply")
        close = QtWidgets.QPushButton("Close")
        for x in (start, stop):
            b.addWidget(x)
        b.addStretch(1)
        b.addWidget(apply_)
        b.addWidget(close)
        right.addLayout(b)
        start.clicked.connect(lambda: (self._apply(), self.m.start_queue()))
        stop.clicked.connect(self.m.stop_queue)
        apply_.clicked.connect(self._apply)
        close.clicked.connect(lambda: (self._apply(), self.accept()))

    def _fill_files(self):
        self.files.clear()
        for it in self.m.queued_items():
            QtWidgets.QTreeWidgetItem(self.files, [it.filename, human_size(it.size), it.status])

    def _apply(self):
        sc = self.s["scheduler"]
        sc["enabled"] = self.enabled.isChecked()
        sc["start_time"] = self.start_t.time().toString("HH:mm")
        sc["stop_time"] = self.stop_t.time().toString("HH:mm") if self.stop_en.isChecked() else ""
        sc["days"] = [i for i, cb in enumerate(self.days) if cb.isChecked()]
        sc["on_finish"] = self.on_finish.currentData()
        self.s["max_simultaneous"] = self.sim.value()
        self.s.save()


def about(parent):
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(f"About {APP_NAME}")
    box.setIconPixmap(icons.pixmap("app", 64))
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(
        f"<h3>{APP_NAME} {VERSION}</h3>"
        "<p>Segmented download accelerator for Ubuntu with browser integration "
        "and video grabbing (powered by yt-dlp).</p>"
        f"<p>GitHub: <a href='{APP_URL}'>{APP_URL.replace('https://', '')}</a><br>"
        f"Report a problem: <a href='{APP_URL}/issues'>Issues</a> · "
        f"Latest version: <a href='{APP_URL}/releases/latest'>Releases</a></p>"
        f"<p style='color:gray'>Helper tools folder: <code>{BIN_DIR}</code></p>")
    for lab in box.findChildren(QtWidgets.QLabel):
        lab.setOpenExternalLinks(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
    exec_(box)


# ===========================================================================
class _ProbeSignals(QtCore.QObject):
    result = Signal(int, object)          # row, info dict (or {"error": ...})


class _SortItem(QtWidgets.QTreeWidgetItem):
    """Sorts the Size column by bytes, everything else as text."""
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col == 1:
            return (self.data(1, Qt.ItemDataRole.UserRole) or -1) < (other.data(1, Qt.ItemDataRole.UserRole) or -1)
        return self.text(col).lower() < other.text(col).lower()


class LinksDialog(QtWidgets.QDialog):
    """'Download all links' / import window: probes every link for size and type."""
    COLS = ["File name", "Size", "Type", "Address"]
    WORKERS = 8

    def __init__(self, settings, links, parent=None, title="Download all links"):
        super().__init__(parent)
        from concurrent.futures import ThreadPoolExecutor
        from ..engine import probe
        self.s = settings
        self.expand = []                 # playlist/channel pages to list with yt-dlp
        self.links = self._prepare(links)
        self.touched = set()
        self.n_done = 0
        self.n_top = 0                   # rows that came from the page's own playlist (kept on top, in order)
        self.closed = False
        self.setWindowTitle(title)
        self.setWindowIcon(icons.icon("app"))
        self.resize(980, 600)
        lay = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        self.filter = QtWidgets.QLineEdit()
        self.filter.setObjectName("search")
        self.filter.setPlaceholderText("Filter by name or address...")
        self.filter.setClearButtonEnabled(True)
        top.addWidget(self.filter, 1)
        self.show_pages = QtWidgets.QCheckBox("Show web pages")
        top.addWidget(self.show_pages)
        lay.addLayout(top)

        refrow = QtWidgets.QHBoxLayout()
        refrow.addWidget(QtWidgets.QLabel("Referer:"))
        self.referer = QtWidgets.QLineEdit()
        self.referer.setPlaceholderText("optional - the page/player the links come from, e.g. https://player.arvancloud.ir/")
        refs = {l.get("referer", "") for l in links}
        if len(refs) == 1:
            self.referer.setText(refs.pop())
        refrow.addWidget(self.referer, 1)
        self.recheck = QtWidgets.QPushButton("Apply && recheck")
        self.recheck.setAutoDefault(False)
        self.recheck.clicked.connect(self._recheck)
        refrow.addWidget(self.recheck)
        lay.addLayout(refrow)

        from ..media import QUALITY_PRESETS
        self.presets = QUALITY_PRESETS
        self.qrow = QtWidgets.QWidget()
        ql = QtWidgets.QHBoxLayout(self.qrow)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(QtWidgets.QLabel("Video quality:"))
        self.quality = QtWidgets.QComboBox()
        for p in QUALITY_PRESETS:
            self.quality.addItem(p[0])
        ql.addWidget(self.quality)
        self.list_info = QtWidgets.QLabel()
        self.list_info.setObjectName("hint")
        ql.addWidget(self.list_info, 1)
        lay.addWidget(self.qrow)
        self.qrow.setVisible(bool(self.expand) or any(l.get("yt") in ("video", "playlist") for l in self.links))
        self.quality.currentIndexChanged.connect(lambda *_: self._refresh_yt_rows())

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        hdr = self.tree.header()
        hdr.resizeSection(0, 340)
        hdr.resizeSection(1, 90)
        hdr.resizeSection(2, 170)
        lay.addWidget(self.tree, 1)

        self.status = QtWidgets.QLabel()
        self.status.setObjectName("hint")
        lay.addWidget(self.status)

        bottom = QtWidgets.QHBoxLayout()
        for text, state in (("Check all", True), ("Uncheck all", False)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, st=state: self._check_visible(st))
            bottom.addWidget(b)
        sel = QtWidgets.QPushButton("Check selected")
        sel.clicked.connect(self._check_selected)
        bottom.addWidget(sel)
        bottom.addStretch(1)
        self.start_now = QtWidgets.QCheckBox("Start queue now")
        self.start_now.setChecked(True)
        bottom.addWidget(self.start_now)
        cancel = QtWidgets.QPushButton("Cancel")
        self.ok = QtWidgets.QPushButton("Add to queue")
        self.ok.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.accept)
        bottom.addWidget(cancel)
        bottom.addWidget(self.ok)
        lay.addLayout(bottom)

        self.tree.setSortingEnabled(False)
        for i, l in enumerate(self.links):
            self.tree.addTopLevelItem(self._make_row(l, i))
        # keep the page's order; clicking a column header still sorts
        hdr = self.tree.header()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(False)
        hdr.sectionClicked.connect(self._sort_by)
        self.tree.itemChanged.connect(self._item_changed)
        for l in self.links:
            if l.get("yt") == "page":
                l["_item"].setHidden(not self.show_pages.isChecked())
        self.filter.textChanged.connect(self._apply_filter)
        self.show_pages.toggled.connect(self._apply_filter)

        # probe every link in the background
        self.sig = _ProbeSignals(self)
        self.sig.result.connect(self._on_result)
        self.pool = ThreadPoolExecutor(max_workers=self.WORKERS)
        self.generation = 0
        self._start_probes()

    STREAM_RE = re.compile(r"\.(m3u8|mpd)(\?|#|$)", re.I)

    def _headers_for(self, l):
        """Referer from the field (applies to every link) or the link itself; browsers also send
        Origin on cross-site player requests, and some CDNs insist on it."""
        h = {"User-Agent": l.get("user_agent") or self.s["user_agent"]}
        ref = self.referer.text().strip() or l.get("referer", "")
        if ref:
            h["Referer"] = ref
            u = urllib.parse.urlsplit(ref)
            if u.scheme and u.netloc and self.referer.text().strip():
                h["Origin"] = f"{u.scheme}://{u.netloc}"
        if l.get("origin"):
            h["Origin"] = l["origin"]
        if l.get("cookies"):
            h["Cookie"] = l["cookies"]
        return h

    def _start_probes(self):
        from ..engine import probe
        from ..media import probe_media
        self.generation += 1
        gen = self.generation
        self.n_done = 0
        timeout = min(12, self.s["timeout"])
        if gen == 1:
            for k, url in enumerate(self.expand):
                self._submit_yt(-1 - k, "expand", url, gen)
        else:
            self.n_done += len(self.expand)
        for i, l in enumerate(self.links):
            if l.get("yt"):
                self._probe_yt(i, gen)
                continue
            if l.get("kind") == KIND_MEDIA and l.get("media_format"):
                self.n_done += 1
                continue
            headers = self._headers_for(l)
            stream = bool(self.STREAM_RE.search(l["url"]))
            if stream:
                l["_item"].setText(2, "checking...")

            def job(i=i, url=l["url"], headers=headers, stream=stream):
                if self.closed or gen != self.generation:
                    return
                try:
                    if stream:
                        res = probe_media(url, self.s, referer=headers.get("Referer", ""),
                                          cookies=headers.get("Cookie", ""),
                                          headers={"Origin": headers["Origin"]} if "Origin" in headers else None)
                        info = {"stream": res}
                    else:
                        info = probe(url, headers, self.s["proxy"], self.s["use_system_proxy"], timeout)
                except Exception as e:  # noqa: BLE001
                    info = {"error": str(e)[:200]}
                if not self.closed and gen == self.generation:
                    self.sig.result.emit(i, info)
            self.pool.submit(job)
        self._update_status()

    # ------------------------------------------------------------ YouTube
    YT_SIZE_LIMIT = 40          # look up sizes of at most this many videos (each costs a yt-dlp run)

    def _prepare(self, links):
        from .. import media as M
        out, seen_v, seen_l = [], set(), set()
        for l in links:
            u = l.get("url", "")
            if not re.match(r"^(https?|ftp)://", u, re.I):
                continue
            kind = M.classify_link(u)
            if kind == "ad":
                continue
            text = re.sub(r"\s+", " ", l.get("text") or "").strip()[:150]
            if l.get("page"):
                # the page the user is on: list its playlist / channel, it is not a download itself
                if kind in ("playlist", "channel") or (kind == "video" and M.yt_list_id(u)):
                    self.expand.append(u if kind == "channel" else M.yt_playlist_url(u))
                continue
            if kind == "video":
                vu = M.yt_video_url(u)
                if vu in seen_v:
                    continue
                seen_v.add(vu)
                out.append(dict(l, url=vu, yt="video", title=text, _page=False))
            elif kind == "playlist":
                key = M.yt_list_id(u)
                if key in seen_l:
                    continue
                seen_l.add(key)
                out.append(dict(l, url=M.yt_playlist_url(u), yt="playlist", title=text, _page=False))
            elif kind in ("channel", "page"):
                out.append(dict(l, yt="page", _page=True))
            else:
                out.append(dict(l))
        return out

    def preset(self):
        return self.presets[self.quality.currentIndex()]

    def _make_row(self, l, i):
        if l.get("yt") == "video":
            name, typ, icon = l.get("title") or self._name_from_url(l["url"]), "YouTube video", "Video"
        elif l.get("yt") == "playlist":
            name, typ, icon = l.get("title") or "Playlist", "Playlist", "queue"
        elif l.get("yt") == "page":
            name, typ, icon = l.get("title") or self._name_from_url(l["url"]), "Web page", GENERAL
        else:
            name = l.get("filename") or self._name_from_url(l["url"])
            typ, icon = ("checking..." if l.get("kind") != KIND_MEDIA else "Video"), self.s.category_for(name)
        it = _SortItem([name, "", typ, l["url"]])
        it.setData(0, Qt.ItemDataRole.UserRole, i)
        it.setIcon(0, icons.icon(icon))
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        checked = (not l.get("yt") and (self._wanted(name) or l.get("kind") == KIND_MEDIA)) or l.get("_check")
        it.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if (l.get("size") or 0) > 0:
            it.setText(1, human_size(l["size"]))
            it.setData(1, Qt.ItemDataRole.UserRole, l["size"])
        if l.get("yt") == "page":
            it.setHidden(not self.show_pages.isChecked())
        l["_item"] = it
        return it

    def _submit_yt(self, i, what, url, gen):
        from .. import media as M
        if not hasattr(self, "ytpool"):
            from concurrent.futures import ThreadPoolExecutor
            self.ytpool = ThreadPoolExecutor(max_workers=3)   # gentle with YouTube

        def job():
            if self.closed or gen != self.generation:
                return
            try:
                if what == "media":
                    info = {"yt_media": M.probe_media(url, self.s)}
                else:
                    info = {"yt_list" if what == "list" else "expand": M.flat_playlist(url, self.s)}
            except Exception as e:  # noqa: BLE001
                info = {"error": str(e)[:200]}
            if not self.closed and gen == self.generation:
                self.sig.result.emit(i, info)
        self.ytpool.submit(job)

    def _probe_yt(self, i, gen):
        l = self.links[i]
        if l["yt"] == "page" or "_media" in l or "_entries" in l:
            self.n_done += 1
        elif l["yt"] == "playlist":
            l["_item"].setText(2, "Playlist · counting...")
            self._submit_yt(i, "list", l["url"], gen)
        elif sum(1 for x in self.links if x.get("yt") == "video") <= self.YT_SIZE_LIMIT:
            self._submit_yt(i, "media", l["url"], gen)
        else:
            self.n_done += 1

    @staticmethod
    def _dur(sec):
        sec = int(sec or 0)
        if not sec:
            return ""
        h, r = divmod(sec, 3600)
        m, s_ = divmod(r, 60)
        return f"{h}:{m:02d}:{s_:02d}" if h else f"{m}:{s_:02d}"

    def _refresh_yt_rows(self):
        from ..media import pick_size
        p = self.preset()
        self.tree.blockSignals(True)
        for l in self.links:
            if l.get("yt") != "video":
                continue
            it = l["_item"]
            size, approx = pick_size((l.get("_media") or {}).get("options"), p)
            l["size"] = size
            it.setText(1, (("~" if approx else "") + human_size(size)) if size else "")
            it.setData(1, Qt.ItemDataRole.UserRole, size)
            d = self._dur(l.get("duration"))
            it.setText(2, "YouTube video" + (f" · {d}" if d else ""))
        self.tree.blockSignals(False)
        self._update_status()

    def _on_yt_result(self, i, info):
        if "expand" in info:
            self._add_expanded(info["expand"])
            return
        l = self.links[i]
        it = l["_item"]
        if "yt_list" in info:
            res = info["yt_list"]
            l["_entries"] = res["entries"]
            l["list_title"] = res["title"] or l.get("title") or "Playlist"
            if not l.get("title"):
                l["title"] = l["list_title"]
                it.setText(0, l["title"])
            n = sum(1 for e in res["entries"] if e["kind"] == "video")
            it.setText(2, f"Playlist · {n} videos")
            total = sum(e["duration"] or 0 for e in res["entries"])
            it.setText(1, self._dur(total))
            it.setData(1, Qt.ItemDataRole.UserRole, 0)
        elif "yt_media" in info:
            res = info["yt_media"]
            l["_media"] = res
            l["duration"] = l.get("duration") or res.get("duration")
            if not l.get("title"):
                l["title"] = res.get("title") or l["url"]
                it.setText(0, l["title"])
            self._refresh_yt_rows()

    def _add_expanded(self, res):
        """The page's own playlist / channel listing: put it on top, in order, checked."""
        from .. import media as M
        title = res.get("title") or "Playlist"
        by_url = {l["url"]: l for l in self.links}
        added_videos = 0
        self.tree.blockSignals(True)
        for idx, e in enumerate(res["entries"], 1):
            if e["kind"] == "video":
                l = by_url.get(e["url"])
                if l is None:
                    l = {"url": e["url"], "yt": "video", "_page": False}
                    self.links.append(l)
                    by_url[e["url"]] = l
                    self._make_row(l, len(self.links) - 1)
                else:
                    self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(l["_item"]))
                l.update(title=e["title"], duration=e["duration"], list_title=title, list_index=idx, _check=True)
                l["_item"].setText(0, e["title"])
                if self.links.index(l) not in self.touched:
                    l["_item"].setCheckState(0, Qt.CheckState.Checked)
                added_videos += 1
            else:       # a channel's "Playlists" tab
                key = M.yt_list_id(e["url"])
                l = next((x for x in self.links if x.get("yt") == "playlist" and M.yt_list_id(x["url"]) == key), None)
                if l is None:
                    l = {"url": M.yt_playlist_url(e["url"]), "yt": "playlist", "_page": False, "title": e["title"]}
                    self.links.append(l)
                    self._make_row(l, len(self.links) - 1)
                    self._probe_yt(len(self.links) - 1, self.generation)
                else:
                    self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(l["_item"]))
                l["title"] = e["title"]
                l["_item"].setText(0, e["title"])
            self.tree.insertTopLevelItem(self.n_top, l["_item"])
            self.n_top += 1
        self.tree.blockSignals(False)
        self.qrow.setVisible(True)
        if added_videos:
            self.list_info.setText(f"  {title}: {added_videos} videos")
            if sum(1 for x in self.links if x.get("yt") == "video") <= self.YT_SIZE_LIMIT:
                for k, x in enumerate(self.links):
                    if x.get("yt") == "video" and "_media" not in x:
                        self._submit_yt(k, "media", x["url"], self.generation)
        self._refresh_yt_rows()

    def _sort_by(self, col):
        order = Qt.SortOrder.DescendingOrder if getattr(self, "_sort", None) == (col, 0) else Qt.SortOrder.AscendingOrder
        self._sort = (col, 1 if order == Qt.SortOrder.DescendingOrder else 0)
        self.tree.sortItems(col, order)

    def yt_videos(self, l, wait_parent=None):
        """Videos a checked YouTube row stands for: itself, or every video of a playlist."""
        from .. import media as M
        if l.get("yt") == "video":
            return [dict(url=l["url"], title=l.get("title") or l["url"], list_title=l.get("list_title"),
                         list_index=l.get("list_index"))]
        entries = l.get("_entries")
        if entries is None:
            entries = M.flat_playlist(l["url"], self.s)["entries"]
        lt = l.get("list_title") or l.get("title") or "Playlist"
        return [dict(url=e["url"], title=e["title"], list_title=lt, list_index=n)
                for n, e in enumerate([e for e in entries if e["kind"] == "video"], 1)]

    def _recheck(self):
        self.tree.blockSignals(True)
        for l in self.links:
            if l.get("yt"):
                continue
            for k in ("_page", "_info", "_stream"):
                l.pop(k, None)
            it = l["_item"]
            it.setText(2, "checking...")
            it.setForeground(2, self.tree.palette().text())
            it.setToolTip(2, "")
        self.tree.blockSignals(False)
        self._start_probes()

    # --------------------------------------------------------------
    @staticmethod
    def _name_from_url(url):
        return urllib.parse.unquote(url.split("?")[0].split("#")[0].rstrip("/").rsplit("/", 1)[-1]) or url

    def _wanted(self, name):
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        return ext in self.s["capture_extensions"]

    def _item_changed(self, item, col):
        if col == 0:
            self.touched.add(item.data(0, Qt.ItemDataRole.UserRole))
            self._update_status()

    def _on_result(self, i, info):
        if self.closed:
            return
        self.n_done += 1
        if i < 0 or any(k in info for k in ("expand", "yt_list", "yt_media")) or \
                (self.links[i].get("yt") and "error" in info):
            if i >= 0 and "error" in info:
                it = self.links[i]["_item"]
                it.setToolTip(2, info["error"])
                if self.links[i].get("yt") == "playlist":
                    it.setText(2, "Playlist")
            elif i < 0 and "error" in info:
                self.list_info.setText("  Could not read the playlist: " + info["error"][:120])
            else:
                self._on_yt_result(i, info)
            self._update_status()
            return
        l = self.links[i]
        it = l["_item"]
        self.tree.blockSignals(True)
        if "error" in info:
            it.setText(2, "Unreachable")
            it.setToolTip(2, info["error"])
            it.setForeground(2, QtGui.QBrush(QtGui.QColor("#dc2626")))
            l["_page"] = None
            if i not in self.touched:
                it.setCheckState(0, Qt.CheckState.Unchecked)
        elif "stream" in info:
            res = info["stream"]
            best = res["options"][0] if res.get("options") else None
            l["_page"] = False
            l["_stream"] = best
            if not l.get("filename"):
                base = self._name_from_url(l["url"]).rsplit(".", 1)[0]
                l["filename"] = f"{base}.{best['ext'] if best else 'mp4'}"
                it.setText(0, l["filename"])
            it.setIcon(0, icons.icon("Video"))
            size = (best or {}).get("size") or 0
            l["size"] = size
            it.setText(1, (("~" if best and best.get("approx") else "") + human_size(size)) if size else "")
            it.setData(1, Qt.ItemDataRole.UserRole, size)
            q = f" {best['height']}p" if best and best.get("height") else ""
            it.setText(2, "Video stream" + q)
            it.setForeground(2, self.tree.palette().text())
            if i not in self.touched:
                it.setCheckState(0, Qt.CheckState.Checked)
        else:
            ctype = (info.get("content_type") or "").split(";")[0].strip().lower()
            page = ctype in ("text/html", "application/xhtml+xml")
            l["_page"] = page
            l["_info"] = info
            if not page:
                name = l.get("filename") or info["filename"]
                it.setText(0, name)
                it.setIcon(0, icons.icon(self.s.category_for(name)))
                l["filename"] = name
            size = info.get("size", -1)
            l["size"] = size
            it.setText(1, human_size(size) if size and size > 0 else "")
            it.setData(1, Qt.ItemDataRole.UserRole, size)
            it.setText(2, "Web page" if page else self._type_label(ctype, l.get("filename", "")))
            if i not in self.touched:
                want = not page and (self._wanted(l.get("filename", "")) or
                                     ctype.startswith(("video/", "audio/")))
                it.setCheckState(0, Qt.CheckState.Checked if want else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._apply_filter_one(l)
        self._update_status()

    def _type_label(self, ctype, name):
        cat = self.s.category_for(name)
        if cat != GENERAL:
            return cat.rstrip("s") if cat in ("Documents", "Programs") else cat
        if ctype.startswith("video/"):
            return "Video"
        if ctype.startswith("audio/"):
            return "Music"
        return "File"

    def _apply_filter_one(self, l):
        it = l["_item"]
        q = self.filter.text().strip().lower()
        hide = (l.get("_page") and not self.show_pages.isChecked()) or \
            (q and q not in it.text(0).lower() and q not in l["url"].lower())
        it.setHidden(bool(hide))

    def _apply_filter(self, *_):
        for l in self.links:
            self._apply_filter_one(l)
        self._update_status()

    def _check_visible(self, state):
        self.tree.blockSignals(True)
        for l in self.links:
            it = l["_item"]
            if not it.isHidden():
                it.setCheckState(0, Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
                self.touched.add(self.links.index(l))
        self.tree.blockSignals(False)
        self._update_status()

    def _check_selected(self):
        self.tree.blockSignals(True)
        for it in self.tree.selectedItems():
            it.setCheckState(0, Qt.CheckState.Checked)
            self.touched.add(it.data(0, Qt.ItemDataRole.UserRole))
        self.tree.blockSignals(False)
        self._update_status()

    def selected_links(self):
        return [l for l in self.links if l["_item"].checkState(0) == Qt.CheckState.Checked]

    def _update_status(self):
        files = [l for l in self.links if (l.get("_page") is False and l.get("yt") != "playlist")
                 or l.get("kind") == KIND_MEDIA]
        pages = sum(1 for l in self.links if l.get("_page"))
        sel = self.selected_links()
        lists = [l for l in sel if l.get("yt") == "playlist"]
        sel = [l for l in sel if l.get("yt") != "playlist"]
        sel_size = sum(l.get("size", 0) for l in sel if (l.get("size") or 0) > 0)
        unknown = sum(1 for l in sel if not (l.get("size") or 0) > 0)
        txt = f"Checked: {len(sel)} file(s)"
        if lists:
            nv = sum(sum(1 for e in (l.get("_entries") or []) if e["kind"] == "video") for l in lists)
            txt = (f"Checked: {len(lists)} playlist(s), {nv} videos" + (f" + {len(sel)} file(s)" if sel else ""))
        if sel_size:
            txt += f", {human_size(sel_size)}" + (f" + {unknown} of unknown size" if unknown else "")
        txt += f"     |     Found {len(files)} file(s)"
        if pages:
            txt += f", {pages} web page(s)" + ("" if self.show_pages.isChecked() else " hidden")
        total = len(self.links) + len(self.expand)
        if self.n_done < total:
            txt += f"     |     Checking links {min(self.n_done, total)}/{total}..."
        self.status.setText(txt)
        self.ok.setEnabled(bool(sel) or bool(lists))

    def done(self, r):  # QDialog.done override: stop probing
        self.closed = True
        for pool in (self.pool, getattr(self, "ytpool", None)):
            if pool is None:
                continue
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=False)
        super().done(r)
