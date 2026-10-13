"""Read colors from the active Omarchy theme.

Omarchy keeps the active theme at ~/.config/omarchy/current/theme. We look
for colors.toml first, then fall back to the alacritty.toml every theme
ships, then to a built-in Tokyo Night palette.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

OMARCHY_THEME_DIR = Path(
    os.environ.get("KESTREL_THEME_DIR", "~/.config/omarchy/current/theme")
).expanduser()


@dataclass
class Palette:
    bg: str = "#1a1b26"
    bg_alt: str = "#16161e"
    fg: str = "#c0caf5"
    muted: str = "#565f89"
    accent: str = "#7aa2f7"
    red: str = "#f7768e"
    green: str = "#9ece6a"
    yellow: str = "#e0af68"
    magenta: str = "#bb9af7"
    cyan: str = "#7dcfff"
    selection: str = "#283457"
    line: str = "#292e42"
    name: str = "tokyo-night (built-in)"

    def as_dict(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @property
    def is_light(self) -> bool:
        return _luminance(self.bg) > 0.5


def _norm(value) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().strip("'\"")
    if v.startswith("0x"):
        v = "#" + v[2:]
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return v.lower()
    if re.fullmatch(r"[0-9a-fA-F]{6}", v):
        return "#" + v.lower()
    return None


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _mix(a: str, b: str, t: float) -> str:
    """Blend color a toward b by t (0..1)."""
    a, b = a.lstrip("#"), b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        x, y = int(a[i : i + 2], 16), int(b[i : i + 2], 16)
        out.append(round(x + (y - x) * t))
    return "#" + "".join(f"{c:02x}" for c in out)


def _from_colors_toml(data: dict) -> dict[str, str]:
    m = {
        "bg": data.get("background"),
        "fg": data.get("foreground"),
        "accent": data.get("accent") or data.get("color4"),
        "muted": data.get("color8"),
        "red": data.get("color1"),
        "green": data.get("color2"),
        "yellow": data.get("color3"),
        "magenta": data.get("color5"),
        "cyan": data.get("color6"),
    }
    return {k: c for k, v in m.items() if (c := _norm(v))}


def _from_alacritty(data: dict) -> dict[str, str]:
    colors = data.get("colors", {})
    primary = colors.get("primary", {})
    normal = colors.get("normal", {})
    bright = colors.get("bright", {})
    m = {
        "bg": primary.get("background"),
        "fg": primary.get("foreground"),
        "accent": normal.get("blue"),
        "muted": bright.get("black"),
        "red": normal.get("red"),
        "green": normal.get("green"),
        "yellow": normal.get("yellow"),
        "magenta": normal.get("magenta"),
        "cyan": normal.get("cyan"),
    }
    return {k: c for k, v in m.items() if (c := _norm(v))}


def load_palette(theme_dir: Path = OMARCHY_THEME_DIR) -> Palette:
    pal = Palette()
    found: dict[str, str] = {}
    for fname, parser in (("colors.toml", _from_colors_toml), ("alacritty.toml", _from_alacritty)):
        path = theme_dir / fname
        if not path.is_file():
            continue
        try:
            found = parser(tomllib.loads(path.read_text()))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if "bg" in found and "fg" in found:
            break
    if found:
        for k, v in found.items():
            setattr(pal, k, v)
        try:
            pal.name = theme_dir.resolve().name
        except OSError:
            pal.name = "omarchy"
    # Derived shades so every theme gets readable chrome.
    pal.bg_alt = _mix(pal.bg, "#000000" if not pal.is_light else "#ffffff", 0.25)
    if "muted" not in found:
        pal.muted = _mix(pal.fg, pal.bg, 0.5)
    # Theme "selection" colors are often loud; derive calm ones instead.
    pal.selection = _mix(pal.bg, pal.accent, 0.28)
    pal.line = _mix(pal.bg, pal.fg, 0.12)
    return pal


def theme_signature(theme_dir: Path = OMARCHY_THEME_DIR) -> str:
    """Something that changes when the user runs omarchy-theme-set."""
    try:
        resolved = theme_dir.resolve()
        stamps = [
            str(p.stat().st_mtime_ns)
            for p in (resolved / "colors.toml", resolved / "alacritty.toml")
            if p.exists()
        ]
        return f"{resolved}:{':'.join(stamps)}"
    except OSError:
        return ""
