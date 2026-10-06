#!/usr/bin/env python3
"""SmoothCursor — a native Python code editor with Word-style smooth caret."""

import sys

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from smoothcursor.core.settings import Settings
from smoothcursor.core.theme import THEMES, build_qss, load_custom_themes
from smoothcursor.views.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SmoothCursor")
    app.setOrganizationName("smoothcursor")

    settings = Settings()
    try:
        load_custom_themes()
    except Exception:
        pass
    theme = THEMES.get(settings.get("theme"), THEMES["dark"])
    app.setStyleSheet(build_qss(theme))

    # Consistent UI font regardless of desktop environment.
    ui_font = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    ui_font.setPointSize(10)
    app.setFont(ui_font)

    window = MainWindow(settings)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
