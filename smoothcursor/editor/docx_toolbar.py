"""Floating formatting toolbar for .docx tabs.

Appears above the active text selection, hides when the selection clears.
Every control is NoFocus so the editor keeps both focus and selection when
the toolbar is used.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QTextCursor
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget,
)

# Standard Word highlight palette.
HIGHLIGHTS = [
    ("Yellow", "#ffff00"),
    ("Bright green", "#00ff00"),
    ("Turquoise", "#00ffff"),
    ("Pink", "#ff00ff"),
    ("Blue", "#0000ff"),
    ("Red", "#ff0000"),
    ("Dark yellow", "#808000"),
    ("Gray", "#808080"),
]

TEXT_COLORS = [
    ("Automatic", None),
    ("Black", "#000000"),
    ("White", "#ffffff"),
    ("Red", "#e03131"),
    ("Orange", "#e8590c"),
    ("Yellow", "#f08c00"),
    ("Green", "#2f9e44"),
    ("Blue", "#1971c2"),
    ("Purple", "#9c36b5"),
]

FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72]


def _swatch_icon(color_hex, size=12):
    pix = QPixmap(size, size)
    pix.fill(QColor(color_hex if color_hex else "#555555"))
    return QIcon(pix)


class FormatToolbar(QFrame):
    def __init__(self, editor):
        super().__init__(editor.viewport())
        self._editor = editor
        self.setObjectName("formatToolbar")
        self.setFocusPolicy(Qt.NoFocus)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)

        def tool(text, tooltip, cb=None, bold=False, italic=False,
                 underline=False, checkable=True):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tooltip)
            b.setFocusPolicy(Qt.NoFocus)
            font = b.font()
            font.setBold(bold)
            font.setItalic(italic)
            font.setUnderline(underline)
            b.setFont(font)
            b.setCheckable(checkable)
            if cb:
                b.clicked.connect(cb)
            lay.addWidget(b)
            return b

        def separator():
            s = QWidget()
            s.setFixedWidth(1)
            s.setStyleSheet(
                "background: rgba(128,128,128,80); margin: 2px 1px;")
            lay.addWidget(s)
            return s

        # --- font family + size (compact, Word-like row) ----------------
        self.font_combo = QComboBox()
        self.font_combo.setFocusPolicy(Qt.NoFocus)
        self.font_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.font_combo.setMaximumWidth(150)
        self.font_combo.setToolTip("Font")
        families = [f for f in QFontDatabase.families()]
        preferred = [f for f in
                     ("Calibri", "Arial", "Times New Roman", "Georgia",
                      "Verdana", "Courier New", "Comic Sans MS")
                     if f in families]
        others = sorted(f for f in families
                        if f not in preferred and not f.startswith("."))
        self.font_combo.addItem("Arial")
        for f in preferred + others:
            if self.font_combo.findText(f) == -1:
                self.font_combo.addItem(f)
        self.font_combo.setMaxVisibleItems(18)
        self.font_combo.currentTextChanged.connect(self._font_family)
        lay.addWidget(self.font_combo)

        self.size_combo = QComboBox()
        self.size_combo.setFocusPolicy(Qt.NoFocus)
        self.size_combo.setEditable(False)
        self.size_combo.setToolTip("Font size")
        for s in FONT_SIZES:
            self.size_combo.addItem(str(s))
        self.size_combo.setCurrentText("11")
        self.size_combo.currentTextChanged.connect(self._font_size)
        lay.addWidget(self.size_combo)

        self.size_up = tool("▲", "Increase font size", self._size_up,
                            checkable=False)
        self.size_down = tool("▼", "Decrease font size", self._size_down,
                              checkable=False)

        separator()

        self.bold_btn = tool("B", "Bold", self._toggle_bold, bold=True)
        self.italic_btn = tool("I", "Italic", self._toggle_italic, italic=True)
        self.underline_btn = tool("U", "Underline", self._toggle_underline,
                                  underline=True)

        separator()

        self.highlight_btn = QToolButton()
        self.highlight_btn.setText("ab")
        self.highlight_btn.setToolTip("Text highlight color")
        self.highlight_btn.setFocusPolicy(Qt.NoFocus)
        self.highlight_btn.setStyleSheet(
            "QToolButton { border-bottom: 3px solid #ffff00; }")
        hmenu = QMenu(self.highlight_btn)
        clear_h = hmenu.addAction("No highlight")
        clear_h.triggered.connect(
            lambda: self._editor.apply_char_format(highlight=None))
        for name, hex_color in HIGHLIGHTS:
            act = hmenu.addAction(_swatch_icon(hex_color), name)
            act.triggered.connect(
                lambda _=False, h=hex_color:
                    self._editor.apply_char_format(highlight=h))
        self.highlight_btn.setMenu(hmenu)
        self.highlight_btn.setPopupMode(QToolButton.InstantPopup)
        lay.addWidget(self.highlight_btn)

        self.color_btn = QToolButton()
        self.color_btn.setText("A")
        self.color_btn.setToolTip("Font color")
        self.color_btn.setFocusPolicy(Qt.NoFocus)
        self.color_btn.setStyleSheet(
            "QToolButton { border-bottom: 3px solid #e03131; }")
        cmenu = QMenu(self.color_btn)
        for name, hex_color in TEXT_COLORS:
            act = cmenu.addAction(_swatch_icon(hex_color), name)
            act.triggered.connect(
                lambda _=False, h=hex_color:
                    self._editor.apply_char_format(color=h))
        self.color_btn.setMenu(cmenu)
        self.color_btn.setPopupMode(QToolButton.InstantPopup)
        lay.addWidget(self.color_btn)

        self.clear_btn = tool("⨯", "Clear formatting",
                              lambda: self._editor.apply_char_format(
                                  clear=True),
                              checkable=False)
        self.hide()

    # ------------------------------------------------------------- toggles

    def _apply_guarded(self):
        """True while refresh() syncs controls — don't re-apply format."""
        return getattr(self, "_updating", False)

    def _sel_format(self):
        return self._editor._selection_format()

    def _toggle_bold(self):
        self._editor.apply_char_format(
            bold=not (self._sel_format().fontWeight() > QFont.Normal))

    def _toggle_italic(self):
        self._editor.apply_char_format(
            italic=not self._sel_format().fontItalic())

    def _toggle_underline(self):
        self._editor.apply_char_format(
            underline=not self._sel_format().fontUnderline())

    # ------------------------------------------------------- font controls

    def _font_family(self, family):
        if family and not self._apply_guarded():
            self._editor.apply_char_format(family=family)

    def _font_size(self, size_text):
        if self._apply_guarded():
            return
        try:
            size = float(size_text)
        except ValueError:
            return
        if size > 0:
            self._editor.apply_char_format(size=size)

    def _step_size(self, delta):
        current = self._sel_format().fontPointSize()
        if current <= 0:
            current = 11.0
        sizes = FONT_SIZES
        cur_idx = min(range(len(sizes)),
                      key=lambda i: abs(sizes[i] - current))
        new_idx = max(0, min(len(sizes) - 1, cur_idx + delta))
        self._editor.apply_char_format(size=float(sizes[new_idx]))

    def _size_up(self):
        self._step_size(1)

    def _size_down(self):
        self._step_size(-1)

    def refresh(self):
        """Sync control states with the current selection's format."""
        fmt = self._sel_format()
        self.bold_btn.setChecked(fmt.fontWeight() > QFont.Normal)
        self.italic_btn.setChecked(fmt.fontItalic())
        self.underline_btn.setChecked(fmt.fontUnderline())
        self.highlight_btn.setChecked(fmt.background().style() != Qt.NoBrush)
        self._updating = True
        try:
            family = fmt.fontFamilies()
            if family:
                self.font_combo.setCurrentText(str(family[0]))
            size = fmt.fontPointSize()
            if size > 0:
                self.size_combo.setCurrentText(str(int(size)))
        finally:
            self._updating = False

    # ------------------------------------------------------------ position

    def place_over_selection(self):
        """Center above the selection rect; flip below when near the top."""
        editor = self._editor
        cursor = editor.textCursor()
        doc = editor.document()
        start_c = QTextCursor(doc)
        start_c.setPosition(cursor.selectionStart())
        end_c = QTextCursor(doc)
        end_c.setPosition(cursor.selectionEnd())
        r1 = editor.cursorRect(start_c)
        r2 = editor.cursorRect(end_c)
        left = min(r1.left(), r2.left())
        right = max(r1.right(), r2.right())
        top = min(r1.top(), r2.top())
        bottom = max(r1.bottom(), r2.bottom())

        self.adjustSize()
        vw = editor.viewport().width()
        vh = editor.viewport().height()
        w, h = self.width(), self.height()
        x = int((left + right) / 2 - w / 2)
        x = max(2, min(x, vw - w - 2))
        y = int(top) - h - 6
        if y < 2:
            y = int(bottom) + 6
        y = max(2, min(y, vh - h - 2))
        self.move(x, y)
