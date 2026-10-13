import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from kestrel.app import key_token, text_to_url
from kestrel.config import DEFAULT_BINDINGS, Config
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
        '[bindings]\n"<C-t>" = "set-cmd open -t "\nt = "nop"\n'
    )
    cfg = Config.load(f)
    assert cfg.search_engine == "g" and cfg.scroll_step == 100
    assert "mdn" in cfg.search_engines and "ddg" in cfg.search_engines
    assert cfg.bindings["<C-t>"] == "set-cmd open -t "
    assert "t" not in cfg.bindings
    assert "t" in DEFAULT_BINDINGS  # defaults untouched


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
    st.save_session(["https://a.com/", "https://b.com/"], 1)
    assert st.load_session() == (["https://a.com/", "https://b.com/"], 1)
