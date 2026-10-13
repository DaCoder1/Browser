import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from kestrel.config import STANDARD_BINDINGS, VIM_BINDINGS, Config
from kestrel.keys import key_token, pretty_key
from kestrel.urls import is_search, text_to_url
from kestrel.storage import Storage
from kestrel.theme import load_palette


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def key(k, text="", mods=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QEvent.Type.KeyPress, k, mods, text)


def test_key_tokens():
    C = Qt.KeyboardModifier.ControlModifier
    S = Qt.KeyboardModifier.ShiftModifier
    A = Qt.KeyboardModifier.AltModifier
    assert key_token(key(Qt.Key.Key_J, "j")) == "j"
    assert key_token(key(Qt.Key.Key_G, "G", S)) == "G"
    assert key_token(key(Qt.Key.Key_D, "\x04", C)) == "<C-d>"
    assert key_token(key(Qt.Key.Key_Escape)) == "<Esc>"
    assert key_token(key(Qt.Key.Key_Escape, "", S)) == "<S-Esc>"
    assert key_token(key(Qt.Key.Key_1, "1", A)) == "<A-1>"
    assert key_token(key(Qt.Key.Key_Space, " ")) == "<Space>"
    assert key_token(key(Qt.Key.Key_Shift, "", S)) is None
    assert key_token(key(Qt.Key.Key_T, "\x14", C | S)) == "<C-S-t>"
    assert key_token(key(Qt.Key.Key_Backtab, "", C | S)) == "<C-S-Tab>"
    assert key_token(key(Qt.Key.Key_Left, "", A)) == "<A-Left>"
    assert key_token(key(Qt.Key.Key_F5, "")) == "<F5>"


def test_pretty_key():
    assert pretty_key("<C-S-t>") == "Ctrl+Shift+T"
    assert pretty_key("<C-->") == "Ctrl+-"
    assert pretty_key("<A-Left>") == "Alt+←"
    assert pretty_key("gg") == "gg"


def test_text_to_url():
    cfg = Config()
    assert text_to_url("archlinux.org", cfg).toString() == "https://archlinux.org"
    assert text_to_url("localhost:3000", cfg).toString() == "http://localhost:3000"
    assert text_to_url("192.168.1.1/admin", cfg).toString() == "http://192.168.1.1/admin"
    assert text_to_url("https://x.dev/a?b=1", cfg).toString() == "https://x.dev/a?b=1"
    assert text_to_url("kestrel://help", cfg).toString() == "kestrel://help"
    assert "duckduckgo.com/?q=hello+world" in text_to_url("hello world", cfg).toString()
    assert "youtube.com/results?search_query=lofi+beats" in text_to_url("yt lofi beats", cfg).toString()
    assert "duckduckgo" in text_to_url("python", cfg).toString()
    assert is_search("hello world", cfg) and is_search("python", cfg)
    assert not is_search("archlinux.org", cfg) and not is_search("https://x.dev", cfg)


def test_theme_from_alacritty(tmp_path):
    (tmp_path / "alacritty.toml").write_text(
        "[colors.primary]\nbackground = '0x282828'\nforeground = '#d4be98'\n"
        "[colors.normal]\nblue = '#7daea3'\nred = '#ea6962'\n"
    )
    p = load_palette(tmp_path)
    assert (p.bg, p.fg, p.accent, p.red) == ("#282828", "#d4be98", "#7daea3", "#ea6962")
    assert not p.is_light


def test_theme_colors_toml_wins(tmp_path):
    (tmp_path / "colors.toml").write_text('background = "#fafafa"\nforeground = "#111111"\naccent = "#ff0000"\n')
    (tmp_path / "alacritty.toml").write_text("[colors.primary]\nbackground = '#000000'\nforeground = '#ffffff'\n")
    p = load_palette(tmp_path)
    assert (p.bg, p.accent) == ("#fafafa", "#ff0000")
    assert p.is_light


def test_theme_fallback(tmp_path):
    assert load_palette(tmp_path / "missing").bg == "#1a1b26"


def test_config_overrides(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text(
        '[general]\nsearch_engine = "g"\nscroll_step = 100\n'
        '[search_engines]\nmdn = "https://developer.mozilla.org/search?q={}"\n'
        '[bindings]\n"<C-e>" = "tab-search"\n"<C-d>" = "nop"\n'
    )
    cfg = Config.load(f)
    assert cfg.search_engine == "g" and cfg.scroll_step == 100
    assert "mdn" in cfg.search_engines and "ddg" in cfg.search_engines
    assert cfg.bindings["<C-e>"] == "tab-search"
    assert "<C-d>" not in cfg.bindings
    assert STANDARD_BINDINGS["<C-d>"] == "bookmark"  # defaults untouched
    assert "j" not in cfg.bindings  # standard keymap: no single-key bindings


def test_vim_keymap(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[general]\nkeymap = "vim"\n')
    cfg = Config.load(f)
    assert cfg.bindings["j"] == "scroll down"
    assert cfg.bindings["<C-d>"] == VIM_BINDINGS["<C-d>"]  # vim wins over standard
    assert cfg.bindings["<C-t>"] == "tab-new"  # standard chords still there


def test_standard_bindings_are_chords():
    # Plain keys would steal typing from the page in the standard keymap.
    assert all(k.startswith("<") and k != "<Esc>" for k in STANDARD_BINDINGS)


def test_storage(tmp_path):
    st = Storage(tmp_path)
    st.add_visit("https://archlinux.org/", "Arch Linux")
    st.add_visit("https://archlinux.org/", "")
    st.add_visit("kestrel://start", "ignored")
    assert st.search_history("arch") == [("https://archlinux.org/", "Arch Linux")]
    assert st.search_history("100%") == []
    assert st.toggle_bookmark("https://omarchy.org/", "Omarchy") is True
    assert st.search_bookmarks("omar") == [("https://omarchy.org/", "Omarchy")]
    assert st.toggle_bookmark("https://omarchy.org/", "Omarchy") is False
    wins = [{"tabs": ["https://a.com/", "https://b.com/"], "current": 1}, {"tabs": ["https://c.com/"], "current": 0}]
    st.save_session(wins)
    assert st.load_session() == wins
    st.session_file.write_text('{"tabs": ["https://old.com/"], "current": 0}')  # pre-0.2 format
    assert st.load_session() == [{"tabs": ["https://old.com/"], "current": 0}]


def test_kbd_handles_plus():
    from kestrel.pages import kbd
    assert kbd("<C-+>") == "<kbd>Ctrl</kbd><kbd>+</kbd>"
    assert kbd("<C-S-+>") == "<kbd>Ctrl</kbd><kbd>Shift</kbd><kbd>+</kbd>"
    assert kbd("gg") == "<kbd>gg</kbd>"
