"""Turn what the user typed into a URL."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote_plus

from PyQt6.QtCore import QUrl

from kestrel.config import Config

HOST_RE = re.compile(r"^(localhost|[\w-]+(\.[\w-]+)+|\d{1,3}(\.\d{1,3}){3}|\[[0-9a-f:]+\])(:\d+)?([/?#].*)?$", re.I)
LOCAL_RE = re.compile(r"^(localhost|127\.|\d{1,3}(\.\d{1,3}){3}|\[)")


def is_search(text: str, cfg: Config) -> bool:
    """True if text_to_url would run a search rather than open an address."""
    text = text.strip()
    words = text.split()
    if len(words) > 1:
        return True
    if re.match(r"^[a-z][a-z0-9+.-]*:", text, re.I) and not re.match(r"^[\w.-]+:\d+", text):
        return False
    if HOST_RE.match(text):
        return False
    return not (text.startswith(("/", "~")) and Path(text).expanduser().exists())


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
            return QUrl(("http://" if LOCAL_RE.match(text) else "https://") + text)
        if text.startswith(("/", "~")) and Path(text).expanduser().exists():
            return QUrl.fromLocalFile(str(Path(text).expanduser()))
    return QUrl(search_url(text, cfg))


def search_url(query: str, cfg: Config) -> str:
    engine = cfg.search_engines.get(cfg.search_engine, next(iter(cfg.search_engines.values())))
    return engine.replace("{}", quote_plus(query))


def engine_name(cfg: Config) -> str:
    url = cfg.search_engines.get(cfg.search_engine, "")
    host = QUrl(url).host().removeprefix("www.")
    return {"duckduckgo.com": "DuckDuckGo", "google.com": "Google"}.get(host, host or "the web")


def pretty_url(url: QUrl) -> str:
    s = url.toDisplayString()
    if url.scheme() == "kestrel":
        s = s.rstrip("/")
    return s


def is_start_page(url: QUrl) -> bool:
    return url.scheme() == "kestrel" and url.host() in ("start", "newtab", "")
