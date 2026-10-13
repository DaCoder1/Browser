"""History, bookmarks and session persistence."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Storage:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = data_dir / "session.json"
        self.db = sqlite3.connect(data_dir / "kestrel.sqlite")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS history (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                visits INTEGER NOT NULL DEFAULT 1,
                last_visit REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bookmarks (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                added REAL NOT NULL
            );
            """
        )
        self.db.commit()

    # -- history ------------------------------------------------------------
    def add_visit(self, url: str, title: str = "") -> None:
        if not url or url.startswith(("kestrel:", "about:", "data:", "view-source:")):
            return
        self.db.execute(
            """INSERT INTO history (url, title, visits, last_visit) VALUES (?, ?, 1, ?)
               ON CONFLICT(url) DO UPDATE SET visits = visits + 1, last_visit = excluded.last_visit,
               title = CASE WHEN excluded.title != '' THEN excluded.title ELSE title END""",
            (url, title, time.time()),
        )
        self.db.commit()

    def set_title(self, url: str, title: str) -> None:
        if title:
            self.db.execute("UPDATE history SET title = ? WHERE url = ?", (title, url))
            self.db.commit()

    def title_for(self, url: str) -> str:
        row = self.db.execute("SELECT title FROM history WHERE url = ?", (url,)).fetchone()
        return row[0] if row else ""

    @staticmethod
    def _where(words: list[str]) -> tuple[str, list[str]]:
        if not words:
            return "1", []
        clause = " AND ".join("(url LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')" for _ in words)
        args = []
        for w in words:
            w = w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            args += [f"%{w}%", f"%{w}%"]
        return clause, args

    def search_history(self, text: str, limit: int = 30) -> list[tuple[str, str]]:
        where, args = self._where(text.split())
        rows = self.db.execute(
            f"SELECT url, title FROM history WHERE {where} "
            "ORDER BY (visits * 1.0) / (1 + (strftime('%s','now') - last_visit) / 86400.0) DESC LIMIT ?",
            (*args, limit),
        )
        return rows.fetchall()

    def top_sites(self, limit: int = 8) -> list[tuple[str, str]]:
        return self.search_history("", limit)

    # -- bookmarks ----------------------------------------------------------
    def is_bookmarked(self, url: str) -> bool:
        return self.db.execute("SELECT 1 FROM bookmarks WHERE url = ?", (url,)).fetchone() is not None

    def toggle_bookmark(self, url: str, title: str) -> bool:
        if self.is_bookmarked(url):
            self.db.execute("DELETE FROM bookmarks WHERE url = ?", (url,))
            self.db.commit()
            return False
        self.db.execute("INSERT INTO bookmarks (url, title, added) VALUES (?, ?, ?)", (url, title, time.time()))
        self.db.commit()
        return True

    def search_bookmarks(self, text: str, limit: int = 30) -> list[tuple[str, str]]:
        where, args = self._where(text.split())
        rows = self.db.execute(
            f"SELECT url, title FROM bookmarks WHERE {where} ORDER BY added DESC LIMIT ?", (*args, limit)
        )
        return rows.fetchall()

    # -- session ------------------------------------------------------------
    def save_session(self, urls: list[str], current: int) -> None:
        self.session_file.write_text(json.dumps({"tabs": urls, "current": current}, indent=1))

    def load_session(self) -> tuple[list[str], int]:
        try:
            data = json.loads(self.session_file.read_text())
            return [u for u in data.get("tabs", []) if isinstance(u, str)], int(data.get("current", 0))
        except (OSError, ValueError):
            return [], 0
