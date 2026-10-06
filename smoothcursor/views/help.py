"""Help menu dialogs: keyboard-shortcut reference and About box."""

import sys

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

SHORTCUTS = [
    ("New file", "Ctrl+N"),
    ("Open file", "Ctrl+O"),
    ("Save", "Ctrl+S"),
    ("Save as", "Ctrl+Shift+S"),
    ("Export to PDF", ""),
    ("Print", "Ctrl+P"),
    ("Close tab", "Ctrl+W"),
    ("Preferences", "Ctrl+,"),
    ("Quit", "Ctrl+Q"),
    ("Find", "Ctrl+F"),
    ("Replace", "Ctrl+H"),
    ("Next / previous match", "F3 / Shift+F3"),
    ("Next / previous tab", "Ctrl+Tab / Ctrl+Shift+Tab"),
    ("Undo / Redo", "Ctrl+Z / Ctrl+Y"),
    ("Cut / Copy / Paste", "Ctrl+X / Ctrl+C / Ctrl+V"),
    ("Select all", "Ctrl+A"),
    ("Toggle comment", "Ctrl+/"),
    ("Duplicate line", "Ctrl+D"),
    ("Delete line", "Ctrl+Shift+K"),
    ("Move line up / down", "Alt+Up / Alt+Down"),
    ("Join lines", "Ctrl+J"),
    ("Indent / dedent", "Tab / Shift+Tab"),
    ("Zoom in / out", "Ctrl+= / Ctrl+- (Ctrl+wheel)"),
    ("Reset zoom", "Ctrl+0"),
]


class ShortcutsDialog(QDialog):
    """Read-only table of every keyboard shortcut."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(420, 480)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(len(SHORTCUTS), 2)
        self.table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        for row, (action, keys) in enumerate(SHORTCUTS):
            action_item = QTableWidgetItem(action)
            action_item.setFlags(action_item.flags() & ~action_item.flags()
                                 .ItemIsEditable)
            keys_item = QTableWidgetItem(keys)
            keys_item.setFlags(keys_item.flags() & ~keys_item.flags()
                               .ItemIsEditable)
            self.table.setItem(row, 0, action_item)
            self.table.setItem(row, 1, keys_item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class AboutDialog(QDialog):
    """About box: name, version, stack, credits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from smoothcursor import __version__
        self.setWindowTitle("About SmoothCursor")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        title = QLabel("SmoothCursor")
        title.setObjectName("welcomeTitle")
        lay.addWidget(title)
        self.version_label = QLabel("Version %s" % __version__)
        self.version_label.setObjectName("dimLabel")
        lay.addWidget(self.version_label)
        lay.addWidget(QLabel(
            "A lightweight Python code editor with Word-style smooth "
            "caret, real tables, and rich (.docx/.odt/.html) documents."))
        try:
            from PySide6.QtCore import qVersion
            qt_ver = qVersion()
        except Exception:
            qt_ver = "unknown"
        self.stack_label = QLabel(
            "Built with Python %s and PySide6 (Qt %s)." % (
                "%d.%d.%d" % sys.version_info[:3], qt_ver))
        self.stack_label.setObjectName("dimLabel")
        self.stack_label.setWordWrap(True)
        lay.addWidget(self.stack_label)
        lay.addWidget(QLabel("Spellcheck uses the system hunspell "
                             "dictionaries when present."))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
