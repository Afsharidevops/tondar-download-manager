"""Tasks > Telegram...: optional - log in once with tdl, list a channel's files, queue them."""
import os
import threading
import time

from .. import APP_NAME
from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal
from ..models import human_size, KIND_TELEGRAM
from ..manager import MAIN_QUEUE
from .. import telegram as tg
from .. import osutil
from .widgets import TypeFilter

TYPE_NAMES = {"video": "Video", "audio": "Audio", "image": "Image", "document": "Document",
              "compressed": "Archive", "program": "Program", "other": "File"}
CATEGORY_OF = {"video": "Video", "audio": "Music", "document": "Documents", "compressed": "Compressed",
               "program": "Programs"}



class _Bridge(QtCore.QObject):
    done = Signal(object, object, object)       # callback, result, error


class _SortItem(QtWidgets.QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col in (1, 3, 4):
            return (self.data(col, Qt.ItemDataRole.UserRole) or 0) < (other.data(col, Qt.ItemDataRole.UserRole) or 0)
        return self.text(col).lower() < other.text(col).lower()


def _hms(sec):
    if not sec:
        return ""
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class TelegramDialog(QtWidgets.QDialog):
    COLS = ["File name", "Size", "Type", "Length", "Date", "Caption"]

    def __init__(self, manager, settings, parent=None, chat=""):
        super().__init__(parent)
        self.m, self.s = manager, settings
        self.entries = []
        self.busy = False
        self.cancel_flag = False
        self.bridge = _Bridge()
        self.bridge.done.connect(lambda cb, res, err: cb(res, err))
        self.setWindowTitle("Telegram")
        self.resize(980, 640)
        lay = QtWidgets.QVBoxLayout(self)

        # ---------------------------------------------------------- account
        acc = QtWidgets.QGroupBox("Account")
        al = QtWidgets.QVBoxLayout(acc)
        row = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.status, 1)
        self.b_install = QtWidgets.QPushButton("Install Telegram support")
        self.b_install.clicked.connect(self.install)
        self.b_login = QtWidgets.QPushButton("Log in…")
        menu = QtWidgets.QMenu(self.b_login)
        menu.addAction("With a QR code (scan it with Telegram on your phone)", lambda: self.login("qr"))
        menu.addAction("With phone number and code", lambda: self.login("code"))
        menu.addAction("Use Telegram Desktop's login on this computer", lambda: self.login("desktop"))
        self.b_login.setMenu(menu)
        self.b_check = QtWidgets.QPushButton("Check login")
        self.b_check.clicked.connect(self.check)
        self.b_logout = QtWidgets.QPushButton("Log out")
        self.b_logout.clicked.connect(self.logout)
        for b in (self.b_install, self.b_login, self.b_check, self.b_logout):
            row.addWidget(b)
        al.addLayout(row)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel("SOCKS5 proxy for Telegram:"))
        self.proxy = QtWidgets.QLineEdit(self.s.get("telegram_proxy", ""))
        self.proxy.setPlaceholderText("optional, e.g. socks5://127.0.0.1:1080")
        self.proxy.editingFinished.connect(self._save_proxy)
        prow.addWidget(self.proxy, 1)
        al.addLayout(prow)
        note = QtWidgets.QLabel(
            "Telegram support uses <a href='https://github.com/iyear/tdl'>tdl</a> (open source). "
            "Your login is kept only on this computer, in Tondar's data folder; <i>Log out</i> deletes it. "
            "It appears in Telegram under Settings › Devices, where you can also end it.")
        note.setWordWrap(True)
        note.setOpenExternalLinks(True)
        al.addWidget(note)
        lay.addWidget(acc)

        # ------------------------------------------------------------ files
        frow = QtWidgets.QHBoxLayout()
        frow.addWidget(QtWidgets.QLabel("Channel / group:"))
        self.chat = QtWidgets.QLineEdit(chat)
        self.chat.setPlaceholderText("@channel, t.me link or message link")
        self.chat.returnPressed.connect(self.list_files)
        frow.addWidget(self.chat, 1)
        saved = QtWidgets.QPushButton("Saved Messages")
        saved.setToolTip("List the files in your own Saved Messages")
        saved.clicked.connect(lambda: (self.chat.setText("Saved Messages"), self.list_files()))
        frow.addWidget(saved)
        frow.addWidget(QtWidgets.QLabel("last"))
        self.last = QtWidgets.QSpinBox()
        self.last.setRange(1, 10000)
        self.last.setValue(int(self.s.get("telegram_last", 100) or 100))
        self.last.setSuffix(" messages")
        frow.addWidget(self.last)
        self.b_list = QtWidgets.QPushButton("List files")
        self.b_list.setDefault(True)
        self.b_list.clicked.connect(self.list_files)
        frow.addWidget(self.b_list)
        lay.addLayout(frow)

        self.types = TypeFilter(self)
        self.types.changed.connect(self._apply_filter)
        lay.addWidget(self.types)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("Filter by name or caption…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(self.COLS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemChanged.connect(lambda *_: self._update_total())
        for c, w in enumerate((330, 80, 60, 70, 90)):
            self.tree.setColumnWidth(c, w)
        lay.addWidget(self.tree, 1)
        self.info = QtWidgets.QLabel()
        lay.addWidget(self.info)

        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(QtWidgets.QLabel("Save to:"))
        self.folder = QtWidgets.QLineEdit(str(self.s.dir_for_category("Video")))
        srow.addWidget(self.folder, 1)
        b = QtWidgets.QPushButton("Browse…")
        b.clicked.connect(self._browse)
        srow.addWidget(b)
        self.subfolder = QtWidgets.QCheckBox("Folder per channel")
        self.subfolder.setChecked(True)
        srow.addWidget(self.subfolder)
        lay.addLayout(srow)

        brow = QtWidgets.QHBoxLayout()
        for text, fn in (("Check all", lambda: self._check_all(True)), ("Uncheck all", lambda: self._check_all(False)),
                         ("Check selected", self._check_selected)):
            bb = QtWidgets.QPushButton(text)
            bb.clicked.connect(fn)
            brow.addWidget(bb)
        brow.addStretch(1)
        self.start_now = QtWidgets.QCheckBox("Start queue now")
        self.start_now.setChecked(True)
        brow.addWidget(self.start_now)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.reject)
        self.b_add = QtWidgets.QPushButton("Add to queue")
        self.b_add.clicked.connect(self.add)
        brow.addWidget(close)
        brow.addWidget(self.b_add)
        lay.addLayout(brow)

        self.logged_in = None
        self._refresh_state()
        if tg.tdl_path() and tg.has_session():
            self.check(quiet=True, then_list=bool(chat))

    # ------------------------------------------------------------ helpers
    def _bg(self, fn, cb):
        def run():
            try:
                res, err = fn(), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e
            self.bridge.done.emit(cb, res, err)
        threading.Thread(target=run, daemon=True).start()

    def _set_busy(self, busy, text=""):
        self.busy = busy
        self.cancel_flag = False
        self._refresh_state()
        if text:
            self.info.setText(text)

    def _refresh_state(self):
        have = bool(tg.tdl_path())
        session = tg.has_session()
        if not have:
            st = "<b>Telegram support is not installed.</b> It is optional - install it only if you want to " \
                 "download from Telegram channels and groups."
        elif self.logged_in:
            st = "<b style='color:#1f8f2c'>Logged in to Telegram.</b>"
        elif session and self.logged_in is None:
            st = "A saved login was found - <i>checking…</i>" if self.busy else "A saved login was found."
        else:
            st = "<b>Not logged in.</b> Choose <i>Log in…</i>"
        self.status.setText(st)
        self.b_install.setVisible(not have)
        self.b_login.setVisible(have and not self.logged_in)
        self.b_check.setVisible(have and session and not self.logged_in)
        self.b_logout.setVisible(have and session)
        for w in (self.b_install, self.b_login, self.b_check, self.b_logout, self.b_add):
            w.setEnabled(not self.busy)
        self.b_list.setEnabled(have and session and not self.busy)
        self.b_list.setText("List files")

    def _save_proxy(self):
        p = self.proxy.text().strip()
        if p and not p.startswith(("socks5://", "socks5h://")):
            QtWidgets.QMessageBox.warning(self, APP_NAME, "tdl supports SOCKS5 proxies only "
                                          "(socks5://host:port or socks5://user:password@host:port).")
            return
        if p != self.s.get("telegram_proxy", ""):
            self.s["telegram_proxy"] = p
            self.s.save()

    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Save to", self.folder.text())
        if d:
            self.folder.setText(d)

    def _error(self, e):
        QtWidgets.QMessageBox.warning(self, APP_NAME, str(e))

    # ------------------------------------------------------------ account
    def install(self):
        self._set_busy(True, "Downloading tdl…")
        self._bg(lambda: tg.install_tdl(self.s, log=lambda *_: None), self._installed)

    def _installed(self, res, err):
        self._set_busy(False, "" if err else f"tdl {tg.tdl_version()} installed.")
        if err:
            self._error(f"Could not download tdl:\n{err}\n\nCheck your internet connection or proxy "
                        "(Options › Connection) and try again.")

    def login(self, mode):
        self._save_proxy()
        try:
            cmd = tg.login_command(self.s, mode)
        except tg.TelegramError as e:
            return self._error(e)
        if tg.TDL_LOCK.locked():
            return self._error("A Telegram download is running - stop it before logging in.")
        hints = {"qr": "Scan the QR code in the terminal window with Telegram on your phone "
                       "(Settings › Devices › Link Desktop Device).",
                 "code": "Type your phone number (with country code, e.g. +98…) and the code Telegram sends you "
                         "in the terminal window.",
                 "desktop": "Telegram Desktop must be installed and logged in on this computer. "
                            "Answer the questions in the terminal window (choose No when asked to log out "
                            "the desktop app)."}
        if tg.open_terminal(cmd):
            self.logged_in = None
            self._refresh_state()
            self.info.setText(hints[mode] + "  When it says <i>Login successfully</i>, click <b>Check login</b>.")
            self.info.setTextFormat(Qt.TextFormat.RichText)
            self.info.setWordWrap(True)
            self.b_check.setVisible(True)
            self.b_check.setEnabled(True)
        else:
            import shlex
            QtWidgets.QApplication.clipboard().setText(shlex.join(cmd))
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "No terminal program was found. The login command was copied - paste it into "
                "a terminal, finish the login there, then click Check login.\n\n" + shlex.join(cmd))
            self.b_check.setVisible(True)

    def check(self, quiet=False, then_list=False):
        self._save_proxy()
        self._set_busy(True, "Connecting to Telegram…")
        self._bg(lambda: tg.check_login(self.s), lambda r, e: self._checked(r, e, quiet, then_list))

    def _checked(self, res, err, quiet, then_list):
        self.logged_in = bool(res) if not err else None
        self._set_busy(False, "")
        if err:
            msg = str(err)
            if "open db" in msg or "timeout" in msg.lower() and "db" in msg.lower():
                msg = "The login window is still open - finish the login there (or close it) first."
            self.info.setText(f"<span style='color:#c62828'>{msg}</span>")
            if not quiet:
                self._error(msg)
        elif not res and not quiet:
            self.info.setText("Not logged in yet.")
        elif res:
            self.info.setText("Ready. Enter a channel and click List files.")
            if then_list and self.chat.text().strip():
                self.list_files()

    def logout(self):
        r = QtWidgets.QMessageBox.question(
            self, APP_NAME, "Remove the saved Telegram login from this computer?\n\n"
            "To end the session completely, also remove it in Telegram › Settings › Devices.")
        if r != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if tg.TDL_LOCK.locked():
            return self._error("A Telegram download is running - stop it first.")
        tg.logout()
        self.logged_in = False
        self.tree.clear()
        self.entries = []
        self._refresh_state()
        self.info.setText("Logged out.")

    # -------------------------------------------------------------- files
    def list_files(self):
        if self.busy:
            if self.b_list.text() == "Cancel":
                self.cancel_flag = True
            return
        text = self.chat.text().strip()
        try:
            tg.parse_chat(text)
        except ValueError as e:
            return self._error(e)
        self._save_proxy()
        if self.last.value() != self.s.get("telegram_last"):
            self.s["telegram_last"] = self.last.value()
            self.s.save()
        self._set_busy(True, "Reading the chat from Telegram… (large channels can take a minute)")
        self.b_list.setEnabled(True)
        self.b_list.setText("Cancel")
        n = self.last.value()
        self._bg(lambda: tg.list_files(self.s, text, n, cancel=lambda: self.cancel_flag), self._listed)

    def _listed(self, res, err):
        self._set_busy(False, "")
        if err:
            if "Not logged in" in str(err):
                self.logged_in = False
                self._refresh_state()
            self.info.setText(f"<span style='color:#c62828'>{err}</span>")
            if str(err) != "Cancelled":
                self._error(err)
            return
        self.logged_in = True
        self._refresh_state()
        self.chat_name, self.entries = res
        self._fill()

    def _fill(self):
        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        counts = {}
        for e in self.entries:
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1
            it = _SortItem([e["name"], human_size(e["size"]) if e["size"] > 0 else "?",
                            TYPE_NAMES.get(e["kind"], e["kind"]),
                            _hms(e["duration"]),
                            time.strftime("%Y-%m-%d", time.localtime(e["date"])) if e["date"] else "",
                            " ".join((e["caption"] or "").split())[:200]])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(0, Qt.CheckState.Checked if e["kind"] == "video" else Qt.CheckState.Unchecked)
            it.setData(0, Qt.ItemDataRole.UserRole, e)
            it.setData(1, Qt.ItemDataRole.UserRole, e["size"])
            it.setData(3, Qt.ItemDataRole.UserRole, e["duration"])
            it.setData(4, Qt.ItemDataRole.UserRole, e["date"])
            it.setData(2, Qt.ItemDataRole.UserRole, e["kind"])
            it.setToolTip(0, e["link"])
            it.setToolTip(5, e["caption"])
            self.tree.addTopLevelItem(it)
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(4, Qt.SortOrder.AscendingOrder)
        self.tree.blockSignals(False)
        self.types.set_counts(counts)
        self._apply_filter()

    def _rows(self):
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _apply_filter(self):
        f = self.filter.text().strip().lower()
        for it in self._rows():
            it.setHidden(not self.types.allowed(it.data(2, Qt.ItemDataRole.UserRole)) or
                         (bool(f) and f not in (it.text(0) + " " + it.text(5)).lower()))
        self._update_total()

    def _check_all(self, on):
        self.tree.blockSignals(True)
        for it in self._rows():
            if not it.isHidden():
                it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._update_total()

    def _check_selected(self):
        self.tree.blockSignals(True)
        for it in self.tree.selectedItems():
            it.setCheckState(0, Qt.CheckState.Checked)
        self.tree.blockSignals(False)
        self._update_total()

    def _checked_rows(self):
        return [it for it in self._rows() if it.checkState(0) == Qt.CheckState.Checked and not it.isHidden()]

    def _update_total(self):
        rows = self._checked_rows()
        total = sum(max(0, it.data(1, Qt.ItemDataRole.UserRole) or 0) for it in rows)
        shown = sum(1 for it in self._rows() if not it.isHidden())
        if self.entries:
            self.info.setText(f"Checked: {len(rows)} file(s), {human_size(total)}   |   "
                              f"{shown} shown of {len(self.entries)} media message(s)")

    def add(self):
        rows = self._checked_rows()
        if not rows:
            return self._error("Check the files to download first.")
        folder = self.folder.text().strip()
        if not folder:
            return self._error("Choose a folder.")
        # left at the default (the Video folder): every type goes to its own category folder
        by_category = os.path.normpath(folder) == os.path.normpath(str(self.s.dir_for_category("Video")))
        chat = getattr(self, "chat_name", "") or "Telegram"
        sub = tg.safe_name("Saved Messages" if chat == "me" else chat) if self.subfolder.isChecked() else ""
        added = 0
        for row in rows:
            e = row.data(0, Qt.ItemDataRole.UserRole)
            name = tg.safe_name(row.text(0).strip()) or e["name"]
            if not os.path.splitext(name)[1] and os.path.splitext(e["name"])[1]:
                name += os.path.splitext(e["name"])[1]
            cat = CATEGORY_OF.get(e["kind"]) or self.s.category_for(name)
            base = str(self.s.dir_for_category(cat)) if by_category else folder
            it = self.m.new_item(e["link"], name, os.path.join(base, sub) if sub else base, cat, kind=KIND_TELEGRAM, size=e["size"],
                                 page_url=e["link"], description=" ".join((e["caption"] or "").split())[:300],
                                 headers={"tg_chat": str(e.get("chat_id") or ""), "tg_msg": str(e["id"])})
            self.m.add(it, start=False, queue=MAIN_QUEUE)
            added += 1
        if self.start_now.isChecked():
            self.m.start_queue()
        self.info.setText(f"{added} file(s) added to the queue.")
        self.accept()
