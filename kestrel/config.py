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

# Standard browser shortcuts. Typing goes to the page; only these chords are
# intercepted. Values are commands (see commands.py / the Ctrl+K palette).
STANDARD_BINDINGS: dict[str, str] = {
    # tabs & windows
    "<C-t>": "tab-new",
    "<C-w>": "tab-close",
    "<C-F4>": "tab-close",
    "<C-S-t>": "tab-undo",
    "<C-Tab>": "tab-next",
    "<C-PgDown>": "tab-next",
    "<C-S-Tab>": "tab-prev",
    "<C-PgUp>": "tab-prev",
    "<C-S-PgUp>": "tab-move -1",
    "<C-S-PgDown>": "tab-move +1",
    **{f"<C-{n}>": f"tab-focus {n}" for n in range(1, 9)},
    "<C-9>": "tab-focus -1",
    **{f"<A-{n}>": f"tab-focus {n}" for n in range(1, 10)},
    "<C-S-a>": "tab-search",
    "<C-n>": "window-new",
    "<C-S-n>": "private",
    "<C-S-w>": "window-close",
    "<C-q>": "quit",
    # navigation
    "<A-Left>": "back",
    "<A-Right>": "forward",
    "<C-[>": "back",
    "<C-]>": "forward",
    "<C-r>": "reload",
    "<F5>": "reload",
    "<C-S-r>": "reload -f",
    "<S-F5>": "reload -f",
    "<C-F5>": "reload -f",
    "<A-Home>": "home",
    # address bar
    "<C-l>": "focus-url",
    "<A-d>": "focus-url",
    "<F6>": "focus-url",
    "<C-k>": "palette",
    "<C-S-p>": "palette",
    "<C-S-o>": "bookmarks",
    "<C-h>": "history",
    # page
    "<C-f>": "find",
    "<F3>": "find-next",
    "<C-g>": "find-next",
    "<S-F3>": "find-prev",
    "<C-S-g>": "find-prev",
    "<C-d>": "bookmark",
    "<A-f>": "hint",
    "<A-S-f>": "hint -t",
    "<A-y>": "hint -y",
    "<A-i>": "focus-input",
    "<A-c>": "yank url",
    # view
    "<C-=>": "zoom in",
    "<C-+>": "zoom in",
    "<C-S-+>": "zoom in",
    "<C-->": "zoom out",
    "<C-0>": "zoom reset",
    "<F11>": "fullscreen",
    # tools
    "<C-u>": "view-source",
    "<F12>": "devtools",
    "<C-S-i>": "devtools",
    "<C-S-y>": "downloads",
    "<F1>": "help",
    "<C-/>": "help",
}

# Optional modal Vim keys (keymap = "vim"), layered on top of the standard ones.
VIM_BINDINGS: dict[str, str] = {
    "j": "scroll down",
    "k": "scroll up",
    "h": "scroll left",
    "l": "scroll right",
    "d": "scroll-page 0.5",
    "u": "scroll-page -0.5",
    "<C-d>": "scroll-page 0.5",
    "<C-u>": "scroll-page -0.5",
    "<Space>": "scroll-page 0.9",
    "<S-Space>": "scroll-page -0.9",
    "<C-f>": "scroll-page 0.9",
    "<C-b>": "scroll-page -0.9",
    "gg": "scroll-to top",
    "G": "scroll-to bottom",
    "H": "back",
    "L": "forward",
    "r": "reload",
    "R": "reload -f",
    "<Esc>": "clear",
    "gu": "navigate up",
    "gU": "navigate root",
    "gs": "view-source",
    "o": "open",
    "O": "tab-new",
    "t": "tab-new",
    "go": "focus-url {url}",
    "gO": "tab-new {url}",
    "p": "paste",
    "P": "paste -t",
    "gh": "home",
    "J": "tab-next",
    "K": "tab-prev",
    "gt": "tab-next",
    "gT": "tab-prev",
    "g0": "tab-focus 1",
    "g$": "tab-focus -1",
    "x": "tab-close",
    "X": "tab-undo",
    "yd": "tab-clone",
    "b": "tab-search",
    "f": "hint",
    "F": "hint -t",
    "yf": "hint -y",
    "gi": "focus-input",
    "yy": "yank url",
    "yt": "yank title",
    "/": "find",
    "n": "find-next",
    "N": "find-prev",
    "i": "mode insert",
    "<C-v>": "mode passthrough",
    ":": "palette",
    "zi": "zoom in",
    "zo": "zoom out",
    "zz": "zoom reset",
    "B": "bookmark",
    "?": "help",
    "ZZ": "quit",
    "ZQ": "quit --no-save",
}


def default_bindings(keymap: str) -> dict[str, str]:
    bindings = dict(STANDARD_BINDINGS)
    if keymap == "vim":
        bindings.update(VIM_BINDINGS)
    return bindings


@dataclass
class Config:
    keymap: str = "standard"  # standard | vim
    homepage: str = "kestrel://start"
    search_engine: str = "ddg"
    search_engines: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SEARCH_ENGINES))
    downloads_dir: Path = field(default_factory=lambda: Path("~/Downloads").expanduser())
    restore_session: bool = True
    show_tabs: str = "always"  # always | multiple | never
    hint_chars: str = "asdfghjkl"
    scroll_step: int = 60
    default_zoom: float = 1.0
    force_dark: bool = False
    smooth_scrolling: bool = True
    font: str = "JetBrainsMono Nerd Font"
    font_size: int = 11
    bindings: dict[str, str] = field(default_factory=lambda: default_bindings("standard"))

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
            "keymap", "homepage", "search_engine", "restore_session", "show_tabs", "hint_chars",
            "scroll_step", "default_zoom", "force_dark", "smooth_scrolling", "font", "font_size",
        ):
            if key in general:
                setattr(cfg, key, type(getattr(cfg, key))(general[key]))
        if "downloads_dir" in general:
            cfg.downloads_dir = Path(general["downloads_dir"]).expanduser()
        cfg.bindings = default_bindings(cfg.keymap)
        cfg.search_engines.update(data.get("search_engines", {}))
        for key, cmd in data.get("bindings", {}).items():
            if cmd in ("", None, "nop"):
                cfg.bindings.pop(key, None)
            else:
                cfg.bindings[key] = cmd
        return cfg
