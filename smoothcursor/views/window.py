"""MainWindow: file operations, tabs, find bar, settings, status bar."""
import os
import re

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import (QColor, QFont, QKeySequence,
                           QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)
from smoothcursor.editor.editor import CodeEditor
from smoothcursor.editor.rich import RichEditor
from smoothcursor.views.search import FindBar
from smoothcursor.core.settings import DEFAULTS, Settings, SettingsDialog
from smoothcursor.views.tabs import EditorTabs
from smoothcursor.core.theme import (THEMES, available_themes, build_qss,
                                       load_custom_themes)
from smoothcursor.views.help import AboutDialog, ShortcutsDialog
from smoothcursor.views.welcome import WelcomePage
from smoothcursor.documents.docx_io import (
    docx_available,
    docx_to_document,
    docx_to_text,
    is_docx,
    looks_like_docx,
    text_to_docx,
)
from smoothcursor.documents.html_io import (
    html_to_document,
    is_html,
    looks_like_html,
    text_to_html,
)
from smoothcursor.documents.odt_io import (
    is_odt,
    looks_like_odt,
    odt_available,
    odt_to_document,
    text_to_odt,
)
from smoothcursor.documents.pdf_io import export_qdoc_to_pdf, is_pdf
FILE_FILTER = (
    "Supported files (*.py *.pyw *.json *.txt *.docx *.odt *.html *.htm "
    "*.md);;"
    "Python (*.py *.pyw);;JSON (*.json);;Text (*.txt *.md);;"
    "Word document (*.docx);;OpenDocument (*.odt);;"
    "Web page (*.html *.htm);;All files (*)"
)
SAVE_FILTER = FILE_FILTER + ";;PDF document (*.pdf)"
OPEN_FILTER = FILE_FILTER
# Extensions that open as rich (WYSIWYG) tabs with real tables.
RICH_EXTENSIONS = (".docx", ".odt", ".html", ".htm")


def is_rich_document(path):
    """True for word-processor/web formats edited as rich text."""
    low = (path or "").lower()
    return low.endswith(RICH_EXTENSIONS)


# ------------------------------------------------------- insertable content

def build_markdown_table(rows, cols, header=True):
    """Build a markdown table. Returns (text, cursor_offset) with the cursor
    parked in the first body cell (or first header cell without header)."""
    headers = [f"Header {i + 1}" for i in range(cols)]
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("-" * (len(h) + 2) for h in headers) + "|"
    body = ["|" + "|".join(["  "] * cols) + "|" for _ in range(rows)]
    if header:
        lines = [head, sep] + body
        offset = len(head) + 1 + len(sep) + 1 + len("| ")
    else:
        lines = body
        offset = len("| ")
    return "\n".join(lines), offset


def image_markdown(image_path, doc_path):
    """`![alt](target)` with a relative target when possible."""
    alt = os.path.splitext(os.path.basename(image_path))[0] or "image"
    target = image_path
    if doc_path:
        try:
            rel = os.path.relpath(image_path, os.path.dirname(
                os.path.abspath(doc_path)))
            if not rel.startswith(".."):
                target = rel
        except ValueError:
            pass
    return f"![{alt}]({target})"


TABLE_FILL_OPTIONS = [
    ("No fill", None),
    ("Yellow", "#ffff00"),
    ("Green", "#c6efce"),
    ("Blue", "#d6e4f0"),
    ("Gray", "#e7e6e6"),
    ("Orange", "#fce4d6"),
    ("Pink", "#ffd9e8"),
]


class TableDialog(QDialog):
    """Rows/columns/style picker for Insert > Table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Table")
        form = QFormLayout(self)
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 20)
        self.rows_spin.setValue(2)
        form.addRow("Body rows", self.rows_spin)
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 10)
        self.cols_spin.setValue(3)
        form.addRow("Columns", self.cols_spin)
        self.header_check = QCheckBox("Header row")
        self.header_check.setChecked(True)
        form.addRow("", self.header_check)
        self.header_bold_check = QCheckBox("Bold header")
        self.header_bold_check.setChecked(True)
        form.addRow("", self.header_bold_check)
        self.header_check.toggled.connect(self.header_bold_check.setEnabled)
        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 4)
        self.border_spin.setValue(1)
        self.border_spin.setSuffix(" px")
        self.border_spin.setToolTip("Table grid border width (0 = no border)")
        form.addRow("Border", self.border_spin)
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 12)
        self.padding_spin.setValue(4)
        self.padding_spin.setToolTip("Space inside each cell")
        form.addRow("Cell padding", self.padding_spin)
        from PySide6.QtWidgets import QComboBox
        self.fill_combo = QComboBox()
        for name, _hex in TABLE_FILL_OPTIONS:
            self.fill_combo.addItem(name)
        self.fill_combo.setToolTip("Header row background fill")
        form.addRow("Header fill", self.fill_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def rows(self):
        return self.rows_spin.value()

    def cols(self):
        return self.cols_spin.value()

    def header(self):
        return self.header_check.isChecked()

    def header_bold(self):
        return self.header_bold_check.isChecked() and self.header()

    def border(self):
        return self.border_spin.value()

    def padding(self):
        return self.padding_spin.value()

    def header_fill(self):
        idx = self.fill_combo.currentIndex()
        if 0 <= idx < len(TABLE_FILL_OPTIONS):
            return TABLE_FILL_OPTIONS[idx][1]
        return None


class TablePropertiesDialog(QDialog):
    """Restyle the table under the cursor (border/padding/header)."""

    def __init__(self, parent=None, style=None):
        super().__init__(parent)
        self.setWindowTitle("Table Properties")
        style = style or {}
        form = QFormLayout(self)
        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 4)
        self.border_spin.setValue(int(style.get("border", 1)))
        self.border_spin.setSuffix(" px")
        form.addRow("Border", self.border_spin)
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 12)
        try:
            pad = int(float(style.get("padding", 4)))
        except (TypeError, ValueError):
            pad = 4
        self.padding_spin.setValue(max(0, min(12, pad)))
        form.addRow("Cell padding", self.padding_spin)
        self.header_bold_check = QCheckBox("Bold header row")
        self.header_bold_check.setChecked(bool(style.get("header_bold", True)))
        form.addRow("", self.header_bold_check)
        from PySide6.QtWidgets import QComboBox
        self.fill_combo = QComboBox()
        current_fill = (style.get("header_fill") or None)
        if isinstance(current_fill, str):
            current_fill = current_fill.lower()
        sel = 0
        for i, (name, hexv) in enumerate(TABLE_FILL_OPTIONS):
            self.fill_combo.addItem(name)
            if hexv is not None and current_fill is not None and \
                    hexv.lower() == current_fill:
                sel = i
        self.fill_combo.setCurrentIndex(sel)
        form.addRow("Header fill", self.fill_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def border(self):
        return self.border_spin.value()

    def padding(self):
        return self.padding_spin.value()

    def header_bold(self):
        return self.header_bold_check.isChecked()

    def header_fill(self):
        idx = self.fill_combo.currentIndex()
        if 0 <= idx < len(TABLE_FILL_OPTIONS):
            return TABLE_FILL_OPTIONS[idx][1]
        return None


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        try:
            load_custom_themes()
        except Exception:
            pass
        self.theme_name = settings.get("theme")
        if self.theme_name not in THEMES:
            self.theme_name = "dark"
        self.theme = THEMES[self.theme_name]
        self._untitled_counter = 0

        self.setWindowTitle("SmoothCursor")
        self.resize(1080, 720)
        try:
            geo = settings.value("session/geometry")
            if isinstance(geo, QByteArray) and not geo.isEmpty():
                self.restoreGeometry(geo)
        except Exception:
            pass

        # --- central layout: tabs + find bar + placeholder page ---------
        self.tabs = EditorTabs()
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.find_bar = FindBar()

        self.welcome = WelcomePage()
        self.welcome.new_requested.connect(self.new_file)
        self.welcome.open_requested.connect(self.open_file)
        self.welcome.settings_requested.connect(self.open_settings)
        self.welcome.open_path_requested.connect(self._open_recent)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.tabs)
        self.stack.setCurrentWidget(self.welcome)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.find_bar)
        self.setCentralWidget(central)

        # --- status bar ---------------------------------------------------
        self.position_label = QLabel("")
        self.statusBar().addPermanentWidget(self.position_label)
        self.statusBar().showMessage("Ready")

        self._build_menu_bar()

        if not self._restore_session():
            self._refresh_ui()  # no session: land on the startup screen

    # ------------------------------------------------------------ menu bar

    @staticmethod
    def _menu_action(menu, label, shortcuts, tip, cb, checkable=False):
        """Add an action; `shortcuts` is one key sequence or a list."""
        act = menu.addAction(label)
        if shortcuts:
            if isinstance(shortcuts, str):
                shortcuts = [shortcuts]
            act.setShortcuts([QKeySequence(s) for s in shortcuts])
        act.setToolTip(tip)
        act.setCheckable(checkable)
        act.triggered.connect(cb)
        return act

    def _edit_op(self, name):
        """Undo/redo/cut/copy/paste/select-all on the current tab."""
        editor = self.current_editor()
        if editor is None:
            return
        try:
            getattr(editor, name)()
        except Exception:
            pass

    def _toggle_wrap(self):
        self.settings.set("word_wrap",
                          not bool(self.settings.get("word_wrap")))
        self.apply_settings()

    def _set_line_numbers(self, mode):
        self.settings.set("line_numbers", mode)
        self.apply_settings()

    def _set_theme(self, name):
        self.settings.set("theme", name)
        self.apply_settings()

    def _build_menu_bar(self):
        from PySide6.QtGui import QActionGroup
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        self._menu_action(file_menu, "&New", "Ctrl+N",
                          "New file", self.new_file)
        self._menu_action(file_menu, "&Open", "Ctrl+O",
                          "Open file", self.open_file)
        self.recent_menu = file_menu.addMenu("Open R&ecent")
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._menu_action(file_menu, "&Save", "Ctrl+S",
                          "Save", self.save_current)
        self._menu_action(file_menu, "Save &As", "Ctrl+Shift+S",
                          "Save as", self.save_current_as)
        self._menu_action(file_menu, "Export to &PDF…", None,
                          "Export the current tab to PDF",
                          self.export_pdf)
        self._menu_action(file_menu, "&Print…", "Ctrl+P",
                          "Print the current tab", self.print_current)
        file_menu.addSeparator()
        self._menu_action(file_menu, "&Close Tab", "Ctrl+W",
                          "Close the current tab",
                          lambda: self.close_tab(self.tabs.currentIndex()))
        self._menu_action(file_menu, "&Quit", "Ctrl+Q",
                          "Quit", self.close)

        edit_menu = menubar.addMenu("&Edit")
        self._menu_action(edit_menu, "&Undo", "Ctrl+Z",
                          "Undo", lambda: self._edit_op("undo"))
        self._menu_action(edit_menu, "&Redo", "Ctrl+Y",
                          "Redo", lambda: self._edit_op("redo"))
        edit_menu.addSeparator()
        self._menu_action(edit_menu, "Cu&t", "Ctrl+X",
                          "Cut", lambda: self._edit_op("cut"))
        self._menu_action(edit_menu, "&Copy", "Ctrl+C",
                          "Copy", lambda: self._edit_op("copy"))
        self._menu_action(edit_menu, "&Paste", "Ctrl+V",
                          "Paste", lambda: self._edit_op("paste"))
        self._menu_action(edit_menu, "Select &All", "Ctrl+A",
                          "Select all", lambda: self._edit_op("selectAll"))
        edit_menu.addSeparator()
        self._menu_action(edit_menu, "&Find", "Ctrl+F",
                          "Find", self._open_find)
        self._menu_action(edit_menu, "&Replace", "Ctrl+H",
                          "Replace", self._open_replace)
        self._menu_action(edit_menu, "Find &Next", "F3",
                          "Next match", self.find_bar.find_next)
        self._menu_action(edit_menu, "Find &Previous", "Shift+F3",
                          "Previous match", self.find_bar.find_prev)
        edit_menu.addSeparator()
        self._menu_action(edit_menu, "&Preferences…", "Ctrl+,",
                          "Settings", self.open_settings)

        view_menu = menubar.addMenu("&View")
        self._menu_action(view_menu, "Zoom &In", ["Ctrl+=", "Ctrl++"],
                          "Zoom in", lambda: self.zoom_font(1))
        self._menu_action(view_menu, "Zoom &Out", "Ctrl+-",
                          "Zoom out", lambda: self.zoom_font(-1))
        self._menu_action(view_menu, "&Reset Zoom", "Ctrl+0",
                          "Reset zoom", self.reset_zoom)
        view_menu.addSeparator()
        self.wrap_action = self._menu_action(
            view_menu, "&Word Wrap", None, "Wrap long lines",
            self._toggle_wrap, checkable=True)
        self.lnum_menu = view_menu.addMenu("&Line Numbers")
        self.lnum_group = QActionGroup(self)
        self.lnum_group.setExclusive(True)
        for label, mode in (("Off", "off"), ("Absolute", "absolute"),
                            ("Relative", "relative"), ("Hybrid", "hybrid")):
            act = self.lnum_menu.addAction(label)
            act.setCheckable(True)
            act.triggered.connect(
                lambda _checked=False, m=mode: self._set_line_numbers(m))
            self.lnum_group.addAction(act)
        self.theme_menu = view_menu.addMenu("&Theme")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        view_menu.addSeparator()
        self._menu_action(view_menu, "&Next Tab", "Ctrl+Tab",
                          "Next tab", lambda: self._cycle_tab(1))
        self._menu_action(view_menu, "&Previous Tab", "Ctrl+Shift+Tab",
                          "Previous tab", lambda: self._cycle_tab(-1))
        view_menu.aboutToShow.connect(self._sync_view_menu)

        insert_menu = menubar.addMenu("&Insert")
        self._menu_action(insert_menu, "&Table…", None,
                          "Insert a table", self._insert_table)
        self._menu_action(insert_menu, "&Format Table", None,
                          "Style the table under the cursor",
                          self._format_table)
        insert_menu.addSeparator()
        self._menu_action(insert_menu, "&Image…", None,
                          "Insert a photo", self._insert_image)
        self._menu_action(insert_menu, "Horizontal &Rule", None,
                          "Insert a divider", self._insert_rule)
        self._menu_action(insert_menu, "&Link…", None,
                          "Insert a link", self._insert_link)

        help_menu = menubar.addMenu("&Help")
        self._menu_action(help_menu, "&Keyboard Shortcuts…", None,
                          "Shortcut reference",
                          self.open_shortcuts)
        self._menu_action(help_menu, "&About SmoothCursor…", None,
                          "About this app", self.open_about)

    def _sync_view_menu(self):
        """Check the active wrap / line-number / theme entries."""
        try:
            self.wrap_action.setChecked(bool(self.settings.get("word_wrap")))
        except Exception:
            pass
        try:
            current_lnum = self.settings.get("line_numbers")
        except Exception:
            current_lnum = "absolute"
        for act in self.lnum_group.actions():
            act.setChecked(act.text().lower() == current_lnum)
        try:
            current_theme = self.settings.get("theme")
        except Exception:
            current_theme = "dark"
        names = tuple(available_themes())
        if names != getattr(self, "_theme_names", None):
            # Rebuild only when the set of themes changed (new JSON).
            for act in self.theme_group.actions():
                self.theme_group.removeAction(act)
                try:
                    act.deleteLater()
                except Exception:
                    pass
            self.theme_menu.clear()
            for name in names:
                act = self.theme_menu.addAction(name)
                act.setCheckable(True)
                act.triggered.connect(
                    lambda _checked=False, n=name: self._set_theme(n))
                self.theme_group.addAction(act)
            self._theme_names = names
        for act in self.theme_group.actions():
            act.setChecked(act.text() == current_theme)

    def open_shortcuts(self):
        ShortcutsDialog(self).exec()

    def open_about(self):
        AboutDialog(self).exec()

    def print_current(self):
        """Print the current tab via the system print dialog."""
        editor = self.current_editor()
        if editor is None:
            return
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if not dialog.exec():
            return
        try:
            editor.document().print_(printer)
        except Exception as exc:
            QMessageBox.critical(self, "Print failed", str(exc))

    def export_pdf(self):
        """Export the current tab to a PDF file (Save As flow)."""
        editor = self.current_editor()
        if editor is None:
            return
        if editor.file_path:
            base = os.path.splitext(editor.file_path)[0]
            suggested = base + ".pdf"
        else:
            name = (editor.untitled_name or "untitled").strip() or "untitled"
            if "." in os.path.basename(name):
                name = os.path.splitext(name)[0]
            suggested = os.path.join(os.path.expanduser("~"), name + ".pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Export to PDF",
                                              suggested,
                                              "PDF document (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            export_qdoc_to_pdf(editor.document(), path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage("Exported to %s" % path, 4000)

    # ------------------------------------------------------------- editors

    def current_editor(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, (CodeEditor, RichEditor)) else None

    def _editor_title(self, editor):
        name = os.path.basename(editor.file_path) if editor.file_path \
            else editor.untitled_name
        dot = "● " if editor.document().isModified() else ""
        return dot + name

    def _refresh_ui(self):
        """Sync tab titles, window title and stack page with editor state."""
        for i in range(self.tabs.count()):
            editor = self.tabs.editor_at(i)
            self.tabs.set_tab_title(i, self._editor_title(editor))
        editor = self.current_editor()
        if editor is None:
            self.setWindowTitle("SmoothCursor")
            self.welcome.set_recent(self.settings.get_recent())
            self.stack.setCurrentWidget(self.welcome)
            self.position_label.setText("")
            return
        self.stack.setCurrentWidget(self.tabs)
        name = os.path.basename(editor.file_path) if editor.file_path \
            else editor.untitled_name
        modified = " •" if editor.document().isModified() else ""
        self.setWindowTitle(f"{name}{modified} — SmoothCursor")
        cursor = editor.textCursor()
        status = (f"Ln {cursor.blockNumber() + 1}, "
                  f"Col {cursor.positionInBlock() + 1}")
        if cursor.hasSelection():
            selected = cursor.selectedText().replace("\u2029", "\n")
            status += f" · {len(selected)} selected"
        else:
            # toPlainText() is O(n): recompute only when the text changed.
            rev = editor.document().revision()
            cached = getattr(editor, "_word_cache", None)
            if cached is None or cached[0] != rev:
                words = len(editor.toPlainText().split())
                editor._word_cache = (rev, words)
            else:
                words = cached[1]
            status += f" · {words} words"
        self.position_label.setText(status)

    def _make_editor(self, file_path=None, language=None):
        if language is None:
            language = CodeEditor.language_for(file_path)
        if file_path and is_rich_document(file_path):
            editor = RichEditor(self.settings, self.theme)
            editor.setProperty("docxView", True)
        else:
            editor = CodeEditor(self.settings, self.theme, language=language)
            if file_path and is_rich_document(file_path):
                editor.setProperty("docxView", True)
        editor.file_path = file_path
        if file_path is None:
            self._untitled_counter += 1
            editor.untitled_name = f"Untitled {self._untitled_counter}"
        else:
            editor.untitled_name = ""
        editor.modified_changed.connect(self._refresh_ui)
        editor.cursorPositionChanged.connect(self._refresh_ui)
        editor.textChanged.connect(self._maybe_refresh_search)
        return editor
    def _add_editor_tab(self, editor):
        title = os.path.basename(editor.file_path) if editor.file_path \
            else editor.untitled_name
        index = self.tabs.add_editor(editor, title, editor.file_path)
        self.tabs.setCurrentIndex(index)
        editor.setFocus()
        self._refresh_ui()
        self._save_session()

    # -------------------------------------------------------- recent files

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        recent = self.settings.get_recent()
        if not recent:
            act = self.recent_menu.addAction("No recent files")
            act.setEnabled(False)
            return
        for path in recent:
            act = self.recent_menu.addAction(os.path.basename(path))
            act.setToolTip(path)
            act.triggered.connect(
                lambda _checked=False, p=path: self._open_recent(p))

    def _open_recent(self, path):
        if not os.path.exists(path):
            self.settings.drop_recent(path)
            self.statusBar().showMessage(f"Not found: {path}", 4000)
            return
        self.open_path(path)

    # ------------------------------------------------------------ insert

    def _insert_block_snippet(self, editor, text, offset):
        """Insert `text` on its own line; open a new line if mid-text."""
        cursor = editor.textCursor()
        if cursor.block().text().strip():
            cursor.movePosition(QTextCursor.EndOfBlock)
            editor.setTextCursor(cursor)
            editor.insert_snippet("\n" + text, offset + 1)
        else:
            cursor.movePosition(QTextCursor.StartOfBlock)
            editor.setTextCursor(cursor)
            editor.insert_snippet(text, offset)

    def _insert_table(self):
        editor = self.current_editor()
        if editor is None:
            return
        dialog = TableDialog(self)
        if not dialog.exec():
            return
        if isinstance(editor, RichEditor):
            # Real editable Word-style table (no markdown pipes).
            editor.insert_real_table(
                dialog.rows(), dialog.cols(), dialog.header(),
                border=dialog.border(), padding=dialog.padding(),
                header_fill=dialog.header_fill(),
                header_bold=dialog.header_bold())
            return
        text, offset = build_markdown_table(dialog.rows(), dialog.cols(),
                                            dialog.header())
        self._insert_block_snippet(editor, text, offset)

    def _format_table(self):
        editor = self.current_editor()
        if editor is None:
            return
        if not editor.format_markdown_table():
            self.statusBar().showMessage("No table under the cursor", 3000)

    def _insert_image(self):
        editor = self.current_editor()
        if editor is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Insert Image", os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;"
            "All files (*)")
        if not path:
            return
        md = image_markdown(path, editor.file_path)
        self._insert_block_snippet(editor, md, len(md))

    def _insert_rule(self):
        editor = self.current_editor()
        if editor is None:
            return
        if not editor.document().toPlainText().strip():
            editor.insert_snippet("---\n", 4)
            return
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.EndOfBlock)
        editor.setTextCursor(cursor)
        editor.insert_snippet("\n\n---\n", 6)

    def _insert_link(self):
        editor = self.current_editor()
        if editor is None:
            return
        url, ok = QInputDialog.getText(self, "Insert Link", "URL:")
        if not ok or not url.strip():
            return
        url = url.strip()
        if editor.textCursor().hasSelection():
            start = editor.textCursor().selectionStart()
            selected = editor.textCursor().selectedText().replace(
                "\u2029", "\n")
            editor.insert_snippet(f"[{selected}]({url})",
                                  len(selected) + len(url) + 4)
        else:
            editor.insert_snippet(f"[text]({url})", 1)
            cursor = editor.textCursor()
            cursor.setPosition(cursor.position() + 4,
                               QTextCursor.KeepAnchor)
            editor.setTextCursor(cursor)

    # --------------------------------------------------------- file actions

    def new_file(self):
        self._add_editor_tab(self._make_new_document_editor())

    def _make_new_document_editor(self):
        """A fresh document defaults to a Word (.docx) file with the
        floating format toolbar ready (real tables)."""
        self._untitled_counter += 1
        editor = RichEditor(self.settings, self.theme)
        editor.file_path = None
        editor.untitled_name = f"Untitled {self._untitled_counter}.docx"
        editor.setProperty("docxView", True)
        editor.modified_changed.connect(self._refresh_ui)
        editor.cursorPositionChanged.connect(self._refresh_ui)
        editor.textChanged.connect(self._maybe_refresh_search)
        return editor

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open file",
                                              os.path.expanduser("~"),
                                              OPEN_FILTER)
        if not path:
            return
        self.open_path(path)

    def open_path(self, path):
        """Open `path` in a new tab (or focus it). Returns True on success."""
        # Reuse a tab that already has this file open.
        for i in range(self.tabs.count()):
            if self.tabs.editor_at(i).file_path == path:
                self.tabs.setCurrentIndex(i)
                return True
        editor = self._make_editor(file_path=path)
        try:
            self._read_file_into(editor, path)
        except (OSError, RuntimeError, Exception) as exc:
            QMessageBox.critical(self, "Open failed", f"{path}\n\n{exc}")
            editor.deleteLater()
            return False
        editor.document().setModified(False)
        self._add_editor_tab(editor)
        self.settings.push_recent(path)
        return True

    def _read_file_into(self, editor, path):
        """Load file text into `editor`; raises on failure."""
        low = (path or "").lower()
        if is_pdf(path):
            raise RuntimeError(
                "PDF files cannot be edited — open the source document "
                "instead. (Use Save As → PDF to export.)")
        if is_docx(path) or is_odt(path) or is_html(path) or \
                looks_like_docx(path) or looks_like_odt(path) or \
                looks_like_html(path):
            self._load_rich_document(editor, path)
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                editor.setPlainText(f.read())

    def _load_rich_document(self, editor, path):
        """Load a rich document (.docx/.odt/.html) with formatting.

        Raises on failure (missing optional dependency included).
        """
        low = (path or "").lower()
        kind = "document"
        if is_odt(path) or (not is_docx(path) and not is_html(path)
                            and looks_like_odt(path)):
            kind = "odt"
        elif is_html(path) or (not is_docx(path) and looks_like_html(path)):
            kind = "html"
        elif is_docx(path) or looks_like_docx(path):
            kind = "docx"
        try:
            if kind == "odt":
                if not odt_available():
                    raise RuntimeError(
                        "Opening .odt requires the odfpy package.\n"
                        "Install it with:  pip install odfpy")
                odt_to_document(path, editor.document())
            elif kind == "html":
                html_to_document(path, editor.document())
            else:
                if not docx_available():
                    raise RuntimeError(
                        "Opening .docx requires the python-docx package.\n"
                        "Install it with:  pip install python-docx")
                docx_to_document(path, editor.document())
        except (OSError, RuntimeError):
            raise
        except Exception as exc:
            raise RuntimeError(f"Could not read document: {exc}") from exc
        editor.setProperty("docxView", True)
        editor.set_rich_mode(True)

    def _write_editor(self, editor, path: str) -> bool:
        # Collapse accidents like "Untitled 1.docx.docx" from older builds.
        path = self.normalize_save_path(path)
        # Detach the floating toolbar during export (rich tabs only —
        # toggling a plain tab would attach one by surprise).
        rich_tab = isinstance(editor, RichEditor)
        if rich_tab:
            editor.set_rich_mode(False)
        try:
            if is_pdf(path):
                export_qdoc_to_pdf(editor.document(), path)
            elif is_docx(path):
                if not docx_available():
                    raise RuntimeError(
                        "Saving .docx requires the python-docx package.\n"
                        "Install it with:  pip install python-docx")
                text_to_docx(path, editor.toPlainText(),
                             document=editor.document())
            elif is_odt(path):
                if not odt_available():
                    raise RuntimeError(
                        "Saving .odt requires the odfpy package.\n"
                        "Install it with:  pip install odfpy")
                text_to_odt(path, editor.toPlainText(),
                            document=editor.document())
            elif is_html(path):
                text_to_html(path, editor.toPlainText(),
                             document=editor.document())
            elif looks_like_docx(path) or looks_like_odt(path):
                raise RuntimeError(
                    "This file is a Word/OpenDocument file but saving "
                    "would corrupt it (missing .docx/.odt support). "
                    "Choose a matching filename or install "
                    "python-docx/odfpy.")
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(editor.toPlainText())
        except (OSError, RuntimeError, Exception) as exc:
            QMessageBox.critical(self, "Save failed", f"{path}\n\n{exc}")
            return False
        finally:
            if rich_tab:
                try:
                    editor.set_rich_mode(True)
                except Exception:
                    pass
        editor.file_path = path
        editor.untitled_name = ""
        editor.document().setModified(False)
        self.settings.push_recent(path)
        self._save_session()
        return True

    def save_current(self) -> bool:
        editor = self.current_editor()
        if editor is None:
            return False
        if not editor.file_path:
            return self.save_current_as()
        return self._write_editor(editor, editor.file_path)

    @staticmethod
    def suggested_save_path(editor) -> str:
        """Default path for Save As without ever doubling '.docx'."""
        if editor.file_path:
            return editor.file_path
        base = (editor.untitled_name or "untitled").strip() or "untitled"
        # untitled_name already carries ".docx" for Word docs — don't
        # append a second extension ("Untitled 1.docx.docx").
        if base.lower().endswith(".docx"):
            filename = base
        else:
            filename = base + ".docx"
        return os.path.join(os.path.expanduser("~"), filename)

    @staticmethod
    def normalize_save_path(path: str) -> str:
        """Collapse accidents like 'Untitled 1.docx.docx'."""
        while path.lower().endswith(".docx.docx"):
            path = path[:-5]
        return path

    def save_current_as(self) -> bool:
        editor = self.current_editor()
        if editor is None:
            return False
        suggested = self.suggested_save_path(editor)
        path, _ = QFileDialog.getSaveFileName(self, "Save as", suggested,
                                              SAVE_FILTER)
        if not path:
            return False
        return self._write_editor(editor, path)

    def _maybe_save_editor(self, editor) -> bool:
        """True when it is OK to discard/close. False = user cancelled."""
        if not editor.document().isModified():
            return True
        name = os.path.basename(editor.file_path) if editor.file_path \
            else editor.untitled_name
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"“{name}” has unsaved changes.")
        save = box.addButton("Save", QMessageBox.AcceptRole)
        discard = box.addButton("Don't Save", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return self._write_editor_for(editor)
        return clicked is discard

    def _write_editor_for(self, editor):
        """Save a specific (not necessarily current) editor."""
        prev = self.tabs.currentWidget()
        result = True
        if not editor.file_path:
            self.tabs.setCurrentWidget(editor)
            result = self.save_current_as()
        else:
            result = self._write_editor(editor, editor.file_path)
        if prev is not None:
            self.tabs.setCurrentWidget(prev)
        return result

    # --------------------------------------------------------------- tabs

    def close_tab(self, index):
        if index < 0 or index >= self.tabs.count():
            return
        editor = self.tabs.editor_at(index)
        if not self._maybe_save_editor(editor):
            return
        self.tabs.removeTab(index)
        editor.deleteLater()
        self._save_session()

    def _cycle_tab(self, step):
        count = self.tabs.count()
        if count:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % count)

    def _on_tab_changed(self, index):
        if index >= 0:
            editor = self.tabs.editor_at(index)
            if editor:
                editor.setFocus()
        self._refresh_ui()
        self._save_session()  # persist the tab left behind + cursor spots

    # --------------------------------------------------------------- find

    def _open_find(self):
        if self.current_editor():
            self.find_bar.open_for(self.current_editor())

    def _open_replace(self):
        if self.current_editor():
            self.find_bar.open_for(self.current_editor(), replace=True)

    def zoom_font(self, steps):
        """Ctrl+=/-/wheel: bump the shared font size and refresh all tabs."""
        size = max(8, min(40, int(self.settings.get("font_size")) + steps))
        if size != self.settings.get("font_size"):
            self.settings.set("font_size", size)
            self.apply_settings()

    def reset_zoom(self):
        self.settings.set("font_size", DEFAULTS["font_size"])
        self.apply_settings()

    def _maybe_refresh_search(self):
        if self.find_bar.isVisible():
            self.find_bar._debounce.start()

    # ----------------------------------------------------------- settings

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.apply_settings()

    def apply_settings(self):
        """Push current settings into the window, all editors and the QSS."""
        theme_name = self.settings.get("theme")
        if theme_name not in THEMES:
            try:
                load_custom_themes()
            except Exception:
                pass
        if theme_name not in THEMES:
            theme_name = "dark"
        if theme_name != self.theme_name:
            self.theme_name = theme_name
            self.theme = THEMES[theme_name]
            try:
                QApplication.instance().setStyleSheet(build_qss(self.theme))
            except Exception:
                pass
        for i in range(self.tabs.count()):
            editor = self.tabs.editor_at(i)
            editor.apply_settings()
            editor.apply_colors(self.theme)
        self._refresh_ui()

    # ------------------------------------------------------------- session

    def _save_session(self):
        """Persist open tabs, cursor positions and untitled backups.

        Never raises: session saving must not interrupt editing.
        Skipped while a session is being restored (it would wipe the
        backups that have not been reopened yet).
        """
        if getattr(self, "_restoring", False):
            return
        try:
            bdir = self.settings.backup_dir()
            for name in os.listdir(bdir):
                try:
                    os.remove(os.path.join(bdir, name))
                except OSError:
                    pass
            tabs = []
            for i in range(self.tabs.count()):
                editor = self.tabs.editor_at(i)
                pos = editor.textCursor().position()
                if editor.file_path:
                    tabs.append({"kind": "file", "path": editor.file_path,
                                 "backup": "", "cursor": pos})
                    continue
                is_rich = isinstance(editor, RichEditor)
                text = editor.toPlainText()
                html = editor.toHtml() if is_rich else ""
                if not text.strip() and not html.strip() and \
                        not editor.document().isModified():
                    continue  # blank scratch tab: nothing worth keeping
                if is_rich:
                    # HTML preserves real tables + formatting.
                    backup = os.path.join(bdir, f"untitled_{i}.html")
                    with open(backup, "w", encoding="utf-8") as f:
                        f.write(editor.toHtml())
                else:
                    backup = os.path.join(bdir, f"untitled_{i}.txt")
                    with open(backup, "w", encoding="utf-8") as f:
                        f.write(text)
                tabs.append({"kind": "untitled",
                             "path": editor.untitled_name,
                             "backup": backup, "cursor": pos})
            self.settings.save_session(tabs, max(0, self.tabs.currentIndex()))
        except Exception:
            pass

    def _restore_session(self):
        """Reopen last session's tabs. Returns True if anything restored."""
        try:
            entries, active = self.settings.load_session()
        except Exception:
            return False
        if not entries:
            return False
        self._restoring = True
        try:
            restored = 0
            for entry in entries:
                try:
                    kind, path = entry.get("kind"), entry.get("path", "")
                    pos = entry.get("cursor", 0)
                    if kind == "file" and path and os.path.exists(path):
                        editor = self._make_editor(file_path=path)
                        self._read_file_into(editor, path)
                        editor.document().setModified(False)
                    elif kind == "untitled" and entry.get("backup") and \
                            os.path.exists(entry["backup"]):
                        backup_path = entry["backup"]
                        if backup_path.endswith(".html"):
                            with open(backup_path, "r",
                                      encoding="utf-8",
                                      errors="replace") as f:
                                html = f.read()
                            if path and is_rich_document(path):
                                editor = RichEditor(self.settings, self.theme)
                                editor.setProperty("docxView", True)
                            else:
                                editor = self._make_editor()
                            if path:
                                editor.untitled_name = path
                            editor.modified_changed.connect(self._refresh_ui)
                            editor.cursorPositionChanged.connect(
                                self._refresh_ui)
                            editor.textChanged.connect(
                                self._maybe_refresh_search)
                            editor.setHtml(html)
                            editor.document().setModified(True)
                        else:
                            with open(backup_path, "r",
                                      encoding="utf-8",
                                      errors="replace") as f:
                                text = f.read()
                            if path and is_rich_document(path):
                                editor = RichEditor(self.settings, self.theme)
                                editor.setProperty("docxView", True)
                                editor.modified_changed.connect(
                                    self._refresh_ui)
                                editor.cursorPositionChanged.connect(
                                    self._refresh_ui)
                                editor.textChanged.connect(
                                    self._maybe_refresh_search)
                            else:
                                editor = self._make_editor()
                            if path:
                                editor.untitled_name = path
                            editor.setPlainText(text)
                            editor.document().setModified(True)
                    else:
                        continue
                    self._add_editor_tab(editor)
                    cursor = editor.textCursor()
                    cursor.setPosition(min(pos, editor.document()
                                           .characterCount() - 1))
                    editor.setTextCursor(cursor)
                    restored += 1
                except Exception:
                    continue
            if not restored:
                return False
            self.tabs.setCurrentIndex(min(active, self.tabs.count() - 1))
            self._refresh_ui()
            return True
        finally:
            self._restoring = False

    # ------------------------------------------------------------- closing

    def closeEvent(self, event):
        for i in range(self.tabs.count()):
            if not self._maybe_save_editor(self.tabs.editor_at(i)):
                event.ignore()
                return
        try:
            self.settings.set_value("session/geometry", self.saveGeometry())
        except Exception:
            pass
        self._save_session()
        event.accept()
