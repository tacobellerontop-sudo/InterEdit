"""Line-number gutter with current-line highlight."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class LineNumberArea(QWidget):
    """Painted by the editor (which owns fonts/colors); forwards mouse clicks."""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event):
        self._editor.gutter_paint_event(event, self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._editor.select_line_at(event.position().toPoint().y())
        super().mousePressEvent(event)


def gutter_mode(editor):
    """Line-number mode for `editor`: off | absolute | relative | hybrid."""
    try:
        mode = editor.settings.get("line_numbers")
    except Exception:
        return "absolute"
    return mode if mode in ("off", "absolute", "relative", "hybrid") \
        else "absolute"


def gutter_label(mode, block_number, current_block):
    """Text for one gutter row (0-based block numbers)."""
    if mode == "relative":
        return "0" if block_number == current_block \
            else str(abs(block_number - current_block))
    if mode == "hybrid" and block_number != current_block:
        return str(abs(block_number - current_block))
    return str(block_number + 1)


def make_gutter_helpers(editor):
    """Return width/paint closures bound to `editor` and its theme colors.

    Kept outside the editor class so editor.py stays focused on editing.
    """
    state = {"digits": 1, "colors": None}

    def set_colors(colors):
        state["colors"] = colors

    def width():
        if gutter_mode(editor) == "off":
            return 0
        digits = max(1, len(str(max(editor.blockCount(), 1))))
        state["digits"] = digits
        fm = editor.fontMetrics()
        return digits * fm.horizontalAdvance("9") + 18

    def paint(event, area: LineNumberArea):
        painter = QPainter(area)
        colors = state["colors"]
        painter.fillRect(event.rect(), QColor(colors["gutter_bg"]))

        mode = gutter_mode(editor)
        if mode == "off":
            painter.end()
            return
        current_block = editor.textCursor().blockNumber()
        block = editor.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(editor.blockBoundingGeometry(block)
                    .translated(editor.contentOffset()).top())
        bottom = top + round(editor.blockBoundingRect(block).height())
        fm_height = editor.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                color = (QColor(colors["gutter_text_active"])
                         if block_number == current_block
                         else QColor(colors["gutter_text"]))
                painter.setPen(color)
                painter.drawText(0, top, area.width() - 10, fm_height,
                                 Qt.AlignRight,
                                 gutter_label(mode, block_number,
                                              current_block))
            block = block.next()
            top = bottom
            bottom = top + round(editor.blockBoundingRect(block).height())
            block_number += 1
        painter.end()

    return set_colors, width, paint
