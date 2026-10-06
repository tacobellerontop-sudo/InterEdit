"""Find bar: Ctrl+F search with next/prev, match highlighting, Escape to close."""

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout,
    QWidget,
)


class FindBar(QFrame):
    """Framed search strip docked under the tab area."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None
        self._matches = []
        self._index = -1
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._refresh)

        self.setObjectName("findBar")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 5, 8, 5)
        outer.setSpacing(6)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)

        self.field = QLineEdit()
        self.field.setPlaceholderText("Search…")
        self.field.setClearButtonEnabled(True)
        self.field.textChanged.connect(lambda _: self._debounce.start())
        self.field.returnPressed.connect(self.find_next)
        self.field.installEventFilter(self)

        self.replace_field = QLineEdit()
        self.replace_field.setPlaceholderText("Replace…")
        self.replace_field.returnPressed.connect(self.replace_one)
        self.replace_field.installEventFilter(self)

        left.addWidget(self.field)
        left.addWidget(self.replace_field)

        self.count_label = QLabel("")
        self.count_label.setObjectName("dimLabel")

        def btn(text, tip, cb):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(cb)
            return b

        self.prev_btn = btn("↑", "Previous match (Shift+F3)",
                            self.find_prev)
        self.next_btn = btn("↓", "Next match (F3)", self.find_next)
        self.replace_btn = btn("Replace", "Replace current match",
                               self.replace_one)
        self.replace_all_btn = btn("All", "Replace all matches",
                                   self.replace_all)
        close_btn = btn("✕", "Close (Escape)", self.close_bar)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(4)
        row1 = QWidget()
        row1_lay = QHBoxLayout(row1)
        row1_lay.setContentsMargins(0, 0, 0, 0)
        row1_lay.setSpacing(6)
        row1_lay.addWidget(self.count_label)
        row1_lay.addWidget(self.prev_btn)
        row1_lay.addWidget(self.next_btn)
        row2 = QWidget()
        row2_lay = QHBoxLayout(row2)
        row2_lay.setContentsMargins(0, 0, 0, 0)
        row2_lay.setSpacing(6)
        row2_lay.addWidget(self.replace_btn)
        row2_lay.addWidget(self.replace_all_btn)
        side.addWidget(row1)
        side.addWidget(row2)
        self._replace_row = row2

        outer.addLayout(left, 1)
        outer.addLayout(side)
        outer.addWidget(close_btn)
        self._replace_widgets = (self.replace_field, self._replace_row)
        self.hide()

    # ------------------------------------------------------------------ API

    def open_for(self, editor, replace=False):
        self.editor = editor
        for w in self._replace_widgets:
            w.setVisible(replace)
        self.show()
        (self.replace_field if replace else self.field).setFocus()
        self.field.selectAll()
        if self.field.text():
            self._refresh()

    def eventFilter(self, obj, event):
        if obj in (self.field, self.replace_field) and \
                event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.close_bar()
                return True
            if event.key() == Qt.Key_F3:
                if event.modifiers() & Qt.ShiftModifier:
                    self.find_prev()
                else:
                    self.find_next()
                return True
        return super().eventFilter(obj, event)

    def close_bar(self):
        self.hide()
        if self.editor:
            self.editor.set_search_results([])
            self.editor.setFocus()
        self.closed.emit()

    # --------------------------------------------------------------- search

    def _refresh(self):
        if self.editor is None or not self.isVisible():
            return
        text = self.field.text()
        self._matches = []
        if text:
            doc = self.editor.document()
            probe = QTextCursor(doc)
            while len(self._matches) < 5000:
                probe = doc.find(text, probe)
                if probe.isNull():
                    break
                self._matches.append(QTextCursor(probe))
        if not self._matches:
            self._index = -1
        elif self._index == -1 or self._index >= len(self._matches):
            # Place at first match at/after the cursor.
            pos = self.editor.textCursor().position()
            self._index = next(
                (i for i, m in enumerate(self._matches)
                 if m.selectionEnd() >= pos), 0)
        self._apply()
        self._update_count()

    def _update_count(self):
        if not self.field.text():
            self.count_label.setText("")
        elif not self._matches:
            self.count_label.setText("No results")
        else:
            self.count_label.setText(
                f"{self._index + 1} / {len(self._matches)}")

    def _apply(self):
        if self.editor:
            self.editor.set_search_results(self._matches, self._index)

    def _go_to(self, index):
        if not self._matches:
            return
        self._index = index % len(self._matches)
        match = self._matches[self._index]
        self.editor.setTextCursor(match)
        self.editor.caret.snap_to_cursor()
        self._apply()
        self._update_count()

    def find_next(self):
        if self._matches:
            self._go_to(self._index + 1)

    def find_prev(self):
        if self._matches:
            self._go_to(self._index - 1)

    # -------------------------------------------------------------- replace

    def replace_one(self):
        """Replace the active match, then step to the next one."""
        if not self._matches or self._index < 0 or self.editor is None:
            return
        match = QTextCursor(self._matches[self._index])
        match.beginEditBlock()
        match.removeSelectedText()
        match.insertText(self.replace_field.text())
        match.endEditBlock()
        self.editor.setTextCursor(match)
        self.editor.caret.snap_to_cursor()
        self._refresh()
        self.find_next()

    def replace_all(self):
        """Replace every match in the document in a single undo step."""
        text = self.field.text()
        if not text or self.editor is None:
            return
        repl = self.replace_field.text()
        probe = QTextCursor(self.editor.document())
        edit = QTextCursor(self.editor.document())
        edit.beginEditBlock()
        count = 0
        pos = self.editor.textCursor().position()
        while count < 10000:
            probe = self.editor.document().find(text, probe)
            if probe.isNull():
                break
            probe.insertText(repl)  # replaces the selection in place
            pos = probe.position()
            count += 1
        edit.endEditBlock()
        cursor = self.editor.textCursor()
        cursor.setPosition(min(pos, self.editor.document().characterCount()
                               - 1))
        self.editor.setTextCursor(cursor)
        self._refresh()
        self.count_label.setText(
            f"{count} replaced" if count != 1 else "1 replaced")
