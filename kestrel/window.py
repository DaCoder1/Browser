"""A browser window: tabs, toolbar, address bar, shortcuts and commands."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from kestrel.commands import COMMANDS
from kestrel.config import CONFIG_FILE
from kestrel.keys import Mode, key_token, pretty_key
from kestrel.urls import engine_name, is_search, is_start_page, pretty_url, text_to_url
from kestrel.web import WebView
from kestrel.widgets import Completion, FindBar, InfoBar, TabBar, Toast, UrlBar, tool_button

if TYPE_CHECKING:
    from kestrel.app import Browser

ZOOM_LEVELS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0]

MENU = [
    ("tab-new", "New tab"), ("window-new", "New window"), ("private", "New private window"), None,
    ("bookmark", "Bookmark this page"), ("bookmarks", "Bookmarks…"), ("history", "History…"),
    ("tab-search", "Search tabs…"), ("palette", "Command palette…"), None,
    ("find", "Find in page…"), ("zoom in", "Zoom in"), ("zoom out", "Zoom out"), ("zoom reset", "Reset zoom"),
    ("fullscreen", "Fullscreen"), None,
    ("downloads", "Downloads folder"), ("view-source", "View page source"), ("devtools", "Developer tools"), None,
    ("help", "Keyboard shortcuts"), ("config", "Settings…"), None,
    ("quit", "Quit"),
]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class MainWindow(QMainWindow):
    def __init__(self, browser: "Browser"):
        super().__init__()
        self.browser = browser
        self.cfg = browser.cfg
        self.storage = browser.storage
        self.profile = browser.profile
        self.private = browser.private
        self.vim = self.cfg.keymap == "vim"
        self.base_mode = Mode.NORMAL if self.vim else Mode.BROWSE
        self.mode = self.base_mode
        self.pending = ""
        self.count = ""
        self.closed_tabs: list[str] = []
        self.search_text = ""
        self.hint_action = "click"
        self._activated = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Kestrel")

        central = QWidget(self)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Tab strip
        self.tabstrip = QWidget(central)
        self.tabstrip.setObjectName("tabstrip")
        self.tabstrip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tsl = QHBoxLayout(self.tabstrip)
        tsl.setContentsMargins(6, 6, 6, 0)
        tsl.setSpacing(2)
        self.tabbar = TabBar(self)
        self.tabbar.currentChanged.connect(self.on_tab_changed)
        self.tabbar.tabMoved.connect(self.on_tab_moved)
        tsl.addWidget(self.tabbar)
        tsl.addWidget(tool_button(self, "+", self.tip("New tab", "tab-new"), lambda: self.run_command("tab-new")))
        tsl.addStretch(1)

        # Toolbar
        self.toolbar = QWidget(central)
        self.toolbar.setObjectName("toolbar")
        self.toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tl = QHBoxLayout(self.toolbar)
        tl.setContentsMargins(8, 5, 8, 5)
        tl.setSpacing(4)
        self.mode_badge = QLabel()
        self.mode_badge.setObjectName("mode")
        self.mode_badge.setVisible(self.vim)
        self.back_btn = tool_button(self, "←", self.tip("Back", "back"), lambda: self.run_command("back"))
        self.fwd_btn = tool_button(self, "→", self.tip("Forward", "forward"), lambda: self.run_command("forward"))
        self.reload_btn = tool_button(self, "↻", self.tip("Reload", "reload"), self.on_reload_clicked)
        self.urlbar = UrlBar(self)
        self.zoom_btn = QPushButton()
        self.zoom_btn.setObjectName("zoom")
        self.zoom_btn.setFlat(True)
        self.zoom_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom_btn.setToolTip(self.tip("Reset zoom", "zoom reset"))
        self.zoom_btn.clicked.connect(lambda: self.run_command("zoom reset"))
        self.private_label = QLabel("private")
        self.private_label.setObjectName("privatelabel")
        self.private_label.setVisible(self.private)
        self.star_btn = tool_button(self, "☆", self.tip("Bookmark this page", "bookmark"),
                                    lambda: self.run_command("bookmark"))
        self.menu_btn = tool_button(self, "≡", "Menu")
        self.menu_btn.setMenu(self.build_menu())
        self.menu_btn.setPopupMode(self.menu_btn.ToolButtonPopupMode.InstantPopup)
        for w in (self.mode_badge, self.back_btn, self.fwd_btn, self.reload_btn):
            tl.addWidget(w)
        tl.addWidget(self.urlbar, 1)
        for w in (self.zoom_btn, self.private_label, self.star_btn, self.menu_btn):
            tl.addWidget(w)

        self.progress = QProgressBar(central)
        self.progress.setObjectName("progress")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(2)
        self.progress.setRange(0, 100)
        self.progress_slot = QWidget(central)  # keeps layout steady when the bar hides
        self.progress_slot.setFixedHeight(2)
        self.progress_slot.setObjectName("progressslot")
        self.infobar = InfoBar(self)
        self.stack = QStackedWidget(central)
        self.findbar = FindBar(self)

        lay.addWidget(self.tabstrip)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_slot)
        lay.addWidget(self.infobar)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.findbar)
        self.setCentralWidget(central)

        self.completion = Completion(central, self)
        self.link_toast = Toast(central, "linktoast")
        self.msg_toast = Toast(central, "msgtoast")
        self.key_timer = QTimer(self, singleShot=True, interval=1000, timeout=self.flush_pending)

        self.apply_theme()
        self.update_chrome()

    # ------------------------------------------------------------------ util
    def keys_for(self, cmd: str) -> list[str]:
        keys = [k for k, c in self.cfg.bindings.items() if c == cmd]
        # Show vim-style plain keys first in vim mode, chords first otherwise.
        keys.sort(key=lambda k: k.startswith("<") == self.vim)  # stable: keeps config order
        return keys

    def tip(self, label: str, cmd: str) -> str:
        keys = self.keys_for(cmd)
        return f"{label} ({pretty_key(keys[0])})" if keys else label

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        for entry in MENU:
            if entry is None:
                menu.addSeparator()
                continue
            cmd, label = entry
            keys = self.keys_for(cmd)
            text = f"{label}\t{pretty_key(keys[0])}" if keys else label
            act = menu.addAction(text)
            act.triggered.connect(lambda _=False, c=cmd: self.run_command(c))
        return menu

    # ------------------------------------------------------------------ tabs
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
        close = tool_button(self.tabbar, "✕", self.tip("Close tab", "tab-close"))
        close.setObjectName("tabclose")
        close.clicked.connect(lambda: self.close_tab(self.stack.indexOf(view)))
        self.tabbar.setTabButton(idx, self.tabbar.ButtonPosition.RightSide, close)
        if not background or self.tabbar.count() == 1:
            self.tabbar.setCurrentIndex(idx)
        self.refresh_tab_titles()
        self.browser.schedule_session_save()
        return view

    def close_tab(self, idx: int | None = None) -> None:
        idx = self.tabbar.currentIndex() if idx is None else idx
        view = self.stack.widget(idx)
        if view is None:
            return
        url = view.current_url().toString()
        if url and not is_start_page(view.current_url()):
            self.closed_tabs.append(url)
        if self.tabbar.count() == 1:
            self.close()  # closing the last tab closes the window, like other browsers
            return
        self.tabbar.removeTab(idx)
        self.stack.removeWidget(view)
        view.page().deleteLater()
        view.deleteLater()
        self.refresh_tab_titles()
        self.browser.schedule_session_save()

    def on_tab_changed(self, idx: int) -> None:
        if idx < 0:
            return
        self.stack.setCurrentIndex(idx)
        view = self.view()
        if view is not None and view.lazy_url is not None:
            view.load(view.lazy_url)
            view.lazy_url = None
        if self.mode in (Mode.INSERT, Mode.HINT):
            self.set_mode(self.base_mode)
        self.link_toast.hide()
        if view is not None and is_start_page(view.current_url()):
            self.urlbar.setFocus()
        elif not self.urlbar.hasFocus() and not self.findbar.edit.hasFocus():
            self.focus_view()
        self.update_chrome()

    def on_tab_moved(self, frm: int, to: int) -> None:
        w = self.stack.widget(frm)
        self.stack.removeWidget(w)
        self.stack.insertWidget(to, w)
        self.stack.setCurrentIndex(self.tabbar.currentIndex())
        self.browser.schedule_session_save()

    def refresh_tab_titles(self) -> None:
        for i, v in enumerate(self.views()):
            if v.lazy_url is not None:
                title = self.storage.title_for(v.lazy_url.toString()) or pretty_url(v.lazy_url)
            elif is_start_page(v.url()):
                title = "New Tab"
            else:
                title = v.title() or pretty_url(v.url()) or "New Tab"
            self.tabbar.setTabText(i, title)
            self.tabbar.setTabToolTip(i, f"{title}\n{v.current_url().toString()}")
        show = self.cfg.show_tabs
        visible = show == "always" or (show == "multiple" and self.tabbar.count() > 1)
        self.tabstrip.setVisible(visible and not self.isFullScreen())

    def focus_view(self) -> None:
        v = self.view()
        if v is not None:
            (v.focusProxy() or v).setFocus()

    # ------------------------------------------------------- web view signals
    def on_load_started(self, view: WebView) -> None:
        view.progress = 0
        if view is self.view():
            self.update_chrome()

    def on_progress(self, view: WebView, p: int) -> None:
        view.progress = p
        if view is self.view():
            self.update_chrome()

    def on_load_finished(self, view: WebView, ok: bool) -> None:
        view.progress = 100
        if ok and not self.private:
            self.storage.add_visit(view.url().toString(), view.title())
        if view is self.view():
            self.update_chrome()

    def on_url_changed(self, view: WebView, url: QUrl) -> None:
        if view is self.view():
            self.update_chrome()
        self.refresh_tab_titles()
        self.browser.schedule_session_save()

    def on_title_changed(self, view: WebView, title: str) -> None:
        if not self.private:
            self.storage.set_title(view.url().toString(), title)
        self.refresh_tab_titles()
        if view is self.view():
            self.update_window_title()

    def on_icon_changed(self, view: WebView, icon) -> None:
        idx = self.stack.indexOf(view)
        if idx >= 0:
            self.tabbar.setTabIcon(idx, icon)

    def on_link_hovered(self, view: WebView, url: str) -> None:
        if view is self.view():
            self.link_toast.show_text(url)
            self.layout_overlays()

    def on_fullscreen_request(self, req) -> None:
        req.accept()
        self.set_fullscreen(req.toggleOn())

    def set_fullscreen(self, on: bool) -> None:
        for w in (self.toolbar, self.progress_slot):
            w.setVisible(not on)
        if on:
            self.tabstrip.hide()
            self.progress.hide()
            self.showFullScreen()
        else:
            self.showNormal()
            self.refresh_tab_titles()
            self.update_chrome()

    def on_permission_request(self, permission) -> None:
        origin = permission.origin().host() or permission.origin().toString()
        kind = re.sub(r"(?<!^)([A-Z])", r" \1", permission.permissionType().name).lower()
        self.infobar.ask(f"{origin} wants to use your {kind}.",
                         lambda ok: permission.grant() if ok else permission.deny())

    def page_mode_request(self, view: WebView, mode: str) -> None:
        if not self.vim or view is not self.view():
            return
        if mode == "insert" and self.mode == Mode.NORMAL:
            self.set_mode(Mode.INSERT)
        elif mode == "normal" and self.mode == Mode.INSERT:
            self.set_mode(Mode.NORMAL, blur=False)

    # ---------------------------------------------------------------- chrome
    def update_window_title(self) -> None:
        v = self.view()
        t = v.title() if v and not is_start_page(v.url()) else ""
        suffix = "Kestrel (private)" if self.private else "Kestrel"
        self.setWindowTitle(f"{t} — {suffix}" if t else suffix)

    def update_chrome(self) -> None:
        p = self.browser.palette
        if self.vim:
            text = f" {self.mode.value} {self.count}{self.pending}".rstrip() + " "
            self.mode_badge.setText(text)
            self.mode_badge.setProperty("mode", self.mode.value.lower())
            self.mode_badge.style().unpolish(self.mode_badge)
            self.mode_badge.style().polish(self.mode_badge)
        v = self.view()
        if v is None:
            return
        url = v.current_url()
        if not self.urlbar.hasFocus():
            self.urlbar.setText("" if is_start_page(url) else pretty_url(url))
            self.urlbar.setCursorPosition(0)
        hist = v.history()
        self.back_btn.setEnabled(hist.canGoBack())
        self.fwd_btn.setEnabled(hist.canGoForward())
        loading = v.progress < 100
        self.reload_btn.setText("✕" if loading else "↻")
        self.reload_btn.setToolTip(self.tip("Stop", "stop") if loading else self.tip("Reload", "reload"))
        fullscreen = self.isFullScreen()
        self.progress.setVisible(loading and not fullscreen)
        self.progress_slot.setVisible(not loading and not fullscreen)
        self.progress.setValue(max(v.progress, 5))
        starred = self.storage.is_bookmarked(url.toString())
        self.star_btn.setText("★" if starred else "☆")
        self.star_btn.setStyleSheet(f"color: {p.yellow};" if starred else "")
        zoom = v.zoomFactor()
        self.zoom_btn.setVisible(abs(zoom - 1.0) > 0.01)
        self.zoom_btn.setText(f"{round(zoom * 100)}%")
        self.update_window_title()

    def show_message(self, text: str, level: str = "info", timeout: int = 3000) -> None:
        p = self.browser.palette
        color = {"info": p.fg, "warn": p.yellow, "error": p.red, "ok": p.green}.get(level, p.fg)
        self.msg_toast.setStyleSheet(f"color: {color};")
        self.msg_toast.show_text(text, timeout)
        self.layout_overlays()

    def apply_theme(self) -> None:
        p = self.browser.palette
        f, fs = self.cfg.font, self.cfg.font_size
        self.setStyleSheet(f"""
        QMainWindow, QWidget {{ background: {p.bg}; color: {p.fg}; }}
        * {{ font-family: '{f}', 'JetBrains Mono', monospace; font-size: {fs}pt; }}
        #tabstrip {{ background: {p.bg_alt}; }}
        QTabBar {{ background: transparent; }}
        QTabBar::tab {{ background: transparent; color: {p.muted}; padding: 6px 10px 6px 12px;
            margin-right: 2px; border: none; border-top-left-radius: 8px; border-top-right-radius: 8px;
            min-width: 60px; max-width: 220px; }}
        QTabBar::tab:selected {{ background: {p.bg}; color: {p.fg}; }}
        QTabBar::tab:hover:!selected {{ background: {p.selection}; color: {p.fg}; }}
        #tabclose {{ background: transparent; color: {p.muted}; border: none; border-radius: 4px;
            min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; font-size: {fs - 1}pt; }}
        #tabclose:hover {{ background: {p.line}; color: {p.fg}; }}
        QTabBar QToolButton {{ background: {p.bg_alt}; border: none; color: {p.fg}; }}
        #toolbar {{ background: {p.bg}; border-bottom: 1px solid {p.line}; }}
        #tool {{ background: transparent; color: {p.fg}; border: none; border-radius: 6px;
            min-width: 28px; min-height: 26px; font-size: {fs + 3}pt; }}
        #tool:hover {{ background: {p.selection}; }}
        #tool:disabled {{ color: {p.line}; }}
        #tool::menu-indicator {{ image: none; width: 0; }}
        #urlbar {{ background: {p.bg_alt}; color: {p.fg}; border: 1px solid {p.line}; border-radius: 15px;
            padding: 4px 14px; min-height: 20px; selection-background-color: {p.selection}; }}
        #urlbar:focus {{ border: 1px solid {p.accent}; }}
        #zoom {{ color: {p.muted}; border: 1px solid {p.line}; border-radius: 10px; padding: 1px 8px; }}
        #privatelabel {{ color: {p.bg}; background: {p.magenta}; border-radius: 9px; padding: 1px 8px; }}
        #mode {{ color: {p.bg}; background: {p.accent}; font-weight: bold; border-radius: 6px; padding: 3px 6px; }}
        #mode[mode="insert"] {{ background: {p.green}; }}
        #mode[mode="hint"] {{ background: {p.yellow}; }}
        #mode[mode="passthrough"] {{ background: {p.red}; }}
        #progress {{ background: transparent; border: none; }}
        #progress::chunk {{ background: {p.accent}; }}
        #completion {{ background: {p.bg_alt}; border: 1px solid {p.line}; border-radius: 10px;
            outline: none; padding: 4px; }}
        #completion::item {{ padding: 4px 10px; border: none; border-radius: 6px; }}
        #completion::item:selected {{ background: {p.selection}; color: {p.fg}; }}
        #completion::item:hover {{ background: {p.selection}; }}
        #findbar {{ background: {p.bg_alt}; border-top: 1px solid {p.line}; }}
        #findedit {{ background: {p.bg}; border: 1px solid {p.line}; border-radius: 6px; padding: 3px 8px; }}
        #findedit:focus {{ border: 1px solid {p.accent}; }}
        #findlabel, #findcount {{ color: {p.muted}; background: transparent; }}
        #infobar {{ background: {p.selection}; }}
        #infobar QLabel {{ background: transparent; }}
        #infobar QPushButton {{ background: {p.bg}; border: 1px solid {p.line}; border-radius: 6px;
            padding: 3px 14px; }}
        #infobar QPushButton:hover {{ border-color: {p.accent}; }}
        #linktoast, #msgtoast {{ background: {p.bg_alt}; color: {p.fg}; border: 1px solid {p.line};
            border-radius: 6px; padding: 3px 8px; }}
        QMenu {{ background: {p.bg_alt}; border: 1px solid {p.line}; border-radius: 8px; padding: 6px; }}
        QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 5px; }}
        QMenu::item:selected {{ background: {p.selection}; }}
        QMenu::separator {{ height: 1px; background: {p.line}; margin: 4px 8px; }}
        QToolTip {{ background: {p.bg_alt}; color: {p.fg}; border: 1px solid {p.line}; }}
        """)
        self.update_chrome()

    def layout_overlays(self) -> None:
        sg = self.stack.geometry()
        c = self.completion
        if c.isVisible():
            top_left = self.urlbar.mapTo(self.centralWidget(), QPoint(0, self.urlbar.height() + 4))
            width = max(self.urlbar.width(), 520)
            c.setGeometry(top_left.x(), top_left.y(), width, c.preferred_height())
            c.setColumnWidth(0, int(width * 0.55))
            c.raise_()
        if self.link_toast.isVisible():
            self.link_toast.move(sg.left() + 6, sg.bottom() - self.link_toast.height() - 6)
            self.link_toast.raise_()
        if self.msg_toast.isVisible():
            self.msg_toast.move(sg.right() - self.msg_toast.width() - 10, sg.bottom() - self.msg_toast.height() - 10)
            self.msg_toast.raise_()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.layout_overlays()

    def changeEvent(self, ev) -> None:
        super().changeEvent(ev)
        if ev.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.browser.last_active = self
            v = self.view()
            if not self._activated and v is not None and is_start_page(v.current_url()):
                QTimer.singleShot(0, self.urlbar.setFocus)  # new window: start typing an address
            self._activated = True

    # ---------------------------------------------------------- address bar
    def on_reload_clicked(self) -> None:
        v = self.view()
        if v is not None:
            self.run_command("stop" if v.progress < 100 else "reload")

    def activate_url(self, text: str | None = None) -> None:
        """Focus the address bar. None selects the current URL; a string replaces it."""
        self.urlbar.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if text is None:
            self.update_chrome()
            self.urlbar.selectAll()
            return
        v = self.view()
        if v is not None:
            text = text.replace("{url}", v.current_url().toString())
        self.urlbar.setText(text)
        self.urlbar.end(False)
        self.on_url_edited(text)

    def leave_url(self) -> None:
        self.completion.set_rows([])
        self.focus_view()
        self.update_chrome()

    def on_url_edited(self, text: str) -> None:
        self.completion.set_rows(self.complete(text))

    def on_url_enter(self, text: str, new_tab: bool = False) -> None:
        action = self.completion.current_action()
        if action is None:
            action = ("text", text)
        self.completion.set_rows([])
        self.run_action(action, new_tab)

    def run_action(self, action, new_tab: bool = False) -> None:
        kind, value = action
        self.completion.set_rows([])
        if kind == "cmd":
            self.focus_view()
            self.run_command(value)
            return
        t = value.strip()
        if kind == "text" and t[:1] in (">", "%", "*", "^"):
            rows = self.complete(t)
            if rows:
                self.run_action(rows[0][2], new_tab)
            elif t.startswith(">") and t[1:].strip():
                self.focus_view()
                self.run_command(t[1:].strip())
            return
        if not t:
            self.leave_url()
            return
        url = QUrl(t) if kind == "url" else text_to_url(t, self.cfg)
        v = self.view()
        if new_tab or v is None:
            self.new_tab(url)
        else:
            v.load(url)
        self.focus_view()
        self.update_chrome()

    def complete(self, text: str) -> list[tuple[str, str, tuple[str, str]]]:
        t = text.strip()
        if not t:
            return []
        prefix, q = t[0], t[1:].strip()
        if prefix == ">":
            words = q.lower().split()
            rows = []
            for cmd, desc, _section, in_palette in COMMANDS:
                if not in_palette and not (self.vim and cmd.startswith(("mode", "scroll"))):
                    continue
                hay = f"{desc} {cmd}".lower()
                if all(w in hay for w in words):
                    keys = self.keys_for(cmd)
                    rows.append((desc, pretty_key(keys[0]) if keys else "", ("cmd", cmd)))
            return rows
        if prefix == "%":
            return self.tab_rows(q)
        if prefix == "*":
            return [("★ " + (title or url), url, ("url", url)) for url, title in self.storage.search_bookmarks(q, 50)]
        if prefix == "^":
            return [(title or url, url, ("url", url)) for url, title in self.storage.search_history(q, 50)]

        if is_search(t, self.cfg):
            words = t.split()
            if len(words) > 1 and words[0] in self.cfg.search_engines:
                first = f"Search {words[0]}: {' '.join(words[1:])}"
            else:
                first = f"Search {engine_name(self.cfg)} for “{t}”"
        else:
            first = f"Go to {text_to_url(t, self.cfg).toDisplayString()}"
        rows = [(first, "", ("text", t))]
        seen: set[str] = set()
        for left, url, action in self.tab_rows(t)[:3]:
            if not is_start_page(QUrl(url)):
                rows.append(("⇥ " + left.split(": ", 1)[-1], "switch to tab", action))
                seen.add(url)
        for url, title in self.storage.search_bookmarks(t, 5):
            if url not in seen:
                seen.add(url)
                rows.append(("★ " + (title or url), url, ("url", url)))
        for url, title in self.storage.search_history(t, 10):
            if url not in seen and len(rows) < 12:
                seen.add(url)
                rows.append((title or url, url, ("url", url)))
        return rows

    def tab_rows(self, q: str) -> list[tuple[str, str, tuple[str, str]]]:
        words = q.lower().split()
        rows = []
        for i, v in enumerate(self.views()):
            url = v.current_url().toString()
            title = v.title() or self.storage.title_for(url) or "New Tab"
            if all(w in f"{title} {url}".lower() for w in words):
                rows.append((f"{i + 1}: {title}", url, ("cmd", f"buffer {i + 1}")))
        return rows

    # ----------------------------------------------------------------- find
    def find_text(self, text: str, backward: bool = False, incremental: bool = False) -> None:
        v = self.view()
        if v is None:
            return
        self.search_text = text
        flags = QWebEnginePage.FindFlag.FindBackward if backward else QWebEnginePage.FindFlag(0)
        if incremental:
            v.findText("")
        v.findText(text, flags, self.on_find_result)

    def on_find_result(self, result) -> None:
        n = result.numberOfMatches()
        p = self.browser.palette
        if not self.search_text:
            self.findbar.count.clear()
        elif n == 0:
            self.findbar.count.setText(f'<span style="color:{p.red}">No matches</span>')
        else:
            self.findbar.count.setText(f"{result.activeMatch()} of {n}")
        if not self.findbar.isVisible() and self.search_text:
            self.show_message(f"{self.search_text}: {result.activeMatch()}/{n}" if n else "No matches", "info")

    # ----------------------------------------------------------------- modes
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
        self.update_chrome()

    # ------------------------------------------------------------------ keys
    def handle_key(self, ev: QKeyEvent) -> bool:
        """Return True if the key was consumed."""
        tok = key_token(ev)
        if tok is None:
            return False
        if self.mode == Mode.HINT:
            self.hint_key(tok)
            return True
        focus = QGuiApplication.focusObject()
        in_edit = isinstance(focus, QLineEdit)
        if in_edit or not self.vim:
            # Text fields and the standard keymap: only chords and F-keys are shortcuts.
            if self.vim and in_edit:
                return False
            if not tok.startswith(("<C-", "<A-", "<M-", "<F", "<S-F")):
                return False
            cmd = self.cfg.bindings.get(tok)
            if cmd is None:
                return False
            self.run_command(cmd)
            return True
        return self.handle_vim_key(tok)

    def handle_vim_key(self, tok: str) -> bool:
        if self.mode == Mode.INSERT:
            if tok in ("<Esc>", "<C-[>"):
                self.set_mode(Mode.NORMAL)
                return True
            if tok.startswith(("<C-", "<A-", "<F")) and tok in self.cfg.bindings and tok not in (
                "<C-d>", "<C-u>", "<C-f>", "<C-b>", "<C-v>"
            ):
                self.run_command(self.cfg.bindings[tok])
                return True
            return False
        if self.mode == Mode.PASSTHROUGH:
            if tok == "<S-Esc>":
                self.set_mode(Mode.NORMAL)
                return True
            return False
        # NORMAL
        if not self.pending and tok.isdigit() and (tok != "0" or self.count):
            if not any(k.startswith(tok) for k in self.cfg.bindings):
                self.count += tok
                self.update_chrome()
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
            self.update_chrome()
            return True
        had_pending = bool(self.pending or self.count)
        self.pending = ""
        self.count = ""
        self.update_chrome()
        if had_pending:
            return True
        return tok != "<Enter>" and not tok.startswith(("<C-", "<A-"))

    def flush_pending(self) -> None:
        cmd = self.cfg.bindings.get(self.pending)
        if cmd:
            self.run_binding(cmd)
        else:
            self.pending = ""
            self.count = ""
            self.update_chrome()

    def run_binding(self, cmd: str) -> None:
        count = int(self.count) if self.count else None
        self.pending = ""
        self.count = ""
        self.key_timer.stop()
        self.run_command(cmd, count)
        self.update_chrome()

    # ----------------------------------------------------------------- hints
    def start_hints(self, action: str = "click") -> None:
        v = self.view()
        if not v:
            return
        p = self.browser.palette
        opts = {"chars": self.cfg.hint_chars, "action": action, "bg": p.yellow, "fg": p.bg,
                "border": p.bg, "dim": p.muted}

        def done(count):
            if not count:
                self.show_message("No links to follow on this page", "warn")
                self.set_mode(self.base_mode)

        self.set_mode(Mode.HINT)
        self.hint_action = action
        self.show_message("Type a link's letters · Esc cancels", "info", 2500)
        v.js(f"__kestrel.showHints({json.dumps(opts)})", done)

    def hint_key(self, tok: str) -> None:
        v = self.view()
        if tok in ("<Esc>", "<C-[>") or not v:
            self.set_mode(self.base_mode)
            return
        if tok == "<BS>":
            key = "<BS>"
        elif len(tok) == 1:
            key = tok
        else:
            return

        def result(res):
            res = res or {}
            if res.get("status") == "pending":
                return
            self.mode = self.base_mode
            self.msg_toast.hide()
            if res.get("href"):
                self.new_tab(QUrl(res["href"]), background=True)
                self.show_message("Opened in background tab")
            elif "yank" in res:
                QGuiApplication.clipboard().setText(res["yank"])
                self.show_message(f"Copied {res['yank'][:80]}", "ok")
            if res.get("editable") and self.vim:
                self.set_mode(Mode.INSERT)
            else:
                self.set_mode(self.base_mode)

        v.js(f"__kestrel.hintKey({json.dumps(key)})", result)

    # -------------------------------------------------------------- commands
    def run_command(self, line: str, count: int | None = None) -> None:
        cmd, _, arg = line.strip().partition(" ")
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
                    v.js("(function(){var e=document.scrollingElement;"
                         f"e.scrollTo(0,(e.scrollHeight-innerHeight)*{min(count, 100)}/100)}})()")
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
                self.findbar.hide()
                v.js("__kestrel.clearHints()")
                self.msg_toast.hide()
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
            elif cmd == "focus-url":
                self.activate_url(arg if arg else None)
            elif cmd == "palette":
                self.activate_url("> ")
            elif cmd == "tab-search":
                self.activate_url("% " + arg)
            elif cmd == "bookmarks":
                self.activate_url("* ")
            elif cmd == "history":
                self.activate_url("^ ")
            elif cmd in ("open", "o", "tabopen", "t"):
                new = cmd in ("tabopen", "t")
                if arg.startswith("-t"):
                    new, arg = True, arg[2:]
                if not arg.strip():
                    self.run_command("tab-new") if new else self.activate_url("")
                    return
                self.run_action(("text", arg), new_tab=new)
            elif cmd == "tab-new":
                text = arg.replace("{url}", v.current_url().toString()) if v is not None else arg
                self.new_tab(QUrl(self.cfg.homepage))
                self.activate_url(text)
            elif cmd == "window-new":
                self.browser.new_window([QUrl(self.cfg.homepage)])
            elif cmd == "window-close":
                self.close()
            elif cmd == "paste":
                text = QGuiApplication.clipboard().text().strip()
                if not text:
                    self.show_message("Clipboard is empty", "warn")
                    return
                self.run_action(("text", text), new_tab="-t" in argv)
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
                for _ in range(n):
                    self.close_tab()
            elif cmd == "tab-undo":
                if self.closed_tabs:
                    self.new_tab(QUrl(self.closed_tabs.pop()))
                else:
                    self.show_message("No recently closed tabs", "warn")
            elif cmd == "tab-only":
                cur = self.tabbar.currentIndex()
                for i in reversed(range(self.tabbar.count())):
                    if i != cur:
                        self.close_tab(i)
            elif cmd == "tab-clone":
                self.new_tab(v.url())
            elif cmd == "tab-move":
                cur = self.tabbar.currentIndex()
                to = max(0, min(self.tabbar.count() - 1, cur + int(argv[0]) * n))
                self.tabbar.moveTab(cur, to)
            elif cmd in ("buffer", "b"):
                if not argv:
                    self.run_command("tab-search")
                elif argv[0].isdigit():
                    self.tabbar.setCurrentIndex(min(int(argv[0]), self.tabbar.count()) - 1)
                else:
                    rows = self.tab_rows(arg)
                    if rows:
                        self.run_action(rows[0][2])
            elif cmd == "hint":
                self.start_hints("tab" if "-t" in argv else "yank" if "-y" in argv else "click")
            elif cmd == "focus-input":
                def focused(ok):
                    if not ok:
                        self.show_message("No text field on this page", "warn")
                    elif self.vim:
                        self.set_mode(Mode.INSERT)
                self.focus_view()
                v.js("__kestrel.focusInput()", focused)
            elif cmd == "yank":
                what = argv[0] if argv else "url"
                text = v.title() if what == "title" else v.url().toString()
                QGuiApplication.clipboard().setText(text)
                self.show_message(f"Copied {what}: {text[:80]}", "ok")
            elif cmd == "find":
                self.findbar.open(arg)
            elif cmd in ("find-next", "find-prev", "search-next", "search-prev"):
                text = self.findbar.edit.text() or self.search_text
                if not text:
                    self.findbar.open()
                    return
                for _ in range(n):
                    self.find_text(text, backward=cmd.endswith("prev"))
            elif cmd == "mode":
                mode = {"insert": Mode.INSERT, "passthrough": Mode.PASSTHROUGH}.get(argv[0], self.base_mode)
                if self.vim:
                    self.set_mode(mode)
                    if mode == Mode.PASSTHROUGH:
                        self.show_message("All keys go to the page — Shift+Esc to leave", "warn")
            elif cmd == "zoom":
                z = v.zoomFactor()
                if argv[0] == "in":
                    for _ in range(n):
                        z = next((lv for lv in ZOOM_LEVELS if lv > z + 0.01), z)
                elif argv[0] == "out":
                    for _ in range(n):
                        z = next((lv for lv in reversed(ZOOM_LEVELS) if lv < z - 0.01), z)
                elif argv[0] == "reset":
                    z = count / 100 if count else self.cfg.default_zoom
                else:
                    z = float(argv[0].rstrip("%")) / 100
                v.setZoomFactor(z)
                self.show_message(f"Zoom {round(z * 100)}%", timeout=1200)
            elif cmd == "fullscreen":
                self.set_fullscreen(not self.isFullScreen())
            elif cmd == "bookmark":
                added = self.storage.toggle_bookmark(v.url().toString(), v.title())
                self.show_message("Bookmarked ★" if added else "Bookmark removed", "ok")
            elif cmd == "help":
                self.new_tab(QUrl("kestrel://help"))
            elif cmd == "devtools":
                self.open_devtools()
            elif cmd == "downloads":
                self.cfg.downloads_dir.mkdir(parents=True, exist_ok=True)
                self.xdg_open(str(self.cfg.downloads_dir))
            elif cmd == "config":
                self.browser.ensure_config()
                self.xdg_open(str(CONFIG_FILE))
                self.show_message(f"Editing {CONFIG_FILE} — restart Kestrel to apply", "info", 5000)
            elif cmd == "private":
                self.browser.spawn_private(arg)
            elif cmd == "theme-reload":
                self.browser.check_theme(force=True)
            elif cmd in ("quit", "qa", "wq", "x"):
                self.browser.quit(save="--no-save" not in argv)
            else:
                self.show_message(f"Unknown command: {cmd}", "error")
        except (IndexError, ValueError, KeyError) as exc:
            self.show_message(f"{line.strip()}: bad argument ({exc})", "error")
        except AttributeError:
            pass  # no current view
        self.update_chrome()

    def xdg_open(self, target: str) -> None:
        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", target], start_new_session=True)
        else:
            self.show_message(target)

    def open_devtools(self) -> None:
        v = self.view()
        dev = QWebEngineView(self)
        dev.setWindowFlag(Qt.WindowType.Window)
        dev.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dev.setWindowTitle(f"DevTools — {v.title()}")
        v.page().setDevToolsPage(dev.page())
        dev.resize(1000, 700)
        dev.show()

    # -------------------------------------------------------------- session
    def session_state(self) -> dict:
        urls = [v.current_url().toString() or v.page().requestedUrl().toString() for v in self.views()]
        return {"tabs": [u for u in urls if u], "current": self.tabbar.currentIndex()}

    def closeEvent(self, ev) -> None:
        self.browser.window_closing(self)
        for v in self.views():
            v.page().deleteLater()
        super().closeEvent(ev)
