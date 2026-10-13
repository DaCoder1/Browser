"""User configuration: ~/.config/kestrel/config.toml (all keys optional)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "kestrel"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "kestrel"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "kestrel"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_SEARCH_ENGINES = {
    "ddg": "https://duckduckgo.com/?q={}",
    "g": "https://www.google.com/search?q={}",
    "yt": "https://www.youtube.com/results?search_query={}",
    "gh": "https://github.com/search?q={}",
    "aw": "https://wiki.archlinux.org/index.php?search={}",
    "aur": "https://aur.archlinux.org/packages?K={}",
    "w": "https://en.wikipedia.org/wiki/Special:Search?search={}",
}

# key sequence -> command. Commands are the same ones you can type after ':'.
DEFAULT_BINDINGS: dict[str, str] = {
    # scrolling
    "j": "scroll down",
    "k": "scroll up",
    "h": "scroll left",
    "l": "scroll right",
    "<Down>": "scroll down",
    "<Up>": "scroll up",
    "d": "scroll-page 0.5",
    "u": "scroll-page -0.5",
    "<C-d>": "scroll-page 0.5",
    "<C-u>": "scroll-page -0.5",
    "<Space>": "scroll-page 0.9",
    "<S-Space>": "scroll-page -0.9",
    "<C-f>": "scroll-page 0.9",
    "<C-b>": "scroll-page -0.9",
    "<PgDown>": "scroll-page 0.9",
    "<PgUp>": "scroll-page -0.9",
    "gg": "scroll-to top",
    "G": "scroll-to bottom",
    # navigation
    "H": "back",
    "L": "forward",
    "r": "reload",
    "R": "reload -f",
    "<Esc>": "clear",
    "gu": "navigate up",
    "gU": "navigate root",
    "gs": "view-source",
    # opening
    "o": "set-cmd open ",
    "O": "set-cmd open -t ",
    "go": "set-cmd open {url}",
    "gO": "set-cmd open -t {url}",
    "t": "set-cmd open -t ",
    "p": "paste",
    "P": "paste -t",
    "gh": "home",
    # tabs
    "J": "tab-next",
    "K": "tab-prev",
    "gt": "tab-next",
    "gT": "tab-prev",
    "<C-Tab>": "tab-next",
    "<C-S-Tab>": "tab-prev",
    "g0": "tab-focus 1",
    "g$": "tab-focus -1",
    "x": "tab-close",
    "X": "tab-undo",
    "<A-,>": "tab-move -1",
    "<A-.>": "tab-move +1",
    "yd": "tab-clone",
    "b": "set-cmd buffer ",
    **{f"<A-{n}>": f"tab-focus {n}" for n in range(1, 10)},
    # hints
    "f": "hint",
    "F": "hint -t",
    "yf": "hint -y",
    "gi": "focus-input",
    # clipboard
    "yy": "yank url",
    "yt": "yank title",
    # find
    "/": "set-cmd /",
    "n": "search-next",
    "N": "search-prev",
    # modes
    "i": "mode insert",
    "<C-v>": "mode passthrough",
    ":": "set-cmd ",
    # zoom
    "zi": "zoom in",
    "zo": "zoom out",
    "zz": "zoom reset",
    "+": "zoom in",
    "-": "zoom out",
    "=": "zoom reset",
    # misc
    "B": "bookmark",
    "?": "help",
    "<F1>": "help",
    "<F12>": "devtools",
    "ZZ": "quit",
    "ZQ": "quit --no-save",
}


@dataclass
class Config:
    homepage: str = "kestrel://start"
    search_engine: str = "ddg"
    search_engines: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SEARCH_ENGINES))
    downloads_dir: Path = field(default_factory=lambda: Path("~/Downloads").expanduser())
    restore_session: bool = True
    show_tabs: str = "multiple"  # always | multiple | never
    hint_chars: str = "asdfghjkl"
    scroll_step: int = 60
    default_zoom: float = 1.0
    force_dark: bool = False
    smooth_scrolling: bool = True
    font: str = "JetBrainsMono Nerd Font"
    font_size: int = 11
    bindings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BINDINGS))

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "Config":
        cfg = cls()
        if not path.is_file():
            return cfg
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"kestrel: ignoring broken config {path}: {exc}")
            return cfg
        general = data.get("general", data)
        for key in (
            "homepage", "search_engine", "restore_session", "show_tabs", "hint_chars",
            "scroll_step", "default_zoom", "force_dark", "smooth_scrolling", "font", "font_size",
        ):
            if key in general:
                setattr(cfg, key, type(getattr(cfg, key))(general[key]))
        if "downloads_dir" in general:
            cfg.downloads_dir = Path(general["downloads_dir"]).expanduser()
        cfg.search_engines.update(data.get("search_engines", {}))
        for key, cmd in data.get("bindings", {}).items():
            if cmd in ("", None, "nop"):
                cfg.bindings.pop(key, None)
            else:
                cfg.bindings[key] = cmd
        return cfg
