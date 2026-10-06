"""WelcomePage: startup screen with quick actions and recent files."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)


class WelcomePage(QWidget):
    """Startup screen shown when no tab is open.

    Emits `new_requested` / `open_requested` for the action buttons and
    `open_path_requested` when a recent file is activated.
    """

    new_requested = Signal()
    open_requested = Signal()
    settings_requested = Signal()
    open_path_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        card = QWidget()
        card.setMaximumWidth(560)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        title = QLabel("SmoothCursor")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        tag = QLabel("A native Python editor with a gliding caret")
        tag.setObjectName("dimLabel")
        tag.setAlignment(Qt.AlignCenter)
        lay.addWidget(tag)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.new_button = QPushButton("New File")
        self.new_button.setDefault(True)
        self.new_button.setToolTip("New file (Ctrl+N)")
        self.new_button.clicked.connect(self.new_requested)
        self.open_button = QPushButton("Open File…")
        self.open_button.setToolTip("Open file (Ctrl+O)")
        self.open_button.clicked.connect(self.open_requested)
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.settings_requested)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.settings_button)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        recent_header = QLabel("RECENT")
        recent_header.setObjectName("welcomeSection")
        lay.addWidget(recent_header)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("recentList")
        self.recent_list.setMaximumHeight(168)
        self.recent_list.setFocusPolicy(Qt.NoFocus)
        self.recent_list.itemActivated.connect(self._on_recent_activated)
        lay.addWidget(self.recent_list)

        cheats = QLabel(
            "Ctrl+N new · Ctrl+O open · Ctrl+F find · Ctrl+H replace · "
            "Ctrl+/ comment · Ctrl+D duplicate · Alt+↑/↓ move line · "
            "Ctrl+= zoom")
        cheats.setObjectName("dimLabel")
        cheats.setWordWrap(True)
        cheats.setAlignment(Qt.AlignCenter)
        lay.addWidget(cheats)

        outer.addWidget(card, alignment=Qt.AlignHCenter)
        outer.addStretch(2)

    # ------------------------------------------------------------------ API

    def set_recent(self, files):
        """Refresh the recent-files list (full paths)."""
        self.recent_list.clear()
        for path in files:
            item = QListWidgetItem(os.path.basename(path) or path)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.recent_list.addItem(item)
        if not files:
            item = QListWidgetItem("No recent files yet — open something!")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setData(Qt.UserRole, None)
            self.recent_list.addItem(item)

    # --------------------------------------------------------------- events

    def _on_recent_activated(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self.open_path_requested.emit(path)
