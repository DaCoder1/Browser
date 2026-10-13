"""Browser chrome widgets: address bar, suggestions, find bar, toasts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

if TYPE_CHECKING:
    from kestrel.window import MainWindow

# A suggestion's action: ("url", url) | ("cmd", command) | ("text", typed text)
Action = tuple[str, str]


def tool_button(parent: QWidget, glyph: str, tip: str, slot=None) -> QToolButton:
    b = QToolButton(parent)
    b.setText(glyph)
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setObjectName("tool")
    if slot:
        b.clicked.connect(slot)
    return b


def _delete_word(edit: QLineEdit) -> None:
    pos = edit.cursorPosition()
    text = edit.text()
    head = text[:pos].rstrip()
    start = head.rfind(" ") + 1 if " " in head else 0
    edit.setText(text[:start] + text[pos:])
    edit.setCursorPosition(start)


class TabBar(QTabBar):
    """Tab strip: middle-click closes, double-click on empty space opens a tab."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window_ = window
        self.setMovable(True)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setDrawBase(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionBehaviorOnRemove(QTabBar.SelectionBehavior.SelectPreviousTab)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.MiddleButton:
            idx = self.tabAt(ev.position().toPoint())
            if idx >= 0:
                self.window_.close_tab(idx)
                return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev: QMouseEvent) -> None:
        if self.tabAt(ev.position().toPoint()) < 0:
            self.window_.run_command("tab-new")
            return
        super().mouseDoubleClickEvent(ev)


class UrlBar(QLineEdit):
    """Address bar / omnibox. Prefixes: '>' commands, '%' tabs, '*' bookmarks, '^' history."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window_ = window
        self.setObjectName("urlbar")
        self.setPlaceholderText("Search or enter address")
        self.textEdited.connect(window.on_url_edited)

    def focusInEvent(self, ev) -> None:
        super().focusInEvent(ev)
        if ev.reason() == Qt.FocusReason.MouseFocusReason:
            QTimer.singleShot(0, self.selectAll)
        self.window_.update_chrome()

    def focusOutEvent(self, ev) -> None:
        super().focusOutEvent(ev)
        if ev.reason() != Qt.FocusReason.PopupFocusReason:
            self.window_.completion.set_rows([])
            self.window_.update_chrome()

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        w = self.window_
        key, mods = ev.key(), ev.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key == Qt.Key.Key_Escape:
            w.leave_url()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            w.on_url_enter(self.text(), new_tab=bool(mods & Qt.KeyboardModifier.AltModifier))
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Tab) or (ctrl and key in (Qt.Key.Key_N, Qt.Key.Key_J)):
            w.completion.step(1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Backtab) or (ctrl and key in (Qt.Key.Key_P, Qt.Key.Key_K)):
            w.completion.step(-1)
        elif ctrl and key == Qt.Key.Key_W:
            _delete_word(self)
            w.on_url_edited(self.text())
        else:
            super().keyPressEvent(ev)


class Completion(QTreeWidget):
    """Suggestion dropdown under the address bar."""

    MAX_ROWS = 10

    def __init__(self, parent: QWidget, window: "MainWindow"):
        super().__init__(parent)
        self.window_ = window
        self.setObjectName("completion")
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.header().setStretchLastSection(True)
        self.actions_: list[Action] = []
        self.itemClicked.connect(lambda item, _col: window.run_action(self.actions_[self.indexOfTopLevelItem(item)]))
        self.hide()

    def set_rows(self, rows: list[tuple[str, str, Action]]) -> None:
        self.clear()
        self.actions_ = []
        for left, right, action in rows[:100]:
            item = QTreeWidgetItem([left, right])
            if action[0] == "cmd" and right:
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.addTopLevelItem(item)
            self.actions_.append(action)
        self.setVisible(bool(rows))
        self.window_.layout_overlays()

    def current_action(self) -> Action | None:
        item = self.currentItem()
        if item is None or not self.isVisible():
            return None
        return self.actions_[self.indexOfTopLevelItem(item)]

    def step(self, delta: int) -> None:
        n = self.topLevelItemCount()
        if not n:
            return
        idx = self.indexOfTopLevelItem(self.currentItem()) if self.currentItem() else -1
        idx = (idx + delta) % n if idx >= 0 else (0 if delta > 0 else n - 1)
        self.setCurrentItem(self.topLevelItem(idx))
        self.scrollToItem(self.topLevelItem(idx))
        kind, value = self.actions_[idx]
        if kind in ("url", "text"):
            self.window_.urlbar.setText(value)

    def preferred_height(self) -> int:
        rows = min(self.topLevelItemCount(), self.MAX_ROWS)
        if not rows:
            return 0
        row_h = self.visualItemRect(self.topLevelItem(0)).height() or self.sizeHintForRow(0)
        return rows * max(row_h, 26) + 2 * self.frameWidth() + 12


class FindEdit(QLineEdit):
    def __init__(self, bar: "FindBar"):
        super().__init__(bar)
        self.bar = bar

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        key = ev.key()
        if key == Qt.Key.Key_Escape:
            self.bar.close_bar()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            back = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.bar.window_.find_text(self.text(), backward=back)
        else:
            super().keyPressEvent(ev)


class FindBar(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window_ = window
        self.setObjectName("findbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)
        label = QLabel("Find")
        label.setObjectName("findlabel")
        self.edit = FindEdit(self)
        self.edit.setObjectName("findedit")
        self.edit.setPlaceholderText("Find in page")
        self.edit.setMaximumWidth(360)
        self.edit.textEdited.connect(lambda t: window.find_text(t, incremental=True))
        self.count = QLabel()
        self.count.setObjectName("findcount")
        lay.addWidget(label)
        lay.addWidget(self.edit, 1)
        lay.addWidget(tool_button(self, "↑", "Previous match (Shift+Enter)",
                                  lambda: window.find_text(self.edit.text(), backward=True)))
        lay.addWidget(tool_button(self, "↓", "Next match (Enter)", lambda: window.find_text(self.edit.text())))
        lay.addWidget(self.count)
        lay.addStretch(1)
        lay.addWidget(tool_button(self, "✕", "Close (Esc)", self.close_bar))
        self.hide()

    def open(self, text: str = "") -> None:
        self.show()
        if text:
            self.edit.setText(text)
        self.edit.setFocus()
        self.edit.selectAll()
        if self.edit.text():
            self.window_.find_text(self.edit.text(), incremental=True)

    def close_bar(self) -> None:
        self.hide()
        self.count.clear()
        v = self.window_.view()
        if v is not None:
            v.findText("")
        self.window_.focus_view()


class InfoBar(QWidget):
    """Yellow-ish bar under the toolbar for permission requests."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.setObjectName("infobar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        self.label = QLabel()
        self.allow = QPushButton("&Allow")
        self.deny = QPushButton("&Deny")
        for b in (self.allow, self.deny):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.allow)
        lay.addWidget(self.deny)
        self.allow.clicked.connect(lambda: self.resolve(True))
        self.deny.clicked.connect(lambda: self.resolve(False))
        self.callback = None
        self.hide()

    def ask(self, text: str, callback) -> None:
        self.label.setText(text)
        self.callback = callback
        self.show()

    def resolve(self, ok: bool) -> None:
        cb, self.callback = self.callback, None
        self.hide()
        if cb:
            cb(ok)


class Toast(QLabel):
    """Small floating label over the page (hovered link, messages)."""

    def __init__(self, parent: QWidget, name: str):
        super().__init__(parent)
        self.setObjectName(name)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.timer = QTimer(self, singleShot=True, timeout=self.hide)
        self.hide()

    def show_text(self, text: str, timeout: int = 0, max_width: int = 700) -> None:
        if not text:
            self.hide()
            return
        metrics = self.fontMetrics()
        self.setText(metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max_width))
        self.adjustSize()
        self.show()
        self.raise_()
        if timeout:
            self.timer.start(timeout)
        else:
            self.timer.stop()
