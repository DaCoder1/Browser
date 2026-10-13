"""Kestrel main window, modes, key handling and commands."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtCore import QBuffer, QByteArray, QEvent, QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication, QKeyEvent, QKeySequence
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QStackedWidget,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kestrel import APP_NAME, __version__, pages
from kestrel.config import CACHE_DIR, DATA_DIR, Config
from kestrel.storage import Storage
from kestrel.theme import Palette, load_palette, theme_signature

JS_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld
JS_LIB = (Path(__file__).parent / "js" / "kestrel.js").read_text()
SCHEME = b"kestrel"


class Mode(Enum):
    NORMAL = "NORMAL"
    INSERT = "INSERT"
    HINT = "HINT"
    COMMAND = "COMMAND"
    PASSTHROUGH = "PASSTHROUGH"


# --------------------------------------------------------------------------
# Key handling helpers
# --------------------------------------------------------------------------

SPECIAL_KEYS = {
    Qt.Key.Key_Escape: "Esc", Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backtab: "Tab",
    Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Backspace: "BS",
    Qt.Key.Key_Delete: "Del", Qt.Key.Key_Space: "Space", Qt.Key.Key_Up: "Up",
    Qt.Key.Key_Down: "Down", Qt.Key.Key_Left: "Left", Qt.Key.Key_Right: "Right",
    Qt.Key.Key_PageUp: "PgUp", Qt.Key.Key_PageDown: "PgDown", Qt.Key.Key_Home: "Home",
    Qt.Key.Key_End: "End", Qt.Key.Key_Insert: "Ins",
    **{getattr(Qt.Key, f"Key_F{i}"): f"F{i}" for i in range(1, 13)},
}
MODIFIER_KEYS = {
    Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    Qt.Key.Key_Super_L, Qt.Key.Key_Super_R, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock,
}


def key_token(ev: QKeyEvent) -> str | None:
    """Turn a key event into vim-ish notation: 'j', 'G', '<C-d>', '<Esc>'."""
    key = Qt.Key(ev.key())
    if key in MODIFIER_KEYS:
        return None
    mods = ev.modifiers()
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    if key in SPECIAL_KEYS:
        name = SPECIAL_KEYS[key]
        shift = shift or key == Qt.Key.Key_Backtab
    else:
        text = ev.text()
        if text and text.isprintable() and not ctrl and not alt and not meta:
            return text
        name = QKeySequence(key.value).toString().lower() if not text or ctrl or alt else text
        if not name:
            return None
        shift = shift and not name.isalpha()
    prefix = "".join(p for p, on in (("C-", ctrl), ("A-", alt), ("M-", meta), ("S-", shift)) if on)
    return f"<{prefix}{name}>"


# --------------------------------------------------------------------------
# URL handling
# --------------------------------------------------------------------------

HOST_RE = re.compile(r"^(localhost|[\w-]+(\.[\w-]+)+|\d{1,3}(\.\d{1,3}){3}|\[[0-9a-f:]+\])(:\d+)?([/?#].*)?$", re.I)


def text_to_url(text: str, cfg: Config) -> QUrl:
    text = text.strip()
    if not text:
        return QUrl(cfg.homepage)
    words = text.split()
    if len(words) > 1 and words[0] in cfg.search_engines:
        return QUrl(cfg.search_engines[words[0]].replace("{}", quote_plus(" ".join(words[1:]))))
    if len(words) == 1:
        if re.match(r"^[a-z][a-z0-9+.-]*:", text, re.I) and not re.match(r"^[\w.-]+:\d+", text):
            return QUrl(text)
        if HOST_RE.match(text):
            local = re.match(r"^(localhost|127\.|\d{1,3}(\.\d{1,3}){3}|\[)", text)
            return QUrl(("http://" if local else "https://") + text)
        if text.startswith(("/", "~")) and Path(text).expanduser().exists():
            return QUrl.fromLocalFile(str(Path(text).expanduser()))
    engine = cfg.search_engines.get(cfg.search_engine, next(iter(cfg.search_engines.values())))
    return QUrl(engine.replace("{}", quote_plus(text)))


def pretty_url(url: QUrl) -> str:
    s = url.toDisplayString()
    if url.scheme() == "kestrel":
        s = s.rstrip("/")
    return s


# --------------------------------------------------------------------------
# Web engine pieces
# --------------------------------------------------------------------------


class SchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves kestrel://start and kestrel://help."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        url = job.requestUrl()
        name = (url.host() or url.path().strip("/")).lower()
        w = self.window
        if name in ("start", "newtab", ""):
            html = pages.start_page(
                w.palette_, w.cfg.font, w.storage.top_sites(10), w.storage.search_bookmarks("", 10)
            )
        elif name == "help":
            html = pages.help_page(w.palette_, w.cfg.font, w.cfg.bindings, w.cfg.search_engines)
        else:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        buf = QBuffer(job)
        buf.setData(QByteArray(html.encode()))
        buf.open(QBuffer.OpenModeFlag.ReadOnly)
        job.reply(b"text/html", buf)


class Page(QWebEnginePage):
    modeRequested = pyqtSignal(str)

    def __init__(self, profile: QWebEngineProfile, window: "MainWindow"):
        super().__init__(profile, window)
        self.window = window

    def createWindow(self, _type):  # target=_blank, window.open()
        background = _type == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        view = self.window.new_tab(None, background=background)
        return view.page()

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith("__kestrel:mode:"):
            self.modeRequested.emit(message.rsplit(":", 1)[1])


class WebView(QWebEngineView):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window_ = window
        page = Page(window.profile, window)
        self.setPage(page)
        page.modeRequested.connect(lambda m: window.page_mode_request(self, m))
        page.fullScreenRequested.connect(window.on_fullscreen_request)
        page.linkHovered.connect(window.on_link_hovered)
        page.scrollPositionChanged.connect(lambda _: window.update_status() if self is window.view() else None)
        if hasattr(page, "permissionRequested"):
            page.permissionRequested.connect(window.on_permission_request)
        self.loadProgress.connect(lambda p: window.on_progress(self, p))
        self.loadFinished.connect(lambda ok: window.on_load_finished(self, ok))
        self.urlChanged.connect(lambda u: window.on_url_changed(self, u))
        self.titleChanged.connect(lambda t: window.on_title_changed(self, t))
        self.iconChanged.connect(lambda i: window.on_icon_changed(self, i))
        self.progress = 100
        self.lazy_url: QUrl | None = None  # restored tab, not loaded until shown
        self.setZoomFactor(window.cfg.default_zoom)

    def current_url(self) -> QUrl:
        return self.lazy_url or self.url()

    def js(self, code: str, callback=None) -> None:
        if callback is None:
            self.page().runJavaScript(code, JS_WORLD)
        else:
            self.page().runJavaScript(code, JS_WORLD, callback)


# --------------------------------------------------------------------------
# Chrome: status bar, command line, completion
# --------------------------------------------------------------------------


class CommandLine(QLineEdit):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window_ = window
        self.textEdited.connect(window.on_command_edited)
        self.returnPressed.connect(window.on_command_enter)

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        w = self.window_
        key, mods = ev.key(), ev.modifiers()
        ctrl = mods & Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_Escape or (ctrl and key == Qt.Key.Key_BracketLeft):
            w.leave_command()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Down) or (ctrl and key in (Qt.Key.Key_N, Qt.Key.Key_J)):
            w.completion.step(1)
        elif key in (Qt.Key.Key_Backtab, Qt.Key.Key_Up) or (ctrl and key in (Qt.Key.Key_P, Qt.Key.Key_K)):
            w.completion.step(-1)
        elif ctrl and key == Qt.Key.Key_W:
            # delete previous word, like a shell
            pos = self.cursorPosition()
            text = self.text()
            start = len(text[:pos].rstrip().rsplit(" ", 1)[0]) if " " in text[:pos].rstrip() else 0
            if start and start < pos:
                start += 1
            self.setText(text[:start] + text[pos:])
            self.setCursorPosition(start)
            w.on_command_edited(self.text())
        elif ctrl and key == Qt.Key.Key_U:
            self.setText(self.text()[self.cursorPosition():])
            self.setCursorPosition(0)
            w.on_command_edited(self.text())
        elif key == Qt.Key.Key_Backspace and not self.text():
            w.leave_command()
        else:
            super().keyPressEvent(ev)


class Completion(QTreeWidget):
    """Popup list above the command line."""

    MAX_ROWS = 12

    def __init__(self, parent: QWidget, window: "MainWindow"):
        super().__init__(parent)
        self.window_ = window
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.values: list[str] = []
        self.hide()

    def set_rows(self, rows: list[tuple[str, str, str]]) -> None:
        """rows: (left, right, value-to-insert)"""
        self.clear()
        self.values = []
        for left, right, value in rows[:200]:
            item = QTreeWidgetItem([left, right])
            item.setToolTip(0, left)
            self.addTopLevelItem(item)
            self.values.append(value)
        self.setVisible(bool(rows))
        self.window_.layout_overlays()

    def step(self, delta: int) -> None:
        n = self.topLevelItemCount()
        if not n:
            return
        idx = self.indexOfTopLevelItem(self.currentItem()) if self.currentItem() else -1
        idx = (idx + delta) % n if idx >= 0 else (0 if delta > 0 else n - 1)
        self.setCurrentItem(self.topLevelItem(idx))
        self.scrollToItem(self.topLevelItem(idx))
        self.window_.on_completion_selected(self.values[idx])

    def preferred_height(self) -> int:
        rows = min(self.topLevelItemCount(), self.MAX_ROWS)
        h = self.sizeHintForRow(0) if rows else 0
        return rows * max(h, 22) + 6


class StatusBar(QWidget):
    def __init__(self, parent: QWidget, window: "MainWindow"):
        super().__init__(parent)
        self.setObjectName("statusbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)
        self.mode = QLabel("NORMAL")
        self.mode.setObjectName("mode")
        self.prefix = QLabel(":")
        self.prefix.setObjectName("prefix")
        self.cmd = CommandLine(window)
        self.cmd.setObjectName("cmd")
        self.url = QLabel()
        self.url.setObjectName("url")
        self.url.setTextFormat(Qt.TextFormat.RichText)
        self.url.setMinimumWidth(50)
        self.msg = QLabel()
        self.msg.setObjectName("msg")
        self.keys = QLabel()
        self.keys.setObjectName("keys")
        self.info = QLabel()
        self.info.setObjectName("info")
        lay.addWidget(self.mode)
        lay.addWidget(self.prefix)
        lay.addWidget(self.cmd, 1)
        lay.addWidget(self.url, 1)
        lay.addWidget(self.msg)
        lay.addWidget(self.keys)
        lay.addWidget(self.info)
        self.prefix.hide()
        self.cmd.hide()


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, storage: Storage, profile: QWebEngineProfile, private: bool = False):
        super().__init__()
        self.cfg = cfg
        self.storage = storage
        self.profile = profile
        self.private = private
        self.palette_: Palette = load_palette()
        self._theme_sig = theme_signature()
        self.mode = Mode.NORMAL
        self.pending = ""
        self.count = ""
        self.closed_tabs: list[str] = []
        self.search_text = ""
        self.search_backwards = False
        self.command_prefix = ":"
        self.pending_permission = None
        self.saving_session = not private

        self.setWindowTitle("Kestrel")
        central = QWidget(self)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.tabbar = QTabBar(central)
        self.tabbar.setDrawBase(False)
        self.tabbar.setExpanding(False)
        self.tabbar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabbar.setMovable(True)
        self.tabbar.currentChanged.connect(self.on_tab_changed)
        self.tabbar.tabMoved.connect(self.on_tab_moved)
        self.stack = QStackedWidget(central)
        self.status = StatusBar(central, self)
        lay.addWidget(self.tabbar)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.status)
        self.setCentralWidget(central)
        self.completion = Completion(central, self)

        self.msg_timer = QTimer(self, singleShot=True, timeout=lambda: self.status.msg.clear())
        self.key_timer = QTimer(self, singleShot=True, interval=1000, timeout=self.flush_pending)
        self.session_timer = QTimer(self, singleShot=True, interval=1500, timeout=self.save_session)
        self.theme_timer = QTimer(self, interval=2000, timeout=self.check_theme)
        self.theme_timer.start()

        self.apply_theme()
        self.update_status()

    # -- tabs ---------------------------------------------------------------
    def views(self) -> list[WebView]:
        return [self.stack.widget(i) for i in range(self.stack.count())]

    def view(self) -> WebView | None:
        return self.stack.currentWidget()

    def new_tab(self, url: QUrl | str | None, background: bool = False, at_end: bool = False,
                lazy: bool = False) -> WebView:
        view = WebView(self)
        if url is not None:
            url = QUrl(url) if isinstance(url, str) else url
            if lazy:
                view.lazy_url = url
            else:
                view.load(url)
        idx = self.tabbar.currentIndex() + 1 if self.tabbar.count() and not at_end else self.tabbar.count()
        self.stack.insertWidget(idx, view)
        self.tabbar.insertTab(idx, "New Tab")
        if not background or self.tabbar.count() == 1:
            self.tabbar.setCurrentIndex(idx)
        self.refresh_tab_titles()
        self.schedule_session_save()
        return view

    def close_tab(self, idx: int | None = None) -> None:
        idx = self.tabbar.currentIndex() if idx is None else idx
        view = self.stack.widget(idx)
        if view is None:
            return
        url = view.current_url().toString()
        if url:
            self.closed_tabs.append(url)
        if self.tabbar.count() == 1:
            view.load(QUrl(self.cfg.homepage))
            return
        self.tabbar.removeTab(idx)
        self.stack.removeWidget(view)
        view.page().deleteLater()
        view.deleteLater()
        self.refresh_tab_titles()
        self.schedule_session_save()

    def on_tab_changed(self, idx: int) -> None:
        if idx < 0:
            return
        self.stack.setCurrentIndex(idx)
        view = self.view()
        if view is not None and view.lazy_url is not None:
            view.load(view.lazy_url)
            view.lazy_url = None
        if self.mode in (Mode.INSERT, Mode.HINT):
            self.set_mode(Mode.NORMAL)
        if self.mode != Mode.COMMAND:
            self.focus_view()
        self.update_title()
        self.update_status()

    def on_tab_moved(self, frm: int, to: int) -> None:
        w = self.stack.widget(frm)
        self.stack.removeWidget(w)
        self.stack.insertWidget(to, w)
        self.stack.setCurrentIndex(self.tabbar.currentIndex())
        self.refresh_tab_titles()
        self.schedule_session_save()

    def refresh_tab_titles(self) -> None:
        for i, v in enumerate(self.views()):
            if v.lazy_url is not None:
                title = self.storage.title_for(v.lazy_url.toString()) or pretty_url(v.lazy_url)
            else:
                title = v.title() or pretty_url(v.url()) or "New Tab"
            if v.url().scheme() == "kestrel" and v.url().host() in ("start", ""):
                title = "New Tab"
            label = f"{i + 1}  {title}"
            self.tabbar.setTabText(i, label[:40] + ("…" if len(label) > 40 else ""))
            self.tabbar.setTabToolTip(i, v.url().toString())
        show = self.cfg.show_tabs
        self.tabbar.setVisible(show == "always" or (show == "multiple" and self.tabbar.count() > 1))

    def focus_view(self) -> None:
        v = self.view()
        if v is not None:
            (v.focusProxy() or v).setFocus()

    # -- web view signals ---------------------------------------------------
    def on_progress(self, view: WebView, p: int) -> None:
        view.progress = p
        if view is self.view():
            self.update_status()

    def on_load_finished(self, view: WebView, ok: bool) -> None:
        view.progress = 100
        if ok and not self.private:
            self.storage.add_visit(view.url().toString(), view.title())
        if view is self.view():
            self.update_status()

    def on_url_changed(self, view: WebView, url: QUrl) -> None:
        if view is self.view():
            self.update_status()
            self.update_title()
        self.refresh_tab_titles()
        self.schedule_session_save()

    def on_title_changed(self, view: WebView, title: str) -> None:
        if not self.private:
            self.storage.set_title(view.url().toString(), title)
        self.refresh_tab_titles()
        if view is self.view():
            self.update_title()

    def on_icon_changed(self, view: WebView, icon) -> None:
        idx = self.stack.indexOf(view)
        if idx >= 0:
            self.tabbar.setTabIcon(idx, icon)

    def on_link_hovered(self, url: str) -> None:
        self.hovered = url
        self.update_status()

    def on_fullscreen_request(self, req) -> None:
        req.accept()
        if req.toggleOn():
            self.tabbar.hide()
            self.status.hide()
            self.showFullScreen()
        else:
            self.status.show()
            self.refresh_tab_titles()
            self.showNormal()

    def on_permission_request(self, permission) -> None:
        origin = permission.origin().host() or permission.origin().toString()
        kind = permission.permissionType().name
        nice = re.sub(r"(?<!^)([A-Z])", r" \1", kind).lower()
        self.pending_permission = permission
        self.show_message(f"{origin} wants {nice} — press y to allow, n to deny", "warn", 0)

    def page_mode_request(self, view: WebView, mode: str) -> None:
        if view is not self.view():
            return
        if mode == "insert" and self.mode == Mode.NORMAL:
            self.set_mode(Mode.INSERT)
        elif mode == "normal" and self.mode == Mode.INSERT:
            self.set_mode(Mode.NORMAL, blur=False)

    def update_title(self) -> None:
        v = self.view()
        t = v.title() if v else ""
        self.setWindowTitle(f"{t} — Kestrel" if t else "Kestrel")

    # -- status -------------------------------------------------------------
    hovered = ""

    def update_status(self) -> None:
        p = self.palette_
        s = self.status
        s.mode.setText(f" {self.mode.value} ")
        s.mode.setProperty("mode", self.mode.value.lower())
        s.mode.style().unpolish(s.mode)
        s.mode.style().polish(s.mode)
        s.keys.setText(self.count + self.pending)
        v = self.view()
        if v is None:
            return
        if self.hovered:
            s.url.setText(f'<span style="color:{p.cyan}">→ {_esc(self.hovered)}</span>')
        else:
            url = v.url()
            text = _esc(pretty_url(url))
            if url.scheme() == "https":
                text = f'<span style="color:{p.green}">https://</span>' + text[len("https://"):]
            elif url.scheme() == "http":
                text = f'<span style="color:{p.red}">http://</span>' + text[len("http://"):]
            s.url.setText(text)
        bits = []
        if v.progress < 100:
            bits.append(f"{v.progress}%")
        page = v.page()
        content_h = page.contentsSize().height()
        view_h = v.height() / max(v.zoomFactor(), 0.01)
        if content_h > view_h + 1:
            y = page.scrollPosition().y()
            pct = round(100 * y / max(1.0, content_h - view_h))
            bits.append("Top" if y <= 0 else "Bot" if pct >= 100 else f"{pct}%")
        if abs(v.zoomFactor() - 1.0) > 0.01:
            bits.append(f"{round(v.zoomFactor() * 100)}%z")
        if self.storage.is_bookmarked(v.url().toString()):
            bits.append("★")
        if self.private:
            bits.append("private")
        bits.append(f"[{self.tabbar.currentIndex() + 1}/{self.tabbar.count()}]")
        s.info.setText("  ".join(bits))

    def show_message(self, text: str, level: str = "info", timeout: int = 3000) -> None:
        p = self.palette_
        color = {"info": p.fg, "warn": p.yellow, "error": p.red, "ok": p.green}.get(level, p.fg)
        self.status.msg.setStyleSheet(f"color: {color};")
        self.status.msg.setText(text)
        if timeout:
            self.msg_timer.start(timeout)
        else:
            self.msg_timer.stop()

    # -- theme --------------------------------------------------------------
    def check_theme(self) -> None:
        sig = theme_signature()
        if sig != self._theme_sig:
            self._theme_sig = sig
            self.palette_ = load_palette()
            self.apply_theme()
            for v in self.views():
                if v.url().scheme() == "kestrel":
                    v.reload()
            self.show_message(f"theme: {self.palette_.name}", "ok")

    def apply_theme(self) -> None:
        p = self.palette_
        f = self.cfg.font
        fs = self.cfg.font_size
        self.setStyleSheet(f"""
        QMainWindow, QWidget {{ background: {p.bg}; color: {p.fg}; }}
        * {{ font-family: '{f}', 'JetBrains Mono', monospace; font-size: {fs}pt; }}
        QTabBar {{ background: {p.bg_alt}; }}
        QTabBar::tab {{ background: {p.bg_alt}; color: {p.muted}; padding: 5px 14px;
            border: none; border-bottom: 2px solid transparent; max-width: 260px; }}
        QTabBar::tab:selected {{ background: {p.bg}; color: {p.fg}; border-bottom: 2px solid {p.accent}; }}
        QTabBar::tab:hover:!selected {{ color: {p.fg}; }}
        QTabBar QToolButton {{ background: {p.bg_alt}; border: none; }}
        #statusbar {{ background: {p.bg_alt}; min-height: 24px; max-height: 24px; }}
        #statusbar QLabel {{ background: transparent; }}
        #statusbar #mode {{ color: {p.bg}; background: {p.accent}; font-weight: bold; padding: 0 6px; }}
        #statusbar #mode[mode="insert"] {{ background: {p.green}; }}
        #statusbar #mode[mode="hint"] {{ background: {p.yellow}; }}
        #statusbar #mode[mode="command"] {{ background: {p.magenta}; }}
        #statusbar #mode[mode="passthrough"] {{ background: {p.red}; }}
        #statusbar #prefix {{ color: {p.accent}; font-weight: bold; }}
        #cmd {{ background: transparent; border: none; color: {p.fg};
            selection-background-color: {p.selection}; }}
        #statusbar #keys {{ color: {p.yellow}; }}
        #statusbar #info {{ color: {p.muted}; }}
        QTreeWidget {{ background: {p.bg_alt}; border: none; border-top: 1px solid {p.line};
            outline: none; padding: 2px 0; }}
        QTreeWidget::item {{ padding: 3px 8px; border: none; }}
        QTreeWidget::item:selected {{ background: {p.selection}; color: {p.fg}; }}
        QToolTip {{ background: {p.bg_alt}; color: {p.fg}; border: 1px solid {p.line}; }}
        """)
        self.update_status()

    # -- modes --------------------------------------------------------------
    def set_mode(self, mode: Mode, blur: bool = True) -> None:
        old = self.mode
        self.mode = mode
        self.pending = ""
        self.count = ""
        v = self.view()
        if old == Mode.HINT and mode != Mode.HINT and v:
            v.js("__kestrel.clearHints()")
        if mode == Mode.NORMAL and old in (Mode.INSERT, Mode.PASSTHROUGH) and v and blur:
            v.js("__kestrel.blur()")
        self.update_status()

    def leave_command(self) -> None:
        if self.command_prefix == "/" and not self.status.cmd.text():
            self.view() and self.view().findText("")
        self.status.cmd.hide()
        self.status.prefix.hide()
        self.status.url.show()
        self.completion.set_rows([])
        self.set_mode(Mode.NORMAL)
        self.focus_view()

    # -- key dispatch -------------------------------------------------------
    def handle_key(self, ev: QKeyEvent) -> bool:
        """Return True if we consumed the key."""
        tok = key_token(ev)
        if tok is None:
            return False
        if self.mode == Mode.COMMAND:
            return False  # CommandLine handles its own keys
        if self.mode == Mode.INSERT:
            if tok in ("<Esc>", "<C-[>"):
                self.set_mode(Mode.NORMAL)
                return True
            return False
        if self.mode == Mode.PASSTHROUGH:
            if tok == "<S-Esc>":
                self.set_mode(Mode.NORMAL)
                return True
            return False
        if self.mode == Mode.HINT:
            self.hint_key(tok)
            return True

        # NORMAL
        if self.pending_permission is not None and tok in ("y", "n", "<Esc>"):
            perm = self.pending_permission
            self.pending_permission = None
            (perm.grant if tok == "y" else perm.deny)()
            self.show_message("allowed" if tok == "y" else "denied", "ok" if tok == "y" else "warn")
            return True
        if not self.pending and tok.isdigit() and (tok != "0" or self.count):
            if not any(k.startswith(tok) for k in self.cfg.bindings):
                self.count += tok
                self.update_status()
                return True
        seq = self.pending + tok
        exact = self.cfg.bindings.get(seq)
        longer = any(k != seq and k.startswith(seq) for k in self.cfg.bindings)
        if exact and not longer:
            self.run_binding(exact)
            return True
        if longer:
            self.pending = seq
            self.key_timer.start()
            self.update_status()
            return True
        # unbound
        had_pending = bool(self.pending or self.count)
        self.pending = ""
        self.count = ""
        self.update_status()
        if had_pending:
            return True
        # Let Enter and modifier chords (Ctrl+C, Ctrl+A ...) reach the page.
        if tok == "<Enter>" or tok.startswith(("<C-", "<A-")):
            return False
        return True

    def flush_pending(self) -> None:
        cmd = self.cfg.bindings.get(self.pending)
        if cmd:
            self.run_binding(cmd)
        else:
            self.pending = ""
            self.count = ""
            self.update_status()

    def run_binding(self, cmd: str) -> None:
        count = int(self.count) if self.count else None
        self.pending = ""
        self.count = ""
        self.key_timer.stop()
        self.run_command(cmd, count)
        self.update_status()

    # -- hints --------------------------------------------------------------
    def start_hints(self, action: str = "click") -> None:
        v = self.view()
        if not v:
            return
        p = self.palette_
        opts = {"chars": self.cfg.hint_chars, "action": action, "bg": p.yellow, "fg": p.bg,
                "border": p.bg, "dim": p.muted}

        def done(count):
            if not count:
                self.show_message("no links to hint", "warn")
                self.set_mode(Mode.NORMAL)

        self.set_mode(Mode.HINT)
        self.hint_action = action
        v.js(f"__kestrel.showHints({json.dumps(opts)})", done)

    def hint_key(self, tok: str) -> None:
        v = self.view()
        if tok in ("<Esc>", "<C-[>") or not v:
            self.set_mode(Mode.NORMAL)
            return
        if tok == "<BS>":
            key = "<BS>"
        elif len(tok) == 1:
            key = tok
        else:
            return

        def result(res):
            res = res or {}
            status = res.get("status")
            if status == "pending":
                return
            self.mode = Mode.NORMAL
            if res.get("href"):
                self.new_tab(QUrl(res["href"]), background=True)
                self.show_message("opened in background tab")
            elif "yank" in res:
                QGuiApplication.clipboard().setText(res["yank"])
                self.show_message(f"yanked {res['yank'][:80]}", "ok")
            if res.get("editable"):
                self.set_mode(Mode.INSERT)
            else:
                self.set_mode(Mode.NORMAL)

        v.js(f"__kestrel.hintKey({json.dumps(key)})", result)

    # -- command line -------------------------------------------------------
    def open_command(self, text: str = "", prefix: str = ":") -> None:
        v = self.view()
        if v is not None:
            text = text.replace("{url}", v.url().toString())
        if prefix == ":" and text.startswith("/"):
            prefix, text = "/", text[1:]
        self.command_prefix = prefix
        self.set_mode(Mode.COMMAND)
        s = self.status
        s.url.hide()
        s.prefix.setText(prefix)
        s.prefix.show()
        s.cmd.show()
        s.cmd.setText(text)
        s.cmd.setFocus()
        s.cmd.end(False)
        self.on_command_edited(text)

    def on_command_edited(self, text: str) -> None:
        if self.command_prefix == "/":
            self.completion.set_rows([])
            v = self.view()
            if v:
                v.findText(text)
            return
        self.completion.set_rows(self.complete(text))

    def on_completion_selected(self, value: str) -> None:
        self.status.cmd.setText(value)

    def on_command_enter(self) -> None:
        text = self.status.cmd.text()
        prefix = self.command_prefix
        self.status.cmd.hide()
        self.status.prefix.hide()
        self.status.url.show()
        self.completion.set_rows([])
        self.set_mode(Mode.NORMAL)
        self.focus_view()
        if prefix == "/":
            self.search_text = text
            self.search_backwards = False
            self.run_command("search-next")
        elif text.strip():
            self.run_command(text.strip())

    COMMANDS = [
        "open", "open -t", "buffer", "tab-close", "tab-undo", "tab-next", "tab-prev", "tab-clone",
        "tab-only", "back", "forward", "reload", "reload -f", "stop", "home", "help", "bookmark",
        "zoom in", "zoom out", "zoom reset", "yank url", "yank title", "devtools", "view-source",
        "mode insert", "mode passthrough", "private", "quit", "quit --no-save", "theme-reload",
    ]

    def complete(self, text: str) -> list[tuple[str, str, str]]:
        cmd, sep, rest = text.partition(" ")
        if not sep:
            return [(c, "", c + " ") for c in self.COMMANDS if c.startswith(cmd)][:30]
        if cmd == "open":
            flag = ""
            if rest.startswith("-t ") or rest == "-t":
                flag, rest = "-t ", rest[3:]
            rows = []
            seen = set()
            for url, title in self.storage.search_bookmarks(rest, 10):
                seen.add(url)
                rows.append(("★ " + (title or url), url, f"open {flag}{url}"))
            for url, title in self.storage.search_history(rest, 40):
                if url not in seen:
                    rows.append((title or url, url, f"open {flag}{url}"))
            return rows
        if cmd == "buffer":
            words = rest.lower().split()
            rows = []
            for i, v in enumerate(self.views()):
                url = v.current_url().toString()
                hay = f"{i + 1} {v.title()} {url}".lower()
                if all(w in hay for w in words):
                    rows.append((f"{i + 1}: {v.title() or 'New Tab'}", url, f"buffer {i + 1}"))
            return rows
        return []

    # -- commands -----------------------------------------------------------
    def run_command(self, line: str, count: int | None = None) -> None:
        cmd, _, arg = line.partition(" ")
        argv = arg.split()
        n = count or 1
        v = self.view()
        step = self.cfg.scroll_step
        try:
            if cmd == "scroll":
                dx, dy = {"down": (0, step), "up": (0, -step), "left": (-step, 0), "right": (step, 0)}[argv[0]]
                v.js(f"__kestrel.scrollBy({dx * n}, {dy * n})")
            elif cmd == "scroll-page":
                v.js(f"__kestrel.scrollPage({float(argv[0]) * n})")
            elif cmd == "scroll-to":
                if count and argv[0] == "bottom":  # 50G -> 50%
                    v.js(f"(function(){{var e=document.scrollingElement;e.scrollTo(0,(e.scrollHeight-innerHeight)*{min(count, 100)}/100)}})()")
                else:
                    v.js(f"__kestrel.scrollTo({argv[0]!r})")
            elif cmd == "back":
                for _ in range(n):
                    v.back()
            elif cmd == "forward":
                for _ in range(n):
                    v.forward()
            elif cmd == "reload":
                if "-f" in argv:
                    v.page().triggerAction(QWebEnginePage.WebAction.ReloadAndBypassCache)
                else:
                    v.reload()
            elif cmd == "stop":
                v.stop()
            elif cmd == "clear":
                v.findText("")
                v.js("__kestrel.clearHints()")
                self.status.msg.clear()
                self.hovered = ""
            elif cmd == "navigate":
                url = v.url()
                if argv[0] == "root":
                    url.setPath("/")
                else:
                    path = url.path().rstrip("/")
                    url.setPath(path.rsplit("/", 1)[0] + "/" if "/" in path else "/")
                url.setQuery(None)
                url.setFragment(None)
                v.load(url)
            elif cmd == "view-source":
                self.new_tab(QUrl("view-source:" + v.url().toString()))
            elif cmd == "home":
                v.load(QUrl(self.cfg.homepage))
            elif cmd == "set-cmd":
                self.open_command(arg)
            elif cmd in ("open", "o", "tabopen", "t"):
                newtab = cmd in ("tabopen", "t")
                if arg.startswith("-t"):
                    newtab, arg = True, arg[2:]
                if not arg.strip():
                    self.open_command("open -t " if newtab else "open ")
                    return
                url = text_to_url(arg, self.cfg)
                if newtab or v is None:
                    self.new_tab(url)
                else:
                    v.load(url)
                self.focus_view()
            elif cmd == "paste":
                text = QGuiApplication.clipboard().text().strip()
                if not text:
                    self.show_message("clipboard is empty", "warn")
                    return
                self.run_command(("open -t " if "-t" in argv else "open ") + text)
            elif cmd in ("tab-next", "tab-prev"):
                c = self.tabbar.count()
                d = n if cmd == "tab-next" else -n
                self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + d) % c)
            elif cmd == "tab-focus":
                idx = count if count else int(argv[0])
                c = self.tabbar.count()
                idx = c if idx == -1 or idx > c else idx
                self.tabbar.setCurrentIndex(idx - 1)
            elif cmd in ("tab-close", "close", "q"):
                if cmd == "q" and self.tabbar.count() == 1:
                    self.close()
                    return
                for _ in range(n):
                    self.close_tab()
            elif cmd == "tab-undo":
                if self.closed_tabs:
                    self.new_tab(QUrl(self.closed_tabs.pop()))
                else:
                    self.show_message("no closed tabs", "warn")
            elif cmd == "tab-only":
                cur = self.tabbar.currentIndex()
                for i in reversed(range(self.tabbar.count())):
                    if i != cur:
                        self.close_tab(i)
            elif cmd == "tab-clone":
                self.new_tab(v.url())
            elif cmd == "tab-move":
                cur = self.tabbar.currentIndex()
                d = int(argv[0]) * n
                to = max(0, min(self.tabbar.count() - 1, cur + d))
                self.tabbar.moveTab(cur, to)
            elif cmd in ("buffer", "b"):
                if not argv:
                    self.open_command("buffer ")
                    return
                if argv[0].isdigit():
                    self.tabbar.setCurrentIndex(min(int(argv[0]), self.tabbar.count()) - 1)
                else:
                    rows = self.complete("buffer " + arg)
                    if rows:
                        self.run_command(rows[0][2])
            elif cmd == "hint":
                self.start_hints("tab" if "-t" in argv else "yank" if "-y" in argv else "click")
            elif cmd == "focus-input":
                v.js("__kestrel.focusInput()", lambda ok: self.set_mode(Mode.INSERT) if ok else
                     self.show_message("no input on page", "warn"))
            elif cmd == "yank":
                what = argv[0] if argv else "url"
                text = v.title() if what == "title" else v.url().toString()
                QGuiApplication.clipboard().setText(text)
                self.show_message(f"yanked {what}: {text[:80]}", "ok")
            elif cmd in ("search-next", "search-prev"):
                if not self.search_text:
                    return
                back = (cmd == "search-prev") != self.search_backwards
                flags = QWebEnginePage.FindFlag.FindBackward if back else QWebEnginePage.FindFlag(0)
                for _ in range(n):
                    v.findText(self.search_text, flags, self.on_find_result)
            elif cmd == "search":
                self.search_text = arg
                self.run_command("search-next")
            elif cmd == "mode":
                self.set_mode({"insert": Mode.INSERT, "passthrough": Mode.PASSTHROUGH}.get(argv[0], Mode.NORMAL))
                if self.mode == Mode.PASSTHROUGH:
                    self.show_message("passthrough: all keys go to the page — Shift+Esc to leave", "warn")
            elif cmd == "zoom":
                levels = [0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0]
                z = v.zoomFactor()
                if argv[0] == "in":
                    for _ in range(n):
                        z = next((l for l in levels if l > z + 0.01), z)
                elif argv[0] == "out":
                    for _ in range(n):
                        z = next((l for l in reversed(levels) if l < z - 0.01), z)
                elif argv[0] == "reset":
                    z = count / 100 if count else self.cfg.default_zoom
                else:
                    z = float(argv[0].rstrip("%")) / 100
                v.setZoomFactor(z)
                self.show_message(f"zoom {round(z * 100)}%")
            elif cmd == "bookmark":
                added = self.storage.toggle_bookmark(v.url().toString(), v.title())
                self.show_message("bookmarked ★" if added else "bookmark removed", "ok")
            elif cmd == "help":
                self.new_tab(QUrl("kestrel://help"))
            elif cmd == "devtools":
                self.open_devtools()
            elif cmd == "private":
                spawn_private(arg)
            elif cmd == "theme-reload":
                self._theme_sig = ""
                self.check_theme()
            elif cmd in ("quit", "qa", "wq", "x"):
                if "--no-save" in argv:
                    self.saving_session = False
                self.close()
            else:
                self.show_message(f"unknown command: {cmd}", "error")
        except (IndexError, ValueError, KeyError) as exc:
            self.show_message(f"{line.strip()}: bad argument ({exc})", "error")
        except AttributeError:
            pass  # no current view

    def on_find_result(self, result) -> None:
        if result.numberOfMatches() == 0:
            self.show_message(f"not found: {self.search_text}", "warn")
        else:
            self.show_message(f"{self.search_text}  [{result.activeMatch()}/{result.numberOfMatches()}]")

    def open_devtools(self) -> None:
        v = self.view()
        dev = QWebEngineView()
        dev.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dev.setWindowTitle(f"DevTools — {v.title()}")
        v.page().setDevToolsPage(dev.page())
        dev.resize(1000, 700)
        dev.show()
        self._devtools = dev

    # -- session ------------------------------------------------------------
    def schedule_session_save(self) -> None:
        if self.saving_session:
            self.session_timer.start()

    def save_session(self) -> None:
        if not self.saving_session:
            return
        urls = [v.current_url().toString() or v.page().requestedUrl().toString() for v in self.views()]
        self.storage.save_session([u for u in urls if u], self.tabbar.currentIndex())

    def closeEvent(self, ev) -> None:
        if self.saving_session:
            self.save_session()
        self.theme_timer.stop()
        for v in self.views():
            v.page().deleteLater()
        super().closeEvent(ev)

    # -- layout -------------------------------------------------------------
    def layout_overlays(self) -> None:
        c = self.completion
        if not c.isVisible():
            return
        h = c.preferred_height()
        y = self.status.geometry().top() - h
        c.setGeometry(0, max(0, y), self.centralWidget().width(), h)
        c.setColumnWidth(0, int(c.width() * 0.5))
        c.raise_()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.layout_overlays()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------
# Global key filter
# --------------------------------------------------------------------------


class KeyFilter(QObject):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self._last = None

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.Type.ShortcutOverride and self.window.mode == Mode.NORMAL:
            # Stop Chromium from treating our keys as editing shortcuts.
            ev.accept()
            return False
        if t != QEvent.Type.KeyPress or not isinstance(obj, QWidget):
            return False
        if obj.window() is not self.window:
            return False
        # Qt re-delivers unhandled key events to parent widgets; handle once.
        sig = (ev.timestamp(), ev.key(), int(ev.modifiers().value), ev.text())
        if sig == self._last:
            return self._last_result
        self._last = sig
        self._last_result = self.window.handle_key(ev)
        return self._last_result


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------


def make_profile(app: QApplication, cfg: Config, private: bool) -> QWebEngineProfile:
    if private:
        profile = QWebEngineProfile(app)  # off-the-record
    else:
        profile = QWebEngineProfile(APP_NAME, app)
        profile.setPersistentStoragePath(str(DATA_DIR / "webengine"))
        profile.setCachePath(str(CACHE_DIR / "webengine"))
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    # Some sites serve degraded pages to "QtWebEngine" user agents.
    profile.setHttpUserAgent(re.sub(r"QtWebEngine/\S+ ", "", profile.httpUserAgent()))
    s = profile.settings()
    A = QWebEngineSettings.WebAttribute
    s.setAttribute(A.FullScreenSupportEnabled, True)
    s.setAttribute(A.ScrollAnimatorEnabled, cfg.smooth_scrolling)
    s.setAttribute(A.JavascriptCanAccessClipboard, True)
    s.setAttribute(A.LocalStorageEnabled, True)
    s.setAttribute(A.PlaybackRequiresUserGesture, False)
    s.setAttribute(A.ForceDarkMode, cfg.force_dark)
    s.setAttribute(A.FocusOnNavigationEnabled, False)

    script = QWebEngineScript()
    script.setName("kestrel")
    script.setSourceCode(JS_LIB)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(JS_WORLD)
    script.setRunsOnSubFrames(True)
    profile.scripts().insert(script)
    return profile


def register_scheme() -> None:
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def spawn_private(url: str = "") -> None:
    args = [sys.executable, "-m", "kestrel", "--private"]
    if url:
        args.append(url)
    subprocess.Popen(args, start_new_session=True)


def setup_downloads(window: MainWindow, profile: QWebEngineProfile, cfg: Config) -> None:
    def on_download(req: QWebEngineDownloadRequest) -> None:
        cfg.downloads_dir.mkdir(parents=True, exist_ok=True)
        req.setDownloadDirectory(str(cfg.downloads_dir))
        req.accept()
        name = req.downloadFileName()
        window.show_message(f"downloading {name}…")

        def finished():
            if not req.isFinished():
                return
            ok = req.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            path = os.path.join(req.downloadDirectory(), req.downloadFileName())
            window.show_message(f"saved {path}" if ok else f"download failed: {name}", "ok" if ok else "error", 6000)
            if shutil.which("notify-send"):
                subprocess.Popen(["notify-send", "-a", "Kestrel", "Download complete" if ok else "Download failed", path])

        req.isFinishedChanged.connect(finished)

    profile.downloadRequested.connect(on_download)


def single_instance(urls: list[str], private: bool) -> QLocalServer | None:
    """Hand URLs to an already running Kestrel. Returns a server if we're the first."""
    if private:
        return None
    name = f"kestrel-{os.getuid()}"
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(("\n".join(urls) or "\x00").encode())
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return "running"  # type: ignore[return-value]
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.listen(name)
    return server


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"kestrel {__version__}")
        return 0
    if "-h" in argv or "--help" in argv:
        print("usage: kestrel [--private] [URL ...]\nKeyboard-driven browser for Omarchy. Press ? inside for keys.")
        return 0
    private = any(a in argv for a in ("--private", "--private-window", "--incognito"))
    urls = [a for a in argv[1:] if not a.startswith("--")]

    cfg = Config.load()
    palette = load_palette()
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "preferredColorScheme" not in flags:
        # 0 = dark, 1 = light: lets sites with prefers-color-scheme match the Omarchy theme.
        flags += f" --blink-settings=preferredColorScheme={1 if palette.is_light else 0}"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags.strip()

    register_scheme()
    QGuiApplication.setDesktopFileName(APP_NAME)  # Wayland app_id, for Hyprland window rules
    app = QApplication(argv[:1] + [a for a in argv[1:] if a.startswith("-platform")])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("Kestrel")
    app.setFont(QFont(cfg.font, cfg.font_size))

    server = single_instance(urls, private)
    if server == "running":
        return 0

    storage = Storage(DATA_DIR)
    profile = make_profile(app, cfg, private)
    window = MainWindow(cfg, storage, profile, private=private)
    profile.installUrlSchemeHandler(SCHEME, SchemeHandler(window))
    setup_downloads(window, profile, cfg)
    app.installEventFilter(KeyFilter(window))

    if server is not None:
        def on_connection():
            conn = server.nextPendingConnection()

            def read():
                data = bytes(conn.readAll()).decode(errors="replace").strip("\x00\n ")
                for u in filter(None, data.split("\n")):
                    window.new_tab(text_to_url(u, cfg))
                if not data:
                    window.new_tab(QUrl(cfg.homepage))
                window.raise_()
                window.activateWindow()

            conn.readyRead.connect(read)

        server.newConnection.connect(on_connection)

    restored = False
    if cfg.restore_session and not private and not urls:
        tabs, current = storage.load_session()
        for u in tabs:
            window.new_tab(QUrl(u), background=True, at_end=True, lazy=True)
        if tabs:
            window.tabbar.setCurrentIndex(max(0, min(current, len(tabs) - 1)))
            window.on_tab_changed(window.tabbar.currentIndex())  # load the visible tab
            restored = True
    for u in urls:
        window.new_tab(text_to_url(u, cfg))
    if not urls and not restored:
        window.new_tab(QUrl(cfg.homepage))

    window.resize(1280, 800)
    window.show()
    window.focus_view()
    return app.exec()
