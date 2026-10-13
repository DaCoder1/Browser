"""Qt WebEngine pieces: kestrel:// pages, the page and view classes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QBuffer, QByteArray, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineUrlRequestJob,
    QWebEngineUrlSchemeHandler,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from kestrel import pages

if TYPE_CHECKING:
    from kestrel.app import Browser
    from kestrel.window import MainWindow

JS_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld
JS_LIB = (Path(__file__).parent / "js" / "kestrel.js").read_text()
SCHEME = b"kestrel"


class SchemeHandler(QWebEngineUrlSchemeHandler):
    """Serves kestrel://start and kestrel://help."""

    def __init__(self, browser: "Browser"):
        super().__init__(browser)
        self.browser = browser

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        url = job.requestUrl()
        name = (url.host() or url.path().strip("/")).lower()
        b = self.browser
        if name in ("start", "newtab", ""):
            html = pages.start_page(b.palette, b.cfg, b.storage.top_sites(10), b.storage.search_bookmarks("", 10))
        elif name == "help":
            html = pages.help_page(b.palette, b.cfg)
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
        self.window_ = window

    def createWindow(self, kind):  # target=_blank, window.open(), middle/ctrl-click
        background = kind == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        return self.window_.new_tab(None, background=background).page()

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
        page.linkHovered.connect(lambda url: window.on_link_hovered(self, url))
        if hasattr(page, "permissionRequested"):
            page.permissionRequested.connect(window.on_permission_request)
        self.loadStarted.connect(lambda: window.on_load_started(self))
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
