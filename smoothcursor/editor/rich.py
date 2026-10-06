"""RichEditor: QTextEdit-based Word-style editor with real QTextTable tables.

CodeEditor (QPlainTextEdit) cannot render tables — QPlainTextDocumentLayout
explicitly does not support tables or nested frames. .docx tabs therefore
use this QTextEdit-based editor, whose standard QTextDocument layout renders
real editable tables natively.
"""

import re

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPalette, QTextCharFormat,
                           QTextCursor, QTextTableFormat)
from PySide6.QtWidgets import QTextEdit

from smoothcursor.editor.caret import SmoothCaret
from smoothcursor.editor.docx_toolbar import FormatToolbar
from smoothcursor.editor.line_numbers import (
    LineNumberArea, gutter_label, gutter_mode,
)
from smoothcursor.editor.spellcheck import (
    SpellHighlighter, append_spelling_section,
)

_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def _split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line):
    cells = _split_row(line)
    return bool(cells) and all(_SEPARATOR_CELL.match(c) for c in cells)


TABLE_HEADER_FILLS = [
    ("None", None),
    ("Yellow", "#ffff00"),
    ("Green", "#c6efce"),
    ("Blue", "#d6e4f0"),
    ("Gray", "#e7e6e6"),
    ("Orange", "#fce4d6"),
    ("Pink", "#ffd9e8"),
]

def default_table_format(border=1, padding=4, spacing=0):
    fmt = QTextTableFormat()
    fmt.setBorder(max(0, int(border)))
    fmt.setBorderStyle(QTextTableFormat.BorderStyle_Solid)
    fmt.setCellPadding(max(0, float(padding)))
    fmt.setCellSpacing(max(0, float(spacing)))
    return fmt


def _normalize_hex(color):
    if not color:
        return None
    c = QColor(color)
    if not c.isValid():
        return None
    return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())


class RichEditor(QTextEdit):
    """Word-style editor with real tables, smooth caret and format toolbar."""

    modified_changed = Signal(bool)

    def __init__(self, settings, colors, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._colors = dict(colors)
        self.language = None
        self.file_path = None
        self.untitled_name = ""
        self.rich_mode = True

        self.setCursorWidth(0)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setWordWrapMode(self._wrap_mode(True))
        self.setAcceptRichText(True)

        self.gutter = LineNumberArea(self)

        self.caret = SmoothCaret(self, QColor(colors["accent"]))
        self.caret.speed = float(settings.get("caret_speed"))
        self.caret.blink_ms = int(settings.get("caret_blink_ms"))

        self.cursorPositionChanged.connect(self.caret.on_activity)
        self.cursorPositionChanged.connect(lambda: self.gutter.update())
        self.document().modificationChanged.connect(self.modified_changed)
        self.document().blockCountChanged.connect(self._update_gutter_width)
        self.textChanged.connect(self._update_gutter_width)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self.gutter.update())
        self._redo_action = None
        try:
            from PySide6.QtGui import QAction
            self._redo_action = QAction("Redo", self)
            self._redo_action.setShortcut("Ctrl+Y")
            self._redo_action.triggered.connect(self.redo)
            self.addAction(self._redo_action)
        except Exception:
            pass

        self.format_toolbar = FormatToolbar(self)
        self.selectionChanged.connect(self._on_selection_changed)

        self.spell_highlighter = SpellHighlighter(self.document(),
                                                  self._colors)

        self.apply_settings()
        self.apply_colors()
        self.caret.resize_to_viewport()

    def update_spellcheck(self):
        """Toggle wavy underlines: prose tabs honoring the setting."""
        try:
            enabled = bool(self.settings.get("spellcheck"))
        except Exception:
            enabled = True
        self.spell_highlighter.set_active(enabled)

    # ------------------------------------------------------------ compat API
    # MainWindow treats CodeEditor and RichEditor interchangeably.

    @staticmethod
    def language_for(path):
        if not path:
            return None
        import os
        ext = os.path.splitext(path)[1].lower()
        return {".py": "python", ".pyw": "python", ".json": "json"}.get(ext)

    def set_rich_mode(self, enabled: bool):
        """Toolbar visibility toggle (export detaches it briefly)."""
        self.rich_mode = bool(enabled)
        if self.format_toolbar is None:
            return
        if enabled:
            pass  # stays hidden until there is a selection
        else:
            self.format_toolbar.hide()

    def _on_selection_changed(self):
        tb = self.format_toolbar
        if tb is None:
            return
        if not self.rich_mode:
            tb.hide()
            return
        if self.textCursor().hasSelection():
            tb.refresh()
            tb.place_over_selection()
            tb.show()
            tb.raise_()
        else:
            tb.hide()

    @staticmethod
    def _wrap_mode(enabled):
        from PySide6.QtGui import QTextOption
        return QTextOption.WrapAtWordBoundaryOrAnywhere if enabled \
            else QTextOption.NoWrap

    def apply_settings(self):
        s = self.settings
        font = QFont(s.resolved_font_family(), int(s.get("font_size")))
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self.setCurrentFont(font)
        try:
            fm = self.fontMetrics()
            self.setTabStopDistance(
                fm.horizontalAdvance(" ") * int(s.get("tab_size")))
        except Exception:
            pass
        self.caret.speed = float(s.get("caret_speed"))
        self.caret.blink_ms = int(s.get("caret_blink_ms"))
        self.caret._snap_now()
        self._update_gutter_width()
        self.update_spellcheck()

    def apply_colors(self, colors=None):
        if colors is not None:
            self._colors = dict(colors)
        c = self._colors
        palette = self.palette()
        palette.setColor(QPalette.Base, QColor(c["editor_bg"]))
        palette.setColor(QPalette.Text, QColor(c["editor_text"]))
        palette.setColor(QPalette.Highlight, QColor(c["selection"]))
        palette.setColor(QPalette.HighlightedText, QColor(c["editor_text"]))
        self.setPalette(palette)
        self.caret.apply_theme(QColor(c["accent"]))
        self.viewport().update()
        self.gutter.update()
        self.spell_highlighter.apply_colors(c)

    # --------------------------------------------------------------- gutter

    def gutter_width(self):
        if gutter_mode(self) == "off":
            return 0
        digits = max(1, len(str(max(self.document().blockCount(), 1))))
        return digits * self.fontMetrics().horizontalAdvance("9") + 18

    def _position_gutter(self):
        rect = self.contentsRect()
        self.gutter.setGeometry(
            QRect(rect.left(), rect.top(), self.gutter_width(),
                  rect.height()))

    def _update_gutter_width(self, *_):
        width = self.gutter_width()
        self.setViewportMargins(width, 0, 0, 0)
        self._position_gutter()
        self.gutter.setVisible(width > 0)
        self.gutter.update()

    def _first_visible_block(self):
        return self.cursorForPosition(QPoint(4, 2)).block()

    def _block_top(self, block, calibration):
        layout = self.document().documentLayout()
        return layout.blockBoundingRect(block).top() \
            - self.verticalScrollBar().value() + calibration

    def _calibrate(self, block):
        """Viewport offset so layout math matches real cursor pixels."""
        try:
            probe = QTextCursor(block)
            probe.setPosition(block.position())
            expected = self.cursorRect(probe).top()
            layout = self.document().documentLayout()
            raw = layout.blockBoundingRect(block).top() \
                - self.verticalScrollBar().value()
            return expected - raw
        except Exception:
            return 0.0

    def gutter_paint_event(self, event, area):
        from PySide6.QtGui import QPainter
        painter = QPainter(area)
        c = self._colors
        painter.fillRect(event.rect(), QColor(c["gutter_bg"]))
        mode = gutter_mode(self)
        if mode == "off":
            painter.end()
            return
        try:
            current = self.textCursor().blockNumber()
            block = self._first_visible_block()
            if not block.isValid():
                painter.end()
                return
            calibration = self._calibrate(block)
            layout = self.document().documentLayout()
            vh = self.viewport().height()
            fm_height = self.fontMetrics().height()
            top = self._block_top(block, calibration)
            while block.isValid() and top <= event.rect().bottom():
                height = layout.blockBoundingRect(block).height()
                bottom = top + height
                if block.isVisible() and bottom >= event.rect().top() \
                        and top <= vh:
                    color = (QColor(c["gutter_text_active"])
                             if block.blockNumber() == current
                             else QColor(c["gutter_text"]))
                    painter.setPen(color)
                    painter.drawText(0, round(top), area.width() - 10,
                                     fm_height, Qt.AlignRight,
                                     gutter_label(mode, block.blockNumber(),
                                                  current))
                top = bottom
                block = block.next()
        finally:
            painter.end()

    def select_line_at(self, y):
        """Click in the gutter selects that whole line."""
        try:
            global_pt = self.gutter.mapToGlobal(QPoint(2, int(y)))
            vp_pt = self.viewport().mapFromGlobal(global_pt)
            block = self.cursorForPosition(vp_pt).block()
        except Exception:
            return
        if block.isValid():
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.LineUnderCursor)
            self.setTextCursor(cursor)
            self.setFocus()

    def zoom_font(self, steps):
        win = self.window()
        if win is not None and hasattr(win, "zoom_font"):
            win.zoom_font(steps)
            return
        try:
            size = max(8, min(40,
                              int(self.settings.get("font_size")) + steps))
            self.settings.set("font_size", size)
            self.apply_settings()
        except Exception:
            pass

    # ------------------------------------------------------------ rich text

    def _selection_format(self) -> QTextCharFormat:
        cursor = self.textCursor()
        pos = cursor.selectionStart()
        block = self.document().findBlock(pos)
        it = block.begin()
        fmt = self.currentCharFormat()
        while it.atEnd() is False:
            frag = it.fragment()
            it += 1
            if not frag.isValid():
                continue
            if frag.position() <= pos < frag.position() + len(frag.text()):
                fmt = frag.charFormat()
                break
        return fmt

    def apply_char_format(self, bold=None, italic=None, underline=None,
                          color=None, highlight=None, family=None, size=None,
                          clear=False):
        cursor = self.textCursor()
        fmt = QTextCharFormat()
        if clear:
            fmt.setFontWeight(QFont.Normal)
            fmt.setFontItalic(False)
            fmt.setFontUnderline(False)
            fmt.clearBackground()
            fmt.setForeground(self.palette().text())
        else:
            if bold is not None:
                fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)
            if italic is not None:
                fmt.setFontItalic(italic)
            if underline is not None:
                fmt.setFontUnderline(underline)
            if color is not None:
                fmt.setForeground(QColor(color))
            if highlight is not None:
                fmt.setBackground(QColor(highlight))
            if family is not None:
                fmt.setFontFamilies([family])
            if size is not None:
                fmt.setFontPointSize(size)
        if clear:
            cursor.setCharFormat(fmt)
            self.setTextCursor(cursor)
            self._sync_typing_format(fmt)
            return
        if not cursor.hasSelection() and not fmt.isEmpty():
            current = QTextCharFormat(self._selection_format())
            if bold is not None:
                current.setFontWeight(fmt.fontWeight())
            if italic is not None:
                current.setFontItalic(italic)
            if underline is not None:
                current.setFontUnderline(underline)
            if color is not None:
                current.setForeground(fmt.foreground())
            if highlight is not None:
                current.setBackground(fmt.background())
            if family is not None:
                current.setFontFamilies([family])
            if size is not None:
                current.setFontPointSize(size)
            cursor.setCharFormat(current)
            self.setTextCursor(cursor)
            return
        cursor.mergeCharFormat(fmt)
        self.setTextCursor(cursor)
        self._sync_typing_format(self._selection_format())

    def _sync_typing_format(self, fmt):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.setCharFormat(fmt)
            self.setTextCursor(cursor)

    def insert_snippet(self, text, cursor_offset=None):
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        start = cursor.position()
        cursor.insertText(text)
        cursor.endEditBlock()
        cursor.setPosition(start + (len(text) if cursor_offset is None
                                    else cursor_offset))
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def set_search_results(self, matches, active_index=-1):
        selections = []
        fmt_match = QTextCharFormat()
        fmt_match.setBackground(QColor(self._colors["search_match"]))
        fmt_active = QTextCharFormat()
        fmt_active.setBackground(QColor(self._colors["search_match_active"]))
        for i, cur in enumerate(matches):
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt_active if i == active_index else fmt_match
            sel.cursor = cur
            selections.append(sel)
        self.setExtraSelections(selections)

    # ---------------------------------------------------------------- tables

    def table_under_cursor(self):
        return self.textCursor().currentTable()

    def insert_real_table(self, rows, cols, header=True, border=1,
                            padding=4, header_fill=None, header_bold=True):
        """Insert a real editable QTextTable; park cursor in first cell."""
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.block().text().strip():
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertBlock()
        table = cursor.insertTable(rows + (1 if header else 0), cols,
                                   default_table_format(border, padding))
        if header:
            for c in range(cols):
                cell = table.cellAt(0, c)
                cc = cell.firstCursorPosition()
                bf = QTextCharFormat()
                if header_bold:
                    bf.setFontWeight(QFont.Bold)
                norm = _normalize_hex(header_fill)
                if norm:
                    bf.setBackground(QColor(norm))
                if not bf.isEmpty():
                    cc.setCharFormat(bf)
                cc.insertText(f"Header {c + 1}")
                if norm:
                    try:
                        cf = cell.format()
                        cf.setBackground(QColor(norm))
                        cell.setFormat(cf)
                    except Exception:
                        pass
        target = table.cellAt(1 if header else 0, 0).firstCursorPosition()
        cursor.endEditBlock()
        self.setTextCursor(target)
        self.ensureCursorVisible()
        return table

    def _apply_header_row(self, table, header_fill=None, header_bold=True):
        norm = _normalize_hex(header_fill)
        for c in range(table.columns()):
            try:
                cell = table.cellAt(0, c)
            except Exception:
                continue
            cur = cell.firstCursorPosition()
            end = cell.lastCursorPosition().position()
            guard = 0
            while cur.position() < end and guard < 2000:
                cur.setPosition(cur.position() + 1, QTextCursor.KeepAnchor)
                guard += 1
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Bold if header_bold else QFont.Normal)
            if norm:
                fmt.setBackground(QColor(norm))
            if end > cell.firstCursorPosition().position():
                cur.mergeCharFormat(fmt)
            else:
                # Empty header cell: set typing format + cell shading.
                cur.setCharFormat(fmt)
            if norm:
                try:
                    cf = cell.format()
                    cf.setBackground(QColor(norm))
                    cell.setFormat(cf)
                except Exception:
                    pass
            elif header_fill is None:
                try:
                    cf = cell.format()
                    cf.clearBackground()
                    cell.setFormat(cf)
                except Exception:
                    pass

    def _style_table(self, table):
        """Keep border/padding, ensure the header row stays bold."""
        try:
            cur_fmt = table.format()
            table.setFormat(default_table_format(
                cur_fmt.border(), cur_fmt.cellPadding(),
                cur_fmt.cellSpacing()))
        except Exception:
            try:
                table.setFormat(default_table_format())
            except Exception:
                pass
        self._apply_header_row(table)

    # --------------------------------------------------- table customisation

    def get_table_style(self, table=None):
        """Return {'border','padding','spacing','header_fill','header_bold'}."""
        table = table or self.table_under_cursor()
        if table is None:
            return None
        try:
            tfmt = table.format()
            border = int(tfmt.border())
            padding = float(tfmt.cellPadding())
        except Exception:
            border, padding = 1, 4
        try:
            spacing = float(tfmt.cellSpacing())
        except Exception:
            spacing = 0
        header_fill, header_bold = None, False
        try:
            cell = table.cellAt(0, 0)
            cfmt = cell.format()
            if cfmt.background().style() != Qt.NoBrush:
                col = cfmt.background().color()
                header_fill = "#%02x%02x%02x" % (col.red(), col.green(),
                                                col.blue())
            else:
                # Fall back to the first header fragment's background.
                blk = cell.firstCursorPosition().block()
                it = blk.begin()
                if not it.atEnd():
                    bg = it.fragment().charFormat().background()
                    if bg.style() != Qt.NoBrush:
                        col = bg.color()
                        header_fill = "#%02x%02x%02x" % (
                            col.red(), col.green(), col.blue())
            # Bold if any header fragment is bold.
            for c in range(table.columns()):
                blk = table.cellAt(0, c).firstCursorPosition().block()
                it = blk.begin()
                while not it.atEnd():
                    frag = it.fragment()
                    it += 1
                    if frag.charFormat().fontWeight() > QFont.Normal:
                        header_bold = True
                        break
                if header_bold:
                    break
        except Exception:
            pass
        return {"border": border, "padding": padding, "spacing": spacing,
                "header_fill": header_fill, "header_bold": header_bold}

    def set_table_style(self, table=None, border=None, padding=None,
                        spacing=None, header_fill="__keep__",
                        header_bold="__keep__"):
        """Restyle the table under the cursor (or `table`)."""
        table = table or self.table_under_cursor()
        if table is None:
            return False
        cur = self.get_table_style(table) or {}
        if border is None:
            border = cur.get("border", 1)
        if padding is None:
            padding = cur.get("padding", 4)
        if spacing is None:
            spacing = cur.get("spacing", 0)
        try:
            table.setFormat(default_table_format(border, padding, spacing))
        except Exception:
            return False
        fill_touched = header_fill != "__keep__"
        bold_touched = header_bold != "__keep__"
        if fill_touched or bold_touched:
            if not fill_touched:
                header_fill = cur.get("header_fill")
            if not bold_touched:
                header_bold = cur.get("header_bold", True)
            self._apply_header_row(table, header_fill, bool(header_bold))
        return True

    def _cell_row_col(self):
        cursor = self.textCursor()
        table = cursor.currentTable()
        if table is None:
            return None, None, None
        try:
            cell = table.cellAt(cursor)
        except Exception:
            return table, None, None
        return table, cell.row(), cell.column()

    def insert_table_row(self, below=True):
        table, row, _col = self._cell_row_col()
        if table is None or row is None:
            return False
        table.insertRows(row + (1 if below else 0), 1)
        return True

    def insert_table_column(self, right=True):
        table, _row, col = self._cell_row_col()
        if table is None or col is None:
            return False
        table.insertColumns(col + (1 if right else 0), 1)
        return True

    def delete_table_row(self):
        table, row, _col = self._cell_row_col()
        if table is None or row is None:
            return False
        if table.rows() <= 1:
            return self.delete_table()
        table.removeRows(row, 1)
        return True

    def delete_table_column(self):
        table, _row, col = self._cell_row_col()
        if table is None or col is None:
            return False
        if table.columns() <= 1:
            return self.delete_table()
        table.removeColumns(col, 1)
        return True

    def delete_table(self):
        cursor = self.textCursor()
        table = cursor.currentTable()
        if table is None:
            return False
        start = table.cellAt(0, 0).firstCursorPosition().position()
        end = table.cellAt(table.rows() - 1,
                           table.columns() - 1).lastCursorPosition() \
            .position()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        # Swallow one surrounding block separator so no stray blank line.
        try:
            after = self.document().findBlock(end)
            if after.isValid():
                cursor.setPosition(after.position(), QTextCursor.KeepAnchor)
        except Exception:
            pass
        cursor.removeSelectedText()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True

    def toggle_header_row(self):
        table = self.table_under_cursor()
        if table is None:
            return False
        cur = self.get_table_style(table) or {}
        return self.set_table_style(
            table, header_bold=not cur.get("header_bold", True))

    def format_markdown_table(self) -> bool:
        """Style the real table under the cursor; convert `|…|` groups.

        Returns True when a real table was styled or a markdown pipe block
        was converted into a real table, False when there is no table.
        """
        table = self.table_under_cursor()
        if table is not None:
            self._style_table(table)
            return True
        # Migrate legacy `| a | b |` pipe blocks into a real table.
        block = self.textCursor().block()
        if not _TABLE_ROW.match(block.text()):
            return False
        first = block
        while first.previous().isValid() and \
                _TABLE_ROW.match(first.previous().text()):
            first = first.previous()
        last = block
        while last.next().isValid() and _TABLE_ROW.match(last.next().text()):
            last = last.next()
        lines = []
        b = first
        while True:
            lines.append(b.text())
            if b == last:
                break
            b = b.next()
        data = [_split_row(r) for r in lines]
        header = None
        if len(data) >= 2 and _is_separator(lines[1]):
            header, data = data[0], data[2:]
        if not data and header is None:
            return False
        if not data:
            data = [header]
            header = None
        width = max(len(r) for r in data + ([header] if header else []))
        data = [r + [""] * (width - len(r)) for r in data]
        if header is not None:
            header = header + [""] * (width - len(header))
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(first.position())
        cursor.setPosition(last.position() + len(last.text()),
                           QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        table = cursor.insertTable(len(data) + (1 if header else 0), width,
                                   default_table_format())
        if header is not None:
            for c, text in enumerate(header):
                cell = table.cellAt(0, c)
                cc = cell.firstCursorPosition()
                bf = QTextCharFormat()
                bf.setFontWeight(QFont.Bold)
                cc.setCharFormat(bf)
                cc.insertText(text)
        for ri, row in enumerate(data):
            tr = (1 if header is not None else 0) + ri
            for c, text in enumerate(row):
                if header is None or tr != 0 or True:
                    table.cellAt(tr, c).firstCursorPosition().insertText(text)
        cursor.endEditBlock()
        self.setTextCursor(table.cellAt(0, 0).firstCursorPosition())
        self.ensureCursorVisible()
        return True

    # ------------------------------------------------------------- key input

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_gutter()
        self.caret.resize_to_viewport()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.caret.set_focus_state(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.caret.set_focus_state(False)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() // 120
            if steps:
                self.zoom_font(steps)
            event.accept()
            return
        super().wheelEvent(event)

    def _move_to_cell(self, direction):
        cursor = self.textCursor()
        table = cursor.currentTable()
        if table is None:
            return False
        try:
            cell = table.cellAt(cursor)
        except Exception:
            return False
        r, c = cell.row(), cell.column()
        if direction > 0:
            c += 1
            if c >= table.columns():
                c = 0
                r += 1
            if r >= table.rows():
                table.appendRows(1)
        else:
            c -= 1
            if c < 0:
                c = table.columns() - 1
                r -= 1
            if r < 0:
                return True  # stay put at first cell
        self.setTextCursor(table.cellAt(r, c).firstCursorPosition())
        self.ensureCursorVisible()
        return True

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key_Tab and not mods & (Qt.ControlModifier |
                                             Qt.AltModifier | Qt.MetaModifier):
            if self.table_under_cursor() is not None:
                self._move_to_cell(1)
                return
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and
                                     mods & Qt.ShiftModifier):
            if self.table_under_cursor() is not None:
                self._move_to_cell(-1)
                return
        super().keyPressEvent(event)

    # ---------------------------------------------------------- context menu

    def _open_table_properties(self):
        """Show the Table Properties dialog for the table under cursor."""
        table = self.table_under_cursor()
        if table is None:
            return False
        from smoothcursor.views.window import TablePropertiesDialog
        dlg = TablePropertiesDialog(self.window(),
                                    self.get_table_style(table) or {})
        if not dlg.exec():
            return False
        return self.set_table_style(
            table, border=dlg.border(), padding=dlg.padding(),
            header_fill=dlg.header_fill(),
            header_bold=dlg.header_bold())

    def _status_hint(self, text):
        try:
            win = self.window()
            if win is not None and hasattr(win, "statusBar"):
                win.statusBar().showMessage(text, 3000)
        except Exception:
            pass

    def contextMenuEvent(self, event):
        """Standard edit menu + table section when right-clicking a table."""
        try:
            vp_pos = self.viewport().mapFrom(self, event.pos())
            clicked = self.cursorForPosition(vp_pos)
        except Exception:
            clicked = None
        clicked_table = None
        if clicked is not None:
            try:
                clicked_table = clicked.currentTable()
            except Exception:
                clicked_table = None
        if clicked_table is not None:
            # Park the cursor in the right-clicked cell (unless the click
            # is inside the current selection, which must be preserved
            # for Cut/Copy).
            try:
                cur = self.textCursor()
                inside = (cur.hasSelection() and
                          cur.selectionStart() <= clicked.position() <=
                          cur.selectionEnd())
                if not inside:
                    self.setTextCursor(clicked)
            except Exception:
                pass
        in_table = (self.table_under_cursor() is not None or
                    clicked_table is not None)
        menu = self.createStandardContextMenu()
        try:
            append_spelling_section(menu, self, event.pos())
            if not in_table:
                menu.exec(event.globalPos())
                return
            menu.addSeparator()
            props = menu.addAction("Table Properties…")
            props.triggered.connect(lambda: self._open_table_properties())
            fmt = menu.addAction("Format Table")
            fmt.triggered.connect(
                lambda: (self.format_markdown_table() or
                         self._status_hint("No table under the cursor")))
            menu.addSeparator()
            above = menu.addAction("Insert Row Above")
            above.triggered.connect(
                lambda: (self.insert_table_row(below=False) or
                         self._status_hint("Cannot insert row")))
            below = menu.addAction("Insert Row Below")
            below.triggered.connect(
                lambda: (self.insert_table_row(below=True) or
                         self._status_hint("Cannot insert row")))
            left = menu.addAction("Insert Column Left")
            left.triggered.connect(
                lambda: (self.insert_table_column(right=False) or
                         self._status_hint("Cannot insert column")))
            right = menu.addAction("Insert Column Right")
            right.triggered.connect(
                lambda: (self.insert_table_column(right=True) or
                         self._status_hint("Cannot insert column")))
            menu.addSeparator()
            del_row = menu.addAction("Delete Row")
            del_row.triggered.connect(
                lambda: (self.delete_table_row() or
                         self._status_hint("Cannot delete row")))
            del_col = menu.addAction("Delete Column")
            del_col.triggered.connect(
                lambda: (self.delete_table_column() or
                         self._status_hint("Cannot delete column")))
            del_tbl = menu.addAction("Delete Table")
            del_tbl.triggered.connect(
                lambda: (self.delete_table() or
                         self._status_hint("Cannot delete table")))
            menu.addSeparator()
            toggle = menu.addAction("Toggle Header Row")
            toggle.triggered.connect(
                lambda: (self.toggle_header_row() or
                         self._status_hint("Cannot toggle header")))
            menu.exec(event.globalPos())
        finally:
            try:
                menu.deleteLater()
            except Exception:
                pass
