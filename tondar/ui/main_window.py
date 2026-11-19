"""Main window: toolbar, categories tree, download list, tray icon."""
import datetime
import os
import re
import subprocess

from .. import APP_NAME
from ..qt import QtCore, QtGui, QtWidgets, Qt, QAction, exec_, dialog_accepted
from ..config import GENERAL
from ..models import (human_size, human_speed, human_eta, COMPLETED, ERROR, PAUSED, QUEUED,
                      DOWNLOADING, CONNECTING, WAITING, KIND_MEDIA)
from ..manager import MAIN_QUEUE
from . import icons
from .dialogs import (AddUrlDialog, FileInfoDialog, ProgressDialog, CompleteDialog, OptionsDialog,
                      SchedulerDialog, open_path, open_folder, about, run_tools_update)

COLS = ["File Name", "Q", "Size", "Status", "Time left", "Transfer rate", "Last Try Date", "Description"]
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
ID_ROLE = Qt.ItemDataRole.UserRole + 2


class DownloadModel(QtCore.QAbstractTableModel):
    def __init__(self, manager):
        super().__init__()
        self.m = manager
        self.ids = list(manager.items.keys())
        self.rows = {i: n for n, i in enumerate(self.ids)}
        manager.item_added.connect(self._added)
        manager.item_removed.connect(self._removed)
        manager.item_updated.connect(self._updated)

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.ids)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(COLS)

    def headerData(self, s, o, role=Qt.ItemDataRole.DisplayRole):
        if o == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLS[s]
        return None

    def item(self, row):
        return self.m.items.get(self.ids[row])

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        it = self.item(idx.row())
        if it is None:
            return None
        c = idx.column()
        if role == ID_ROLE:
            return it.id
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return it.filename
            if c == 1:
                return "Q" if it.status == QUEUED else ""
            if c == 2:
                return human_size(it.size) if it.size > 0 else ""
            if c == 3:
                return self._status(it)
            if c == 4:
                return human_eta(it.eta) if it.id in self.m.engines else ""
            if c == 5:
                return human_speed(it.speed) if it.id in self.m.engines else ""
            if c == 6:
                t = it.last_try or it.added
                return datetime.datetime.fromtimestamp(t).strftime("%b %d %H:%M:%S %Y") if t else ""
            if c == 7:
                return it.description or (it.media_title if it.kind == KIND_MEDIA else "")
        if role == SORT_ROLE:
            return [it.filename.lower(), it.status == QUEUED, it.size, it.progress, it.eta,
                    it.speed, it.last_try or it.added, it.description][c]
        if role == Qt.ItemDataRole.DecorationRole and c == 0:
            return icons.icon(it.category if it.category in icons.DRAWERS else GENERAL)
        if role == Qt.ItemDataRole.ForegroundRole and c == 3:
            if it.status == ERROR:
                return QtGui.QColor("#c62828")
            if it.status == COMPLETED:
                return QtGui.QColor("#2e7d32")
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{it.url}\n{it.path}" + (f"\n{it.error}" if it.error else "")
        return None

    def _status(self, it):
        if it.status == COMPLETED:
            return "Complete"
        if it.status == ERROR:
            return "Error"
        if it.status == CONNECTING:
            return "Connecting..."
        if it.size > 0 and it.downloaded > 0:
            return f"{it.progress * 100:.2f}%"
        if it.status == DOWNLOADING:
            return human_size(it.downloaded)
        return it.status

    def _added(self, i):
        n = len(self.ids)
        self.beginInsertRows(QtCore.QModelIndex(), n, n)
        self.ids.append(i)
        self.rows[i] = n
        self.endInsertRows()

    def _removed(self, i):
        r = self.rows.get(i)
        if r is None:
            return
        self.beginRemoveRows(QtCore.QModelIndex(), r, r)
        self.ids.pop(r)
        self.rows = {x: n for n, x in enumerate(self.ids)}
        self.endRemoveRows()

    def _updated(self, i):
        r = self.rows.get(i)
        if r is not None:
            self.dataChanged.emit(self.index(r, 0), self.index(r, len(COLS) - 1))


class FilterProxy(QtCore.QSortFilterProxyModel):
    def __init__(self, manager):
        super().__init__()
        self.m = manager
        self.flt = ("all", None)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(False)

    def set_filter(self, kind, value):
        self.flt = (kind, value)
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        it = self.sourceModel().item(row)
        if it is None:
            return False
        kind, val = self.flt
        if kind == "queue":
            return it.status == QUEUED and it.queue == val
        if kind == "finished" and it.status != COMPLETED:
            return False
        if kind == "unfinished" and it.status == COMPLETED:
            return False
        return val is None or it.category == val

    def lessThan(self, a, b):
        x, y = a.data(SORT_ROLE), b.data(SORT_ROLE)
        try:
            return x < y
        except TypeError:
            return str(x) < str(y)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, manager, settings, bridge, media_cache, ext_dir):
        super().__init__()
        self.m, self.s, self.bridge, self.media_cache, self.ext_dir = manager, settings, bridge, media_cache, ext_dir
        self.progress_dialogs = {}
        self.really_quit = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.icon("app"))
        self.resize(1080, 600)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_body()
        self._build_tray()
        self._update_actions()

        self.status_speed = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.status_speed)
        st = QtCore.QTimer(self)
        st.timeout.connect(self._status_tick)
        st.start(1000)

        bridge.download_requested.connect(self.on_browser_download)
        bridge.media_download_requested.connect(self.on_browser_media)
        bridge.links_requested.connect(self.on_browser_links)
        manager.item_finished.connect(self._on_finished)
        manager.item_updated.connect(lambda _id: self._update_actions())
        manager.queue_state_changed.connect(lambda _r: self._update_actions())
        QtWidgets.QApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        self._last_clip = QtWidgets.QApplication.clipboard().text()

    # ------------------------------------------------------------ build
    def _act(self, text, icon=None, slot=None, shortcut=None, tip=None):
        a = QAction(icons.icon(icon) if icon else QtGui.QIcon(), text, self)
        if slot:
            a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QtGui.QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
        return a

    def _build_actions(self):
        A = self._act
        self.a_add = A("Add URL", "add", self.add_url, "Ctrl+N", "Add a new download")
        self.a_resume = A("Resume", "resume", self.resume_selected, None, "Resume selected downloads")
        self.a_stop = A("Stop", "stop", self.stop_selected, None, "Stop selected downloads")
        self.a_stop_all = A("Stop All", "stop_all", self.m.stop_all, None, "Stop all downloads")
        self.a_delete = A("Delete", "delete", self.delete_selected, "Del", "Delete selected downloads")
        self.a_delete_done = A("Delete Co...", "delete_done", self.m.remove_completed, None,
                               "Delete all completed downloads")
        self.a_options = A("Options", "options", self.options, None, "Configuration")
        self.a_scheduler = A("Scheduler", "scheduler", self.scheduler, None, "Scheduler")
        self.a_start_q = A("Start Qu...", "start_queue", lambda: self.m.start_queue(), None, "Start main queue")
        self.a_stop_q = A("Stop Qu...", "stop_queue", self.m.stop_queue, None, "Stop main queue")
        self.a_speed = A("Speed Limiter", "speed", self.toggle_speed, None, "Turn the speed limiter on/off")
        self.a_speed.setCheckable(True)
        self.a_speed.setChecked(bool(self.s["speed_limit_enabled"]))
        self.a_open = A("Open", None, self.open_selected)
        self.a_open_folder = A("Open folder", None, self.open_selected_folder)
        self.a_redownload = A("Redownload", None, self.redownload_selected)
        self.a_to_queue = A("Add to queue", "queue", self.queue_selected)
        self.a_copy = A("Copy address", None, self.copy_url)
        self.a_exit = A("Exit", None, self.quit_app, "Ctrl+Q")
        self.a_tools = A("Update video engine (yt-dlp)", None, lambda: run_tools_update(self, self.s))

    def _build_menus(self):
        mb = self.menuBar()
        t = mb.addMenu("&Tasks")
        t.addAction(self.a_add)
        t.addAction(self._act("Add batch download from clipboard", None, self.batch_from_clipboard))
        t.addSeparator()
        t.addAction(self.a_exit)
        f = mb.addMenu("&File")
        for a in (self.a_resume, self.a_stop, self.a_redownload, None, self.a_open, self.a_open_folder,
                  self.a_copy, None, self.a_delete):
            f.addSeparator() if a is None else f.addAction(a)
        d = mb.addMenu("&Downloads")
        for a in (self.a_stop_all, self.a_delete_done, None, self.a_start_q, self.a_stop_q, self.a_scheduler,
                  None, self.a_speed, None, self.a_tools, self.a_options):
            d.addSeparator() if a is None else d.addAction(a)
        v = mb.addMenu("&View")
        self.a_view_tb = self._act("Toolbar")
        self.a_view_cat = self._act("Categories")
        for a in (self.a_view_tb, self.a_view_cat):
            a.setCheckable(True)
            a.setChecked(True)
            v.addAction(a)
        h = mb.addMenu("&Help")
        h.addAction(self._act("Browser integration...", None, lambda: self.options()))
        h.addAction(self._act(f"About {APP_NAME}", "app", lambda: about(self)))

    def _build_toolbar(self):
        tb = QtWidgets.QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setIconSize(QtCore.QSize(40, 40))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setMovable(False)
        tb.setStyleSheet("QToolBar{spacing:2px; padding:2px; border-bottom:1px solid #c8d0d8;"
                         "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fbfcfd,stop:1 #e7ecf1);}"
                         "QToolButton{min-width:64px; padding:3px 2px; color:#1d2b38;}")
        for a in (self.a_add, self.a_resume, self.a_stop, self.a_stop_all, self.a_delete,
                  self.a_delete_done, self.a_options, self.a_scheduler, self.a_start_q,
                  self.a_stop_q, self.a_speed):
            tb.addAction(a)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self.toolbar = tb

    def _build_body(self):
        split = QtWidgets.QSplitter()
        # categories tree
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabel("Categories")
        self.tree.setMinimumWidth(170)
        self.tree.setMaximumWidth(260)

        def node(parent, text, ic, kind, val):
            n = QtWidgets.QTreeWidgetItem(parent, [text])
            n.setIcon(0, icons.icon(ic))
            n.setData(0, Qt.ItemDataRole.UserRole, (kind, val))
            return n
        cats = list(self.s["categories"].keys())
        root_all = node(self.tree, "All Downloads", "all", "all", None)
        for c in cats:
            node(root_all, c, c, "all", c)
        for kind, text, ic in (("unfinished", "Unfinished", "unfinished"), ("finished", "Finished", "finished")):
            r = node(self.tree, text, ic, kind, None)
            for c in cats:
                node(r, c, c, kind, c)
        q = node(self.tree, "Queues", "queue", "queue", MAIN_QUEUE)
        node(q, MAIN_QUEUE, "queue", "queue", MAIN_QUEUE)
        root_all.setExpanded(True)
        self.tree.setCurrentItem(root_all)
        self.tree.currentItemChanged.connect(self._category_selected)
        split.addWidget(self.tree)

        # download list
        self.model = DownloadModel(self.m)
        self.proxy = FilterProxy(self.m)
        self.proxy.setSourceModel(self.model)
        self.view = QtWidgets.QTreeView()
        self.view.setModel(self.proxy)
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setAlternatingRowColors(True)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(6, Qt.SortOrder.AscendingOrder)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(self._double_click)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._update_actions())
        hdr = self.view.header()
        for i, w in enumerate([330, 24, 80, 80, 90, 100, 150, 200]):
            hdr.resizeSection(i, w)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 880])
        self.setCentralWidget(split)
        self.a_view_tb.toggled.connect(lambda v: self.toolbar.setVisible(v))
        self.a_view_cat.toggled.connect(self.tree.setVisible)

    def _build_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(icons.icon("app"), self)
        menu = QtWidgets.QMenu()
        menu.addAction(self._act("Show", "app", self.show_window))
        menu.addAction(self.a_add)
        menu.addSeparator()
        menu.addAction(self.a_start_q)
        menu.addAction(self.a_stop_q)
        menu.addAction(self.a_speed)
        menu.addSeparator()
        menu.addAction(self.a_exit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_window()
                                    if r == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.setToolTip(APP_NAME)
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    # ---------------------------------------------------------- helpers
    def selected_ids(self):
        ids = []
        for idx in self.view.selectionModel().selectedRows():
            ids.append(self.proxy.data(idx, ID_ROLE))
        return [i for i in ids if i in self.m.items]

    def _update_actions(self):
        ids = self.selected_ids()
        items = [self.m.items[i] for i in ids]
        self.a_resume.setEnabled(any(i.status != COMPLETED and i.id not in self.m.engines for i in items))
        self.a_stop.setEnabled(any(i.id in self.m.engines or i.status == QUEUED for i in items))
        self.a_delete.setEnabled(bool(items))
        self.a_stop_all.setEnabled(bool(self.m.engines))
        self.a_start_q.setEnabled(not self.m.queue_running)
        self.a_stop_q.setEnabled(self.m.queue_running)
        done = any(i.status == COMPLETED for i in items)
        self.a_open.setEnabled(done)
        self.a_open_folder.setEnabled(bool(items))
        self.a_redownload.setEnabled(bool(items))

    def _category_selected(self, cur, _prev):
        if cur:
            kind, val = cur.data(0, Qt.ItemDataRole.UserRole)
            self.proxy.set_filter(kind, val)

    def _status_tick(self):
        sp = self.m.total_speed()
        n = len(self.m.engines)
        txt = f"Active: {n}    Total speed: {human_speed(sp) or '0'}"
        if self.s.get("speed_limit_enabled"):
            txt += f"    Limiter: {self.s['speed_limit_kbps']} KB/sec"
        self.status_speed.setText(txt)
        self.tray.setToolTip(f"{APP_NAME}\n{txt}")

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------- actions
    def add_url(self, url=""):
        dlg = AddUrlDialog(self, url if isinstance(url, str) else "")
        if dialog_accepted(exec_(dlg)):
            url, headers = dlg.value()
            self.new_download({"url": url, "headers": headers})

    def new_download(self, req):
        dup = self.m.find_duplicate(req["url"])
        if dup and dup.status != COMPLETED and not req.get("media_option"):
            r = QtWidgets.QMessageBox.question(
                self, APP_NAME, f"This address is already in the list:\n{dup.filename}\n\n"
                "Add it again as a new download?")
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                self.show_progress(dup.id) if dup.id in self.m.engines else self.m.start(dup.id)
                return
        dlg = FileInfoDialog(self.m, self.s, req, self)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.finished.connect(lambda code, d=dlg: self._file_info_done(d, code))

    def _file_info_done(self, dlg, code):
        if not dialog_accepted(code) or not dlg.result_item:
            return
        it = dlg.result_item
        if dlg.start_now:
            self.m.add(it, start=True)
            if self.s["show_progress_dialog"]:
                self.show_progress(it.id)
        else:
            self.m.add(it, start=False, queue=MAIN_QUEUE)

    def show_progress(self, item_id):
        d = self.progress_dialogs.get(item_id)
        try:
            if d is not None and d.isVisible():
                d.raise_()
                return
        except RuntimeError:
            pass
        d = ProgressDialog(self.m, self.s, item_id)
        d.open_complete.connect(self.show_complete)
        d.destroyed.connect(lambda *_: self.progress_dialogs.pop(item_id, None))
        self.progress_dialogs[item_id] = d
        d.show()

    def show_complete(self, item_id):
        it = self.m.items.get(item_id)
        if it:
            d = CompleteDialog(self.s, it)
            d.show()
            d.raise_()

    def _on_finished(self, item_id, status):
        it = self.m.items.get(item_id)
        if not it:
            return
        if status == COMPLETED:
            # downloads that have a progress window open show the "Download complete"
            # dialog from there; everything else gets a desktop notification
            self.tray.showMessage("Download complete", it.filename, icons.icon("app"), 4000)
        elif status == ERROR:
            self.tray.showMessage("Download failed", f"{it.filename}\n{it.error}", icons.icon("app"), 6000)

    def resume_selected(self):
        for i in self.selected_ids():
            self.m.start(i)
            if self.s["show_progress_dialog"] and len(self.selected_ids()) == 1:
                self.show_progress(i)

    def stop_selected(self):
        for i in self.selected_ids():
            self.m.stop(i)

    def delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Confirm deletion")
        box.setText(f"Remove {len(ids)} download(s) from the list?")
        cb = QtWidgets.QCheckBox("Also delete the files from disk")
        box.setCheckBox(cb)
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok |
                               QtWidgets.QMessageBox.StandardButton.Cancel)
        if exec_(box) == QtWidgets.QMessageBox.StandardButton.Ok:
            for i in ids:
                self.m.remove(i, delete_file=cb.isChecked())

    def open_selected(self):
        for i in self.selected_ids():
            it = self.m.items[i]
            if it.status == COMPLETED:
                open_path(it.path)

    def open_selected_folder(self):
        ids = self.selected_ids()
        if ids:
            it = self.m.items[ids[0]]
            open_folder(it.path if os.path.exists(it.path) else it.save_dir)

    def redownload_selected(self):
        for i in self.selected_ids():
            self.m.redownload(i)

    def queue_selected(self):
        for i in self.selected_ids():
            self.m.add_to_queue(i)

    def copy_url(self):
        ids = self.selected_ids()
        QtWidgets.QApplication.clipboard().setText(
            "\n".join(self.m.items[i].page_url or self.m.items[i].url for i in ids))

    def toggle_speed(self, on):
        self.s["speed_limit_enabled"] = bool(on)
        if on and not self.s["speed_limit_kbps"]:
            v, ok = QtWidgets.QInputDialog.getInt(self, "Speed Limiter", "Maximum speed (KB/sec):", 512, 1, 10_000_000)
            if not ok:
                self.a_speed.setChecked(False)
                self.s["speed_limit_enabled"] = False
                return
            self.s["speed_limit_kbps"] = v
        self.s.save()

    def options(self):
        dlg = OptionsDialog(self.s, self, self.ext_dir)
        exec_(dlg)
        self.a_speed.setChecked(bool(self.s["speed_limit_enabled"]))

    def scheduler(self):
        exec_(SchedulerDialog(self.m, self.s, self))

    def batch_from_clipboard(self):
        text = QtWidgets.QApplication.clipboard().text()
        links = re.findall(r"(?:https?|ftp)://[^\s'\"<>]+", text)
        if not links:
            QtWidgets.QMessageBox.information(self, APP_NAME, "No links found in the clipboard.")
            return
        self.on_browser_links([{"url": u} for u in links])

    def _context_menu(self, pos):
        if not self.selected_ids():
            return
        menu = QtWidgets.QMenu(self)
        for a in (self.a_open, self.a_open_folder, None, self.a_resume, self.a_stop, self.a_redownload,
                  None, self.a_to_queue, self.a_copy, None, self.a_delete):
            menu.addSeparator() if a is None else menu.addAction(a)
        exec_(menu, self.view.viewport().mapToGlobal(pos))

    def _double_click(self, idx):
        i = self.proxy.data(idx, ID_ROLE)
        it = self.m.items.get(i)
        if not it:
            return
        if it.status == COMPLETED:
            self.show_complete(i)
        else:
            if i not in self.m.engines:
                self.m.start(i)
            self.show_progress(i)

    # ------------------------------------------------- browser bridge
    def on_browser_download(self, data):
        req = {"url": data.get("url"), "referer": data.get("referer", ""),
               "cookies": data.get("cookies", ""), "filename": data.get("filename", ""),
               "user_agent": data.get("userAgent", ""), "forced_file": True}
        if self.s["show_file_info_dialog"]:
            self.new_download(req)
        else:
            from urllib.parse import unquote, urlsplit
            name = req["filename"] or unquote(urlsplit(req["url"]).path.rstrip("/").rsplit("/", 1)[-1]) or "download"
            it = self.m.new_item(req["url"], name, referer=req["referer"], cookies=req["cookies"],
                                 user_agent=req["user_agent"], auto_name=not req["filename"])
            self.m.add(it, start=True)
            if self.s["show_progress_dialog"]:
                self.show_progress(it.id)

    def on_browser_media(self, data):
        url = data.get("url")
        info = self.media_cache.get(url)
        req = {"url": url, "media": True, "media_info": info, "media_option": data.get("format")}
        if self.s["show_file_info_dialog"] or not info:
            self.new_download(req)
            return
        o = next((o for o in info["options"] if o["id"] == data.get("format")), info["options"][0])
        from ..media import media_filename
        cat = "Music" if o["type"] != "video" else "Video"
        it = self.m.new_item(url, media_filename(info["title"], o["ext"]), category=cat, kind=KIND_MEDIA,
                             media_format=o["id"], media_title=info["title"], size=o.get("size") or -1,
                             page_url=url)
        self.m.add(it, start=True)
        if self.s["show_progress_dialog"]:
            self.show_progress(it.id)

    def on_browser_links(self, links):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Download all links")
        dlg.setWindowIcon(icons.icon("app"))
        dlg.resize(700, 420)
        lay = QtWidgets.QVBoxLayout(dlg)
        lw = QtWidgets.QListWidget()
        for l in links:
            url = l.get("url", "")
            if not re.match(r"^(https?|ftp)://", url):
                continue
            name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            item = QtWidgets.QListWidgetItem(icons.icon(self.s.category_for(name)), url)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if ext in self.s["capture_extensions"]
                               else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, l)
            lw.addItem(item)
        lay.addWidget(QtWidgets.QLabel("Select the files to add to the main queue:"))
        lay.addWidget(lw)
        h = QtWidgets.QHBoxLayout()
        allb = QtWidgets.QPushButton("Check all")
        noneb = QtWidgets.QPushButton("Uncheck all")
        allb.clicked.connect(lambda: [lw.item(i).setCheckState(Qt.CheckState.Checked) for i in range(lw.count())])
        noneb.clicked.connect(lambda: [lw.item(i).setCheckState(Qt.CheckState.Unchecked) for i in range(lw.count())])
        h.addWidget(allb)
        h.addWidget(noneb)
        h.addStretch(1)
        self_start = QtWidgets.QCheckBox("Start queue now")
        self_start.setChecked(True)
        h.addWidget(self_start)
        lay.addLayout(h)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                        QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if not dialog_accepted(exec_(dlg)):
            return
        for i in range(lw.count()):
            item = lw.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                l = item.data(Qt.ItemDataRole.UserRole)
                url = l["url"]
                name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "download"
                from urllib.parse import unquote
                it = self.m.new_item(url, unquote(name), referer=l.get("referer", ""),
                                     cookies=l.get("cookies", ""))
                self.m.add(it, start=False, queue=MAIN_QUEUE)
        if self_start.isChecked():
            self.m.start_queue()

    def _clipboard_changed(self):
        text = QtWidgets.QApplication.clipboard().text().strip()
        if text == self._last_clip:
            return
        self._last_clip = text
        if not self.s["monitor_clipboard"]:
            return
        if re.match(r"^(https?|ftp)://\S+$", text):
            name = text.split("?")[0].rsplit("/", 1)[-1]
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in self.s["capture_extensions"]:
                self.new_download({"url": text})

    # --------------------------------------------------------- closing
    def closeEvent(self, e):
        if self.s["close_to_tray"] and self.tray.isVisible() and not self.really_quit:
            self.hide()
            e.ignore()
            return
        self.really_quit = True
        e.accept()
        QtWidgets.QApplication.quit()

    def quit_app(self):
        self.really_quit = True
        QtWidgets.QApplication.quit()
