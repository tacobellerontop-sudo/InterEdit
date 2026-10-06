"""CodeEditor: QPlainTextEdit + gutter + current-line highlight + smooth caret."""

import os
import re

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QPainter, QPalette,
                           QTextBlockFormat, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from smoothcursor.editor.caret import SmoothCaret
from smoothcursor.editor.docx_toolbar import FormatToolbar
from smoothcursor.editor.line_numbers import LineNumberArea, \
    make_gutter_helpers
from smoothcursor.editor.spellcheck import (
    SpellHighlighter, append_spelling_section,
)
from smoothcursor.editor.syntax import create_highlighter

# Auto-format patterns (markdown-style lists, task lists, blockquotes).
_ORDERED_RE = re.compile(r"^([ \t]*)(\d+)([.)])([ \t]+)(.*)$")
_BULLET_RE = re.compile(r"^([ \t]*)([-*+])([ \t]+)(?:(\[[ xX]\])([ \t]+))?(.*)$")
_QUOTE_RE = re.compile(r"^([ \t]*)((?:>[ \t]*)+)(.*)$")
_PAIR_MATCH = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
_PAIR_CLOSE = {v: k for k, v in _PAIR_MATCH.items() if v not in _PAIR_MATCH}


class CodeEditor(QPlainTextEdit):
    modified_changed = Signal(bool)

    def __init__(self, settings, colors, language="python", parent=None):
        super().__init__(parent)
        self.settings = settings
        self._colors = dict(colors)
        self.language = language
        self.file_path = None
        self.untitled_name = ""

        # Hide Qt's default caret; SmoothCaret paints over the same spot.
        self.setCursorWidth(0)
        self.setFrameShape(QPlainTextEdit.NoFrame)
        self.setWordWrapMode(self._wrap_mode(settings.get("word_wrap")))
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setViewportMargins(0, 0, 0, 0)

        self.gutter = LineNumberArea(self)
        self._gutter_colors, self._gutter_width, self._gutter_paint = \
            make_gutter_helpers(self)
        self._gutter_colors(self._colors)

        self.caret = SmoothCaret(self, QColor(colors["accent"]))
        self.caret.speed = float(settings.get("caret_speed"))
        self.caret.blink_ms = int(settings.get("caret_blink_ms"))

        self.highlighter = create_highlighter(language, self.document(),
                                              colors)
        self.spell_highlighter = SpellHighlighter(self.document(),
                                                  self._colors)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.document().modificationChanged.connect(self.modified_changed)
        self.document().blockCountChanged.connect(self._update_gutter_width)

        self._redo_action = QAction("Redo", self)
        self._redo_action.setShortcut("Ctrl+Y")
        self._redo_action.triggered.connect(self.redo)
        self.addAction(self._redo_action)

        self._current_line_rect = None
        self._update_gutter_width()
        self.apply_settings()
        self.apply_colors()
        self.caret.resize_to_viewport()

        # Rich-text mode (used by .docx tabs): floating toolbar on selection.
        self.rich_mode = False
        self.format_toolbar = None

    def set_rich_mode(self, enabled: bool):
        """Toggle the floating formatting toolbar (docx documents)."""
        if enabled == self.rich_mode:
            return
        self.rich_mode = enabled
        if enabled:
            self.format_toolbar = FormatToolbar(self)
            self.selectionChanged.connect(self._on_selection_changed)
        else:
            if self.format_toolbar is not None:
                self.format_toolbar.hide()
                self.format_toolbar.deleteLater()
                self.format_toolbar = None

    def _on_selection_changed(self):
        tb = self.format_toolbar
        if tb is None:
            return
        if self.textCursor().hasSelection():
            tb.refresh()
            tb.place_over_selection()
            tb.show()
            tb.raise_()
        else:
            tb.hide()

    # ------------------------------------------------------------ rich text

    def _selection_format(self) -> QTextCharFormat:
        """Char format of the character at the selection start.

        Reads the owning fragment directly: QTextCursor.charFormat() returns
        the format of the character *before* the cursor position, which is
        the wrong side of the boundary for toggle state.
        """
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
        """Apply formatting to the selection, or set the typing format when
        there is no selection (so new text inherits it).

        highlight=None means "clear highlight"; not passing highlight leaves
        existing background untouched.
        """
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
            # No selection: make the format apply to what the user types next.
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
        """Make subsequent typed characters inherit the applied format."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.setCharFormat(fmt)
            self.setTextCursor(cursor)

    def insert_from_mime_data(self, source):
        """Rich mode: paste as plain text to keep the docx model simple."""
        if self.rich_mode and source.hasText():
            self.textCursor().insertText(source.text())
            return
        super().insertFromMimeData(source)

    # ------------------------------------------------------------- settings

    def _position_gutter(self):
        rect = self.contentsRect()
        self.gutter.setGeometry(QRect(rect.left(), rect.top(),
                                      self.gutter_width(), rect.height()))

    # ------------------------------------------------------------- settings

    @staticmethod
    def language_for(path):
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower()
        return {".py": "python", ".pyw": "python", ".json": "json"}.get(ext)

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
        fm = self.fontMetrics()
        self.setTabStopDistance(fm.horizontalAdvance(" ")
                                * int(s.get("tab_size")))
        self.setWordWrapMode(self._wrap_mode(s.get("word_wrap")))
        self.caret.speed = float(s.get("caret_speed"))
        self.caret.blink_ms = int(s.get("caret_blink_ms"))
        self._update_gutter_width()
        self.update_spellcheck()
        self.caret._snap_now()

    def update_spellcheck(self):
        """Wavy underlines on prose tabs only (never inside code)."""
        try:
            enabled = bool(self.settings.get("spellcheck"))
        except Exception:
            enabled = True
        self.spell_highlighter.set_active(
            enabled and self.language not in ("python", "json"))

    def apply_colors(self, colors=None):
        """Recolor editor, gutter and caret; pass `colors` to retheme."""
        if colors is not None:
            self._colors = dict(colors)
        c = self._colors
        palette = self.palette()
        palette.setColor(QPalette.Base, QColor(c["editor_bg"]))
        palette.setColor(QPalette.Text, QColor(c["editor_text"]))
        palette.setColor(QPalette.Highlight, QColor(c["selection"]))
        palette.setColor(QPalette.HighlightedText,
                         QColor(c["editor_text"]))
        self.setPalette(palette)
        self._gutter_colors(c)
        self.caret.apply_theme(QColor(c["accent"]))
        if self.highlighter:
            self.highlighter.apply_colors(c)
        self.spell_highlighter.apply_colors(c)
        self.viewport().update()
        self.gutter.update()

    # --------------------------------------------------------------- gutter

    def gutter_width(self):
        return self._gutter_width()

    def gutter_paint_event(self, event, area):
        self._gutter_paint(event, area)

    def _update_gutter_width(self, *_):
        width = self.gutter_width()
        self.setViewportMargins(width, 0, 0, 0)
        self._position_gutter()
        self.gutter.setVisible(width > 0)
        self.gutter.update()

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(),
                               rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def select_line_at(self, y):
        """Click in the gutter selects that whole line."""
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        while block.isValid():
            height = round(self.blockBoundingRect(block).height())
            if top <= y < top + height:
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.LineUnderCursor)
                self.setTextCursor(cursor)
                self.setFocus()
                return
            top += height
            block = block.next()

    # --------------------------------------------------------- line visual

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

    def paintEvent(self, event):
        # Current-line highlight, then the normal text paint on top.
        painter = QPainter(self.viewport())
        if not self.textCursor().hasSelection():
            rect = self.cursorRect()
            rect.setX(0)
            rect.setWidth(self.viewport().width())
            painter.fillRect(rect, QColor(self._colors["current_line"]))
            self._current_line_rect = QRect(rect)
        else:
            self._current_line_rect = None
        painter.end()
        super().paintEvent(event)

    def _on_cursor_moved(self):
        # Cheap targeted repaint of the old + new current-line rows only.
        rect = self.cursorRect()
        rect.setX(0)
        rect.setWidth(self.viewport().width())
        if self._current_line_rect is not None:
            self.viewport().update(self._current_line_rect.united(rect))
        # Relative/hybrid gutter numbers and the active-row highlight
        # follow the cursor even when nothing scrolls.
        self.gutter.update()
        self.caret.on_activity()

    # ------------------------------------------------------------ key input

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() // 120
            if steps:
                self.zoom_font(steps)
            event.accept()
            return
        super().wheelEvent(event)

    def zoom_font(self, steps):
        """Ctrl+wheel / Ctrl+=/- zoom; routes through the window so every
        tab updates, falling back to this editor alone."""
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

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter) and \
                not mods & (Qt.ControlModifier | Qt.AltModifier |
                            Qt.MetaModifier):
            self._smart_newline()
            return
        if mods & Qt.ControlModifier and \
                not mods & (Qt.AltModifier | Qt.MetaModifier):
            if key == Qt.Key_Slash and not mods & Qt.ShiftModifier:
                self.toggle_comment()
                return
            if key == Qt.Key_D and not mods & Qt.ShiftModifier:
                self.duplicate_line_or_selection()
                return
            if key == Qt.Key_J and not mods & Qt.ShiftModifier:
                self.join_with_next()
                return
            if key == Qt.Key_K and mods & Qt.ShiftModifier:
                self.delete_lines()
                return
        if mods & Qt.AltModifier and \
                not mods & (Qt.ControlModifier | Qt.MetaModifier):
            if key == Qt.Key_Up:
                self.move_lines(-1)
                return
            if key == Qt.Key_Down:
                self.move_lines(1)
                return
        # Shift+Tab arrives as Key_Backtab on most platforms; check the
        # dedent case first so a Tab-with-Shift never falls into indent.
        if key == Qt.Key_Backtab or (key == Qt.Key_Tab and
                                     mods & Qt.ShiftModifier):
            if self._indent_selection(dedent=True):
                return
            if self._dedent_current_line():
                return
            return
        if key == Qt.Key_Tab:
            if self._indent_selection(dedent=False):
                return
            if self._indent_list_line():
                return
            self._insert_indent()
            return
        if key == Qt.Key_Backspace and self._auto_pairs_enabled() \
                and not self.textCursor().hasSelection():
            if self._handle_backspace_pair():
                return
        text = event.text()
        if text and self._auto_pairs_enabled() \
                and not mods & (Qt.ControlModifier | Qt.AltModifier |
                                Qt.MetaModifier):
            if text in _PAIR_MATCH and self._handle_opening_pair(text):
                return
            if (text in _PAIR_CLOSE or text in ("\"", "'")) \
                    and self._handle_closing_skip(text):
                return
        super().keyPressEvent(event)

    def _indent_unit(self):
        if self.settings.get("insert_spaces"):
            return " " * int(self.settings.get("tab_size"))
        return "\t"

    def _insert_indent(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        cursor.insertText(self._indent_unit())

    def _auto_lists_enabled(self) -> bool:
        try:
            return bool(self.settings.get("auto_lists"))
        except Exception:
            return True

    def _auto_pairs_enabled(self) -> bool:
        try:
            return bool(self.settings.get("auto_pairs"))
        except Exception:
            return True

    def _smart_newline(self):
        """Smart newline: lists, blockquotes, indent, brace expansion.

        - ``1. item`` -> next line starts with ``2. `` (``1)`` style kept).
        - ``-``/``*``/``+`` bullets continue; ``- [ ]`` task resets to empty.
        - ``> quote`` continues the ``> `` prefix.
        - Enter on an *empty* list/quote item exits it (nested items dedent
          one level first) instead of adding another marker.
        - Ordered lists after the cursor are renumbered so ``1. 2. 3.``
          stays sequential.
        - Falls back to keeping the indent, plus an extra level after ``:``.
        """
        cursor = self.textCursor()
        block = cursor.block()
        full = block.text()
        pos = cursor.positionInBlock()
        line_before = full[:pos]
        line_after = full[pos:]

        # Brace expansion: "{|}" -> "{\n    \n}".
        if self._auto_pairs_enabled() and line_before \
                and line_after.lstrip():
            prev, nxt = line_before[-1], line_after.lstrip()[:1]
            if prev in "{[(" and nxt == _PAIR_MATCH[prev]:
                self._brace_newline(cursor, prev)
                return

        if self._auto_lists_enabled() and self._try_list_newline(
                cursor, block, full, pos, line_after):
            return

        indent = re.match(r"[ \t]*", line_before).group(0)
        extra = self._indent_unit() if line_before.rstrip().endswith(":") \
            else ""
        cursor.beginEditBlock()
        cursor.insertBlock()
        cursor.insertText(indent + extra)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # --------------------------------------------------- list continuation

    def _try_list_newline(self, cursor, block, full, pos, line_after) -> bool:
        """Handle Enter on list/quote lines. Returns True if handled."""
        qm = _QUOTE_RE.match(full)
        qprefix, rest, qoff = "", full, 0
        if qm:
            qprefix = qm.group(1) + qm.group(2)
            rest = qm.group(3)
            qoff = len(qprefix)

        om = _ORDERED_RE.match(rest)
        if om:
            base, num_s, delim, sp, content = om.groups()
            marker_len = qoff + len(base) + len(num_s) + len(delim) + len(sp)
            if pos < marker_len:
                return False
            # Empty item ("1. <cursor>") -> exit/dedent, don't add a row.
            if rest[len(base) + len(num_s) + len(delim) + len(sp):].strip() \
                    == "" and line_after.strip() == "":
                self._exit_ordered_item(block, qprefix, base, num_s, delim,
                                        sp)
                return True
            nxt = f"{qprefix}{base}{int(num_s) + 1}{delim}{sp}"
            self._insert_continuation(cursor, block, base, nxt,
                                      renumber=(qprefix, base, int(num_s) + 1))
            return True

        bm = _BULLET_RE.match(rest)
        if bm:
            base, bull, sp, check, checksp, content = bm.groups()
            check_txt = (check + checksp) if check else ""
            marker_len = qoff + len(base) + len(bull) + len(sp) + \
                len(check_txt)
            if pos < marker_len:
                return False
            if content.strip() == "" and line_after.strip() == "":
                self._exit_bullet_item(block, qprefix, base, bull, sp,
                                       check_txt)
                return True
            # New task items always start unchecked.
            new_check = "[ ]" + (checksp or sp) if check else ""
            nxt = f"{qprefix}{base}{bull}{sp}{new_check}"
            self._insert_continuation(cursor, block, base, nxt)
            return True

        if qm:
            # Plain blockquote line.
            if rest.strip() == "" and line_after.strip() == "":
                self._exit_quote(block, qm.group(1), qm.group(2))
                return True
            prefix = qprefix if qprefix.endswith((" ", "\t")) \
                else qprefix + " "
            cursor.beginEditBlock()
            cursor.insertBlock()
            cursor.insertText(prefix)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            return True
        return False

    def _insert_continuation(self, cursor, block, base, prefix,
                             renumber=None):
        cursor.beginEditBlock()
        cursor.insertBlock()
        cursor.insertText(prefix)
        if renumber is not None:
            qprefix, rbase, rnum = renumber
            # Renumber subsequent same-level items so the list stays 1-2-3.
            expected = rnum
            nb = cursor.block().next()
            while nb.isValid():
                text = nb.text()
                sub = text
                if qprefix and sub.startswith(qprefix):
                    sub = sub[len(qprefix):]
                elif qprefix:
                    break
                m = _ORDERED_RE.match(sub)
                if not m or m.group(1) != rbase:
                    break
                expected += 1
                if int(m.group(2)) != expected:
                    c = QTextCursor(nb)
                    start = len(qprefix) + len(m.group(1))
                    c.movePosition(QTextCursor.StartOfBlock)
                    c.movePosition(QTextCursor.Right,
                                   QTextCursor.MoveAnchor, start)
                    c.movePosition(QTextCursor.Right,
                                   QTextCursor.KeepAnchor, len(m.group(2)))
                    c.insertText(str(expected))
                nb = nb.next()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _dedent_one(self, indent: str) -> str:
        if indent.startswith("\t"):
            return indent[1:]
        width = int(self.settings.get("tab_size"))
        n = len(indent) - len(indent.lstrip(" "))
        return indent[:max(0, n - width)] + indent[n:]

    def _clear_block_prefix(self, block, keep: str, remove_len: int,
                            insert: str = ""):
        """Replace the first `remove_len` chars of `block` with insert text
        and park the main cursor on that line after `keep + insert`."""
        bc = QTextCursor(block)
        bc.movePosition(QTextCursor.StartOfBlock)
        bc.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor,
                        remove_len)
        bc.beginEditBlock()
        bc.removeSelectedText()
        if insert:
            bc.insertText(insert)
        bc.endEditBlock()
        cur = self.textCursor()
        cur.setPosition(block.position() + len(keep) + len(insert))
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def _exit_ordered_item(self, block, qprefix, base, num_s, delim, sp):
        marker = base + num_s + delim + sp
        if base:
            # Nested empty item: dedent one level, keep the marker.
            dedented = self._dedent_one(base)
            self._clear_block_prefix(block, qprefix + dedented,
                                     len(qprefix) + len(marker),
                                     qprefix + dedented + num_s + delim + sp)
        else:
            self._clear_block_prefix(block, qprefix,
                                     len(qprefix) + len(marker), qprefix)

    def _exit_bullet_item(self, block, qprefix, base, bull, sp, check_txt):
        marker = base + bull + sp + check_txt
        if base:
            dedented = self._dedent_one(base)
            self._clear_block_prefix(
                block, qprefix + dedented, len(qprefix) + len(marker),
                qprefix + dedented + bull + sp + check_txt)
        else:
            self._clear_block_prefix(block, qprefix,
                                     len(qprefix) + len(marker), qprefix)

    def _exit_quote(self, block, base, quotes):
        self._clear_block_prefix(block, base, len(base) + len(quotes), base)

    # ------------------------------------------------------ bracket pairs

    def _brace_newline(self, cursor, opener):
        indent = re.match(r"[ \t]*", cursor.block().text()).group(0)
        unit = self._indent_unit()
        cursor.beginEditBlock()
        cursor.insertBlock()
        cursor.insertText(indent + unit)
        cursor.insertBlock()
        cursor.insertText(indent)
        # Park the cursor at the end of the middle (indented) line.
        middle = cursor.block().previous()
        cur = self.textCursor()
        cur.setPosition(middle.position() + len(middle.text()))
        cursor.endEditBlock()
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def _next_char(self):
        c = self.textCursor()
        if c.positionInBlock() >= len(c.block().text()):
            return ""
        return c.block().text()[c.positionInBlock()]

    def _prev_char(self):
        c = self.textCursor()
        if c.positionInBlock() <= 0:
            return ""
        return c.block().text()[c.positionInBlock() - 1]

    def _handle_opening_pair(self, text: str) -> bool:
        cursor = self.textCursor()
        closer = _PAIR_MATCH[text]
        if cursor.hasSelection():
            selected = cursor.selectedText().replace("\u2029", "\n")
            cursor.beginEditBlock()
            cursor.removeSelectedText()
            cursor.insertText(text + selected + closer)
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            # Leave the selection covering the wrapped text.
            end = cursor.position() - len(closer)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor,
                                len(selected))
            self.setTextCursor(cursor)
            return True
        if text in ("\"", "'"):
            # Don't turn apostrophes inside words into pairs.
            if self._prev_char().isalnum():
                return False
            if self._next_char() not in ("", " ", "\t", ")", "]", "}",
                                         ",", ".", ";", ":", "!", "?",
                                         "\n"):
                return False
        elif self._next_char() not in ("", " ", "\t", ")", "]", "}",
                                           ",", ";", ":", ".", "!", "?"):
            return False
        cursor.beginEditBlock()
        cursor.insertText(text + closer)
        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.Left)
        self.setTextCursor(cursor)
        return True

    def _handle_closing_skip(self, text: str) -> bool:
        cursor = self.textCursor()
        if not cursor.hasSelection() and self._next_char() == text:
            # Typing ")" etc. over an auto-inserted closer skips past it.
            if text in ("\"", "'"):
                cursor.movePosition(QTextCursor.Right)
                self.setTextCursor(cursor)
                return True
            cursor.movePosition(QTextCursor.Right)
            self.setTextCursor(cursor)
            return True
        return False

    def _handle_backspace_pair(self) -> bool:
        prev, nxt = self._prev_char(), self._next_char()
        if prev and nxt and _PAIR_MATCH.get(prev) == nxt:
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.deleteChar()
            cursor.deletePreviousChar()
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return True
        return False

    # ------------------------------------------------- tab on list lines

    @staticmethod
    def _list_marker_len(text: str) -> int:
        qm = _QUOTE_RE.match(text)
        rest, qoff = (text, 0)
        if qm and qm.group(1) + qm.group(2) != text:
            rest, qoff = qm.group(3), len(qm.group(1) + qm.group(2))
        om = _ORDERED_RE.match(rest)
        if om:
            return qoff + len(om.group(1) + om.group(2) + om.group(3) +
                              om.group(4))
        bm = _BULLET_RE.match(rest)
        if bm:
            check_txt = (bm.group(4) + bm.group(5)) if bm.group(4) else ""
            return qoff + len(bm.group(1) + bm.group(2) + bm.group(3) +
                              check_txt)
        return -1

    def _indent_list_line(self) -> bool:
        """Tab on a list line indents the whole line (keeps the marker)."""
        cursor = self.textCursor()
        if self._list_marker_len(cursor.block().text()) < 0:
            return False
        bc = QTextCursor(cursor.block())
        bc.movePosition(QTextCursor.StartOfBlock)
        bc.insertText(self._indent_unit())
        self.ensureCursorVisible()
        return True

    def _dedent_current_line(self) -> bool:
        """Shift+Tab with no selection dedents the current line."""
        cursor = self.textCursor()
        text = cursor.block().text()
        if not text.startswith((" ", "\t")):
            return False
        bc = QTextCursor(cursor.block())
        bc.movePosition(QTextCursor.StartOfBlock)
        if text.startswith("\t"):
            bc.deleteChar()
        else:
            width = int(self.settings.get("tab_size"))
            n = len(text) - len(text.lstrip(" "))
            for _ in range(min(width, n)):
                bc.deleteChar()
        self.ensureCursorVisible()
        return True

    def insertFromMimeData(self, source):  # Qt override name
        self.insert_from_mime_data(source)

    def contextMenuEvent(self, event):
        """Default edit menu, plus spelling suggestions when relevant."""
        menu = self.createStandardContextMenu()
        try:
            append_spelling_section(menu, self, event.pos())
            menu.exec(event.globalPos())
        finally:
            try:
                menu.deleteLater()
            except Exception:
                pass

    def insert_snippet(self, text, cursor_offset=None):
        """Insert `text` over the selection; park the cursor at
        `cursor_offset` (default: end of the inserted text)."""
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

    def format_markdown_table(self) -> bool:
        """Pad the cells of the `|` table under the cursor so pipes align.

        Returns False when the cursor is not on a table row.
        """
        block = self.textCursor().block()
        if not block.text().strip().startswith("|"):
            return False
        first = block
        while first.previous().isValid() and first.previous().text() \
                .strip().startswith("|"):
            first = first.previous()
        last = block
        while last.next().isValid() and last.next().text().strip() \
                .startswith("|"):
            last = last.next()
        rows = []
        b = first
        while True:
            rows.append([c.strip() for c in
                         b.text().strip().strip("|").split("|")])
            if b == last:
                break
            b = b.next()
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        col_w = [0] * width
        for r in rows:
            for i, cell in enumerate(r):
                if not re.match(r"^:?-{3,}:?$", cell):
                    col_w[i] = max(col_w[i], len(cell))
        lines = []
        for r in rows:
            if all(re.match(r"^:?-{3,}:?$", c) for c in r):
                lines.append("|" + "|".join(
                    "-" * max(w + 2, 3) for w in col_w) + "|")
            else:
                lines.append("| " + " | ".join(
                    c.ljust(w) for c, w in zip(r, col_w)) + " |")
        cursor = self.textCursor()
        line_no = block.blockNumber() - first.blockNumber()
        col = cursor.positionInBlock()
        cursor.beginEditBlock()
        cursor.setPosition(first.position())
        cursor.setPosition(last.position() + len(last.text()),
                           QTextCursor.KeepAnchor)
        cursor.insertText("\n".join(lines))
        cursor.endEditBlock()
        target = self.document().findBlockByNumber(
            first.blockNumber() + line_no)
        cursor.setPosition(target.position()
                           + min(col, len(target.text())))
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        return True

    def _indent_selection(self, dedent: bool) -> bool:
        """Indent/dedent every selected line. Returns False if unused."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        doc = self.document()
        start, end = sorted((cursor.selectionStart(), cursor.selectionEnd()))
        first = doc.findBlock(start)
        last = doc.findBlock(max(end - 1, start))
        unit = self._indent_unit()
        edit = self.textCursor()
        edit.beginEditBlock()

        block = first
        while True:
            line_cursor = QTextCursor(block)
            line_cursor.movePosition(QTextCursor.StartOfBlock)
            text = block.text()
            if dedent:
                if text.startswith("\t"):
                    line_cursor.deleteChar()
                else:
                    width = int(self.settings.get("tab_size"))
                    spaces = len(text) - len(text.lstrip(" "))
                    for _ in range(min(width, spaces)):
                        line_cursor.deleteChar()
            elif text.strip():  # don't indent blank lines
                line_cursor.insertText(unit)
            if block == last:
                break
            block = block.next()
        edit.endEditBlock()
        self.setTextCursor(cursor)
        return True

    # -------------------------------------------------------- line operations

    def _doc_end(self):
        return self.document().characterCount() - 1

    def _line_range(self, cursor):
        """First/last blocks covered by the cursor or its selection.

        A selection ending exactly at a block start excludes that block
        (standard line-operation behavior).
        """
        doc = self.document()
        if cursor.hasSelection():
            start, end = sorted((cursor.selectionStart(),
                                 cursor.selectionEnd()))
            first = doc.findBlock(start)
            last = doc.findBlock(max(end - 1, start))
        else:
            first = last = doc.findBlock(cursor.position())
        return first, last

    def _block_count(self, first, last):
        n = 1
        block = first
        while block != last and block.isValid():
            block = block.next()
            n += 1
        return n

    def _comment_prefix(self):
        return "// " if self.language == "json" else "# "

    def toggle_comment(self):
        """Ctrl+/ — comment/uncomment current line or selected lines."""
        cursor = self.textCursor()
        first, last = self._line_range(cursor)
        prefix = self._comment_prefix()
        bare = prefix.rstrip()
        blocks = []
        block = first
        while True:
            blocks.append(block)
            if block == last:
                break
            block = block.next()
        targets = [b for b in blocks if b.text().strip()]
        if not targets:
            return
        commented = all(b.text().lstrip().startswith(bare)
                        for b in targets)
        cursor.beginEditBlock()
        for blk in targets:
            bc = QTextCursor(blk)
            bc.movePosition(QTextCursor.StartOfBlock)
            text = blk.text()
            indent = len(text) - len(text.lstrip(" \t"))
            bc.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor,
                            indent)
            if commented:
                rest = text[indent:indent + len(prefix)]
                take = len(prefix) if rest == prefix else len(bare)
                bc.movePosition(QTextCursor.Right,
                                QTextCursor.KeepAnchor, take)
                bc.removeSelectedText()
            else:
                bc.insertText(prefix)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def duplicate_line_or_selection(self):
        """Ctrl+D — duplicate the selection, or the current line below."""
        cursor = self.textCursor()
        doc = self.document()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            start, end = sorted((cursor.selectionStart(),
                                 cursor.selectionEnd()))
            sel = QTextCursor(doc)
            sel.setPosition(start)
            sel.setPosition(end, QTextCursor.KeepAnchor)
            frag = sel.selection()
            cursor.setPosition(end)
            cursor.insertFragment(frag)
        else:
            block = cursor.block()
            col = cursor.positionInBlock()
            bc = QTextCursor(block)
            bc.movePosition(QTextCursor.StartOfBlock)
            bc.movePosition(QTextCursor.EndOfBlock,
                            QTextCursor.KeepAnchor)
            frag = bc.selection()
            cursor.movePosition(QTextCursor.EndOfBlock)
            cursor.insertBlock()
            cursor.insertFragment(frag)
            cursor.movePosition(QTextCursor.StartOfBlock)
            cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor,
                                min(col, len(cursor.block().text())))
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def delete_lines(self):
        """Ctrl+Shift+K — delete the current line or selected lines."""
        cursor = self.textCursor()
        first, last = self._line_range(cursor)
        doc = self.document()
        start = first.position()
        if last.next().isValid():
            end = last.next().position()  # swallow the trailing newline
        else:
            end = self._doc_end()
            if first.previous().isValid():
                start = first.position() - 1  # swallow preceding newline
            # else: single-line document — clear it all
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _cut_line_range(self, first, cut_end):
        """Cut [first.position, cut_end) as a fragment (keeps formatting)."""
        sel = QTextCursor(self.document())
        sel.setPosition(first.position())
        sel.setPosition(cut_end, QTextCursor.KeepAnchor)
        frag = sel.selection()
        sel.removeSelectedText()
        return frag

    def _reselect_lines(self, start_number, count, col=0,
                          keep_selection=False):
        doc = self.document()
        first = doc.findBlockByNumber(start_number)
        last = doc.findBlockByNumber(start_number + count - 1)
        cursor = self.textCursor()
        if keep_selection or count > 1:
            cursor.setPosition(first.position())
            cursor.setPosition(last.position() + len(last.text()),
                               QTextCursor.KeepAnchor)
        else:
            cursor.setPosition(first.position()
                               + min(col, len(first.text())))
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def move_lines(self, step):
        """Alt+Up/Down — move the current line or selected lines."""
        cursor = self.textCursor()
        had_selection = cursor.hasSelection()
        col = cursor.positionInBlock()
        first, last = self._line_range(cursor)
        doc = self.document()
        count = self._block_count(first, last)
        first_number = first.blockNumber()
        last_has_next = last.next().isValid()
        cursor.beginEditBlock()
        if step < 0:
            prev = first.previous()
            if not prev.isValid():
                cursor.endEditBlock()
                return
            prev_number = prev.blockNumber()
            if last_has_next:
                frag = self._cut_line_range(first, last.next().position())
            else:
                # Last line has no trailing newline: re-add the separator
                # after the moved text so it doesn't merge with `prev`.
                frag = self._cut_line_range(first, self._doc_end())
                # Cutting to the document end empties (but keeps) the final
                # block; drop that leftover so no blank line trails.
                if doc.blockCount() > 1 and not doc.lastBlock().text():
                    tail = QTextCursor(doc)
                    tail.movePosition(QTextCursor.End)
                    tail.deletePreviousChar()
            cursor.setPosition(prev.position())
            cursor.insertFragment(frag)
            if not last_has_next:
                cursor.insertBlock()
            new_first = prev_number
        else:
            nxt = last.next()
            if not nxt.isValid():
                cursor.endEditBlock()
                return
            nxt_has_next = nxt.next().isValid()
            removed = nxt.position() - first.position()
            after = nxt.next().position() if nxt_has_next else -1
            frag = self._cut_line_range(first, nxt.position())
            if nxt_has_next:
                # Account for the removed range shifting later positions.
                cursor.setPosition(after - removed)
                cursor.insertFragment(frag)
            else:
                # `nxt` is the last line: open a fresh line at the end,
                # drop the fragment's trailing newline, close the gap.
                cursor.setPosition(self._doc_end())
                cursor.insertBlock()
                cursor.insertFragment(frag)
                cursor.deletePreviousChar()
            new_first = first_number + 1
        cursor.endEditBlock()
        if had_selection or count > 1:
            self._reselect_lines(new_first, count, keep_selection=True)
        else:
            self._reselect_lines(new_first, count, col)

    def join_with_next(self):
        """Ctrl+J — join the current line with the one below it."""
        cursor = self.textCursor()
        block = cursor.block()
        nxt = block.next()
        if not nxt.isValid():
            return
        end_pos = block.position() + len(block.text())
        lead = len(nxt.text()) - len(nxt.text().lstrip(" \t"))
        cursor.beginEditBlock()
        cursor.setPosition(end_pos)
        cursor.setPosition(nxt.position() + lead, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        doc = self.document()
        prev_ch = doc.characterAt(cursor.position() - 1) \
            if cursor.position() > 0 else " "
        next_ch = doc.characterAt(cursor.position()) \
            if cursor.position() < self._doc_end() else ""
        if next_ch not in ("", " ", "\t", "\u2029") and \
                prev_ch not in ("", " ", "\t", "\u2029"):
            cursor.insertText(" ")
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # ------------------------------------------------------------- search UI

    def set_search_results(self, matches, active_index=-1):
        """Render search matches (and the active one) as extra selections."""
        from PySide6.QtWidgets import QTextEdit
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
