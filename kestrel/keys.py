"""Key events -> tokens like 'j', '<C-t>', '<C-S-Tab>', and back to 'Ctrl+T'."""

from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence


class Mode(Enum):
    BROWSE = "BROWSE"  # standard keymap: keys go to the page unless they're shortcuts
    NORMAL = "NORMAL"  # vim keymap: keys are commands
    INSERT = "INSERT"
    HINT = "HINT"
    PASSTHROUGH = "PASSTHROUGH"


SPECIAL_KEYS = {
    Qt.Key.Key_Escape: "Esc", Qt.Key.Key_Tab: "Tab", Qt.Key.Key_Backtab: "Tab",
    Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Backspace: "BS",
    Qt.Key.Key_Delete: "Del", Qt.Key.Key_Space: "Space", Qt.Key.Key_Up: "Up",
    Qt.Key.Key_Down: "Down", Qt.Key.Key_Left: "Left", Qt.Key.Key_Right: "Right",
    Qt.Key.Key_PageUp: "PgUp", Qt.Key.Key_PageDown: "PgDown", Qt.Key.Key_Home: "Home",
    Qt.Key.Key_End: "End", Qt.Key.Key_Insert: "Ins",
    **{getattr(Qt.Key, f"Key_F{i}"): f"F{i}" for i in range(1, 13)},
}
MODIFIER_KEYS = {
    Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    Qt.Key.Key_Super_L, Qt.Key.Key_Super_R, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock,
}


def key_token(ev: QKeyEvent) -> str | None:
    try:
        key = Qt.Key(ev.key())
    except ValueError:
        return None
    if key in MODIFIER_KEYS:
        return None
    mods = ev.modifiers()
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    chord = ctrl or alt or meta
    if key in SPECIAL_KEYS:
        name = SPECIAL_KEYS[key]
        shift = shift or key == Qt.Key.Key_Backtab
    else:
        text = ev.text()
        if text and text.isprintable() and not chord:
            return text
        name = QKeySequence(key.value).toString().lower()
        if not name:
            return None
    prefix = "".join(p for p, on in (("C-", ctrl), ("A-", alt), ("M-", meta), ("S-", shift)) if on)
    return f"<{prefix}{name}>"


MOD_NAMES = {"C": "Ctrl", "A": "Alt", "S": "Shift", "M": "Super"}
KEY_NAMES = {"PgDown": "PgDn", "BS": "Backspace", "Left": "←", "Right": "→", "Up": "↑", "Down": "↓"}


def pretty_key(tok: str) -> str:
    """'<C-S-t>' -> 'Ctrl+Shift+T'; plain sequences like 'gg' are returned as-is."""
    if not (len(tok) > 2 and tok[0] == "<" and tok[-1] == ">"):
        return tok
    inner, mods = tok[1:-1], []
    while len(inner) > 2 and inner[1] == "-" and inner[0] in MOD_NAMES:
        mods.append(MOD_NAMES[inner[0]])
        inner = inner[2:]
    name = KEY_NAMES.get(inner, inner)
    if len(name) == 1:
        name = name.upper()
    return "+".join(mods + [name])
