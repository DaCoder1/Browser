"""Application controller: windows, profile, session, theme, single instance."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from PyQt6.QtCore import QEvent, QObject, QTimer, QUrl
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebEngineCore import (
    QWebEngineDownloadRequest,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlScheme,
)
from PyQt6.QtWidgets import QApplication, QWidget

from kestrel import APP_NAME, __version__
from kestrel.config import CACHE_DIR, CONFIG_FILE, DATA_DIR, Config
from kestrel.keys import Mode
from kestrel.storage import Storage
from kestrel.theme import load_palette, theme_signature
from kestrel.urls import is_start_page, text_to_url
from kestrel.web import JS_LIB, JS_WORLD, SCHEME, SchemeHandler
from kestrel.window import MainWindow

CONFIG_TEMPLATE = """\
# Kestrel settings. Restart Kestrel after editing.
# Full example: https://github.com/DaCoder1/Browser/blob/main/config.example.toml

[general]
keymap = "standard"        # "standard" (normal browser) or "vim" (modal keys)
search_engine = "ddg"
restore_session = true

[bindings]
# "<C-e>" = "tab-search"
"""


class Browser(QObject):
    def __init__(self, app: QApplication, cfg: Config, private: bool):
        super().__init__(app)
        self.app = app
        self.cfg = cfg
        self.private = private
        self.storage = Storage(DATA_DIR)
        self.palette = load_palette()
        self._theme_sig = theme_signature()
        self.windows: list[MainWindow] = []
        self.last_active: MainWindow | None = None
        self.quitting = False
        self.profile = make_profile(app, cfg, private)
        self.profile.installUrlSchemeHandler(SCHEME, SchemeHandler(self))
        self.profile.downloadRequested.connect(self.on_download)
        self.session_timer = QTimer(self, singleShot=True, interval=1500, timeout=self.save_session)
        self.theme_timer = QTimer(self, interval=2000, timeout=self.check_theme)
        self.theme_timer.start()

    # -- windows ------------------------------------------------------------
    def new_window(self, urls: list[QUrl] | None = None, lazy: bool = False, current: int = 0) -> MainWindow:
        w = MainWindow(self)
        self.windows.append(w)
        for u in urls or [QUrl(self.cfg.homepage)]:
            w.new_tab(u, background=True, at_end=True, lazy=lazy)
        w.tabbar.setCurrentIndex(max(0, min(current, w.tabbar.count() - 1)))
        w.on_tab_changed(w.tabbar.currentIndex())  # load the visible tab
        w.resize(1280, 800)
        w.show()
        v = w.view()
        if v is not None and is_start_page(v.current_url()):
            w.urlbar.setFocus()
        else:
            w.focus_view()
        self.last_active = w
        return w

    def active_window(self) -> MainWindow | None:
        if self.last_active in self.windows:
            return self.last_active
        return self.windows[-1] if self.windows else None

    def window_closing(self, w: MainWindow) -> None:
        if self.quitting or w not in self.windows:
            return
        if len(self.windows) == 1:
            self.save_session()  # last window: its tabs come back next time
            self.windows.remove(w)
            return
        self.windows.remove(w)  # closing one of several windows forgets it
        self.save_session()

    def quit(self, save: bool = True) -> None:
        if save:
            self.save_session()
        self.quitting = True
        for w in list(self.windows):
            w.close()
        self.app.quit()

    # -- session ------------------------------------------------------------
    def schedule_session_save(self) -> None:
        if not self.private and not self.quitting:
            self.session_timer.start()

    def save_session(self) -> None:
        if self.private:
            return
        self.storage.save_session([w.session_state() for w in self.windows if w.views()])

    def restore(self) -> bool:
        for win in self.storage.load_session():
            if win["tabs"]:
                self.new_window([QUrl(u) for u in win["tabs"]], lazy=True, current=win["current"])
        return bool(self.windows)

    # -- theme --------------------------------------------------------------
    def check_theme(self, force: bool = False) -> None:
        sig = theme_signature()
        if sig == self._theme_sig and not force:
            return
        self._theme_sig = sig
        self.palette = load_palette()
        for w in self.windows:
            w.apply_theme()
            for v in w.views():
                if v.url().scheme() == "kestrel":
                    v.reload()
            w.show_message(f"Theme: {self.palette.name}", "ok")

    # -- misc ---------------------------------------------------------------
    def ensure_config(self) -> None:
        if not CONFIG_FILE.exists():
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(CONFIG_TEMPLATE)

    def spawn_private(self, url: str = "") -> None:
        args = [sys.executable, "-m", "kestrel", "--private"]
        if url:
            args.append(url)
        subprocess.Popen(args, start_new_session=True)

    def on_download(self, req: QWebEngineDownloadRequest) -> None:
        self.cfg.downloads_dir.mkdir(parents=True, exist_ok=True)
        req.setDownloadDirectory(str(self.cfg.downloads_dir))
        req.accept()
        name = req.downloadFileName()
        if w := self.active_window():
            w.show_message(f"Downloading {name}…")

        def finished():
            if not req.isFinished():
                return
            ok = req.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            path = os.path.join(req.downloadDirectory(), req.downloadFileName())
            if win := self.active_window():
                win.show_message(f"Saved {path}" if ok else f"Download failed: {name}",
                                 "ok" if ok else "error", 6000)
            if shutil.which("notify-send"):
                subprocess.Popen(["notify-send", "-a", "Kestrel",
                                  "Download complete" if ok else "Download failed", path])

        req.isFinishedChanged.connect(finished)

    def handle_remote(self, data: str) -> None:
        """URLs from another `kestrel` invocation; none means 'new window'."""
        urls = [u for u in data.split("\n") if u.strip()]
        w = self.active_window()
        if not urls or w is None:
            self.new_window([text_to_url(u, self.cfg) for u in urls] or None)
            return
        for u in urls:
            w.new_tab(text_to_url(u, self.cfg))
        w.raise_()
        w.activateWindow()


class KeyFilter(QObject):
    """Sees every key before the page does and hands it to its window."""

    def __init__(self, browser: Browser):
        super().__init__(browser)
        self._last = None
        self._last_result = False

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t not in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride) or not isinstance(obj, QWidget):
            return False
        win = obj.window()
        if not isinstance(win, MainWindow):
            return False
        if t == QEvent.Type.ShortcutOverride:
            if win.vim and win.mode == Mode.NORMAL:
                ev.accept()  # stop Chromium treating our keys as editing shortcuts
            return False
        # Qt re-delivers unhandled key events to parent widgets; handle once.
        sig = (ev.timestamp(), ev.key(), int(ev.modifiers().value), ev.text())
        if sig == self._last:
            return self._last_result
        self._last = sig
        self._last_result = win.handle_key(ev)
        return self._last_result


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
    s.setAttribute(A.FocusOnNavigationEnabled, False)  # loading a page must not steal the address bar

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


def connect_existing(urls: list[str]) -> bool:
    """Hand URLs to an already running Kestrel. True if one was running."""
    sock = QLocalSocket()
    sock.connectToServer(f"kestrel-{os.getuid()}")
    if not sock.waitForConnected(300):
        return False
    sock.write(("\n".join(urls) + "\n").encode())
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def listen(browser: Browser) -> QLocalServer:
    name = f"kestrel-{os.getuid()}"
    QLocalServer.removeServer(name)
    server = QLocalServer(browser)
    server.listen(name)

    def on_connection():
        conn = server.nextPendingConnection()
        buf = bytearray()
        conn.readyRead.connect(lambda: buf.extend(bytes(conn.readAll())))
        conn.disconnected.connect(lambda: browser.handle_remote(buf.decode(errors="replace")))

    server.newConnection.connect(on_connection)
    return server


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"kestrel {__version__}")
        return 0
    if "-h" in argv or "--help" in argv:
        print("usage: kestrel [--private] [URL ...]\nKeyboard-friendly browser for Omarchy. Press F1 inside for shortcuts.")
        return 0
    private = any(a in argv for a in ("--private", "--private-window", "--incognito"))
    urls = [a for a in argv[1:] if not a.startswith("-")]

    cfg = Config.load()
    palette = load_palette()
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "preferredColorScheme" not in flags:
        # 0 = dark, 1 = light: sites with prefers-color-scheme follow the Omarchy theme.
        flags += f" --blink-settings=preferredColorScheme={1 if palette.is_light else 0}"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags.strip()

    register_scheme()
    QGuiApplication.setDesktopFileName(APP_NAME)  # Wayland app_id, for Hyprland window rules
    app = QApplication(argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("Kestrel")
    app.setFont(QFont(cfg.font, cfg.font_size))

    if not private and connect_existing(urls):
        return 0

    browser = Browser(app, cfg, private)
    if not private:
        listen(browser)
    app.installEventFilter(KeyFilter(browser))

    restored = cfg.restore_session and not private and not urls and browser.restore()
    if urls:
        browser.new_window([text_to_url(u, cfg) for u in urls])
    elif not restored:
        browser.new_window()
    return app.exec()
