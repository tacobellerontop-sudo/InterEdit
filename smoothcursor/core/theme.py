"""Color themes and application-wide styling for SmoothCursor.

Built-in themes live in THEMES ("dark"/"light"). Users can drop extra
`*.json` files into the themes folder (see themes_dir()) — each file is
one theme named after the file, e.g. `solarized.json` → "solarized".
Keys are the same color names as the built-ins; missing keys fall back
to "dark" so a JSON file only needs the colors it changes.
"""

import json
import os
import re

from PySide6.QtGui import QColor

THEMES = {
    "dark": {
        # Chrome
        "window_bg": "#1a1c20",
        "panel": "#20232a",
        "panel2": "#262a32",
        "border": "#31363f",
        "text": "#dde1e7",
        "text_dim": "#8a919c",
        "accent": "#4fc1ff",
        "accent_text": "#0d1117",
        "danger": "#f14c4c",
        # Editor surface
        "editor_bg": "#1e2127",
        "editor_text": "#dcdfe4",
        "gutter_bg": "#1e2127",
        "gutter_text": "#4d535d",
        "gutter_text_active": "#c9ced6",
        "current_line": "#282c34",
        "selection": "#2d4f6b",
        "search_match": "#42381f",
        "search_match_active": "#6b5a22",
        # Syntax (VS Code Dark+ inspired)
        "syn_keyword": "#c586c0",
        "syn_constant": "#569cd6",
        "syn_string": "#ce9178",
        "syn_number": "#b5cea8",
        "syn_comment": "#6a9955",
        "syn_funcdef": "#dcdcaa",
        "syn_classdef": "#4ec9b0",
        "syn_builtin": "#dcdcaa",
        "syn_decorator": "#dcdcaa",
        "syn_operator": "#c9ccd1",
        "syn_self": "#569cd6",
    },
    "light": {
        "window_bg": "#eef0f3",
        "panel": "#f6f7f9",
        "panel2": "#eceef1",
        "border": "#d3d7dd",
        "text": "#24292f",
        "text_dim": "#6e7681",
        "accent": "#0a66d0",
        "accent_text": "#ffffff",
        "danger": "#cf222e",
        "editor_bg": "#ffffff",
        "editor_text": "#24292f",
        "gutter_bg": "#ffffff",
        "gutter_text": "#a0a7b0",
        "gutter_text_active": "#4a5058",
        "current_line": "#f2f5f9",
        "selection": "#b4d5fe",
        "search_match": "#fff0b0",
        "search_match_active": "#ffd54f",
        # Syntax (VS Code Light+ inspired)
        "syn_keyword": "#af00db",
        "syn_constant": "#0000ff",
        "syn_string": "#a31515",
        "syn_number": "#098658",
        "syn_comment": "#008000",
        "syn_funcdef": "#795e26",
        "syn_classdef": "#267f99",
        "syn_builtin": "#795e26",
        "syn_decorator": "#795e26",
        "syn_operator": "#444a52",
        "syn_self": "#0000ff",
    },
}


def qcolor(theme: dict, key: str) -> QColor:
    return QColor(theme[key])


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

BUILTIN_THEME_NAMES = ("dark", "light")


def themes_dir():
    """Folder holding user `*.json` themes (created on demand)."""
    try:
        from PySide6.QtCore import QStandardPaths
        loc = QStandardPaths.writableLocation(
            QStandardPaths.AppDataLocation)
    except Exception:
        loc = ""
    if not loc:
        loc = os.path.expanduser("~/.local/share/smoothcursor")
    path = os.path.join(loc, "themes")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def available_themes():
    """Built-ins first, then custom themes alphabetically."""
    customs = sorted(n for n in THEMES if n not in BUILTIN_THEME_NAMES)
    return [n for n in BUILTIN_THEME_NAMES if n in THEMES] + customs


def _valid_theme_dict(data):
    if not isinstance(data, dict):
        return None
    base = dict(THEMES["dark"])
    changed = False
    for key, value in data.items():
        if key.startswith("$") or key.startswith("#") or key.startswith("_"):
            continue  # comments / meta like "$extends"
        if key not in base:
            continue  # unknown key — ignore to stay forward compatible
        if isinstance(value, str) and _HEX_COLOR.match(value.strip()):
            base[key] = value.strip().lower()
            changed = True
    return base if changed else None


def load_custom_themes(directory=None):
    """Load `*.json` themes into THEMES. Returns (loaded, errors).

    `loaded` is a sorted list of theme names; `errors` maps filename →
    message for files that could not be parsed. Built-in names may be
    overridden by a same-named JSON file.
    """
    directory = directory or themes_dir()
    loaded, errors = [], {}
    try:
        files = sorted(f for f in os.listdir(directory)
                       if f.lower().endswith(".json"))
    except OSError:
        return loaded, errors
    for fname in files:
        name = os.path.splitext(fname)[0].strip()
        if not name:
            continue
        fpath = os.path.join(directory, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            errors[fname] = f"Invalid JSON: {exc}"
            continue
        # Optional "$extends": start from that theme instead of dark.
        base_name = None
        if isinstance(data, dict):
            base_name = data.get("$extends")
        if isinstance(base_name, str) and base_name in THEMES:
            base = dict(THEMES[base_name])
        else:
            base = dict(THEMES["dark"])
        merged = dict(base)
        changed = False
        if isinstance(data, dict):
            for key, value in data.items():
                if key.startswith("$"):
                    continue
                if key not in merged:
                    continue
                if isinstance(value, str) and \
                        _HEX_COLOR.match(value.strip()):
                    merged[key] = value.strip().lower()
                    changed = True
        if not changed:
            errors[fname] = "No valid color keys (expected \"#rrggbb\")"
            continue
        THEMES[name] = merged
        loaded.append(name)
    return sorted(loaded), errors


def write_example_theme(directory=None):
    """Write an example JSON theme; returns its path (or None)."""
    directory = directory or themes_dir()
    example = dict(THEMES["dark"])
    example["accent"] = "#ff9e00"
    example["editor_bg"] = "#1a1b26"
    payload = {"$extends": "dark"}
    payload.update({k: example[k] for k in sorted(example)})
    dest = os.path.join(directory, "example-custom.json")
    try:
        if not os.path.exists(dest):
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.write("\n")
        return dest
    except OSError:
        return None


def build_qss(t: dict) -> str:
    """Global stylesheet covering the app chrome (not the text editor itself,
    which is styled through palettes for reliable text rendering)."""
    return f"""
    QMainWindow, QDialog, QStackedWidget {{
        background: {t['window_bg']};
    }}
    QPlainTextEdit {{
        background: {t['editor_bg']};
        color: {t['editor_text']};
        selection-background-color: {t['selection']};
        selection-color: {t['editor_text']};
        border: none;
    }}
    QPlainTextEdit[docxView="true"] {{
        color: #ffffff;
    }}
    QFrame#formatToolbar {{
        background: {t['panel2']};
        border: 1px solid {t['border']};
        border-radius: 7px;
    }}
    QFrame#formatToolbar QToolButton {{
        background: transparent;
        color: {t['text']};
        border: none;
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 12px;
        min-width: 18px;
        max-height: 20px;
    }}
    QFrame#formatToolbar QToolButton:hover {{
        background: {t['border']};
    }}
    QFrame#formatToolbar QToolButton:checked {{
        background: {t['accent']};
        color: {t['accent_text']};
    }}
    QFrame#formatToolbar QComboBox {{
        background: transparent;
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 4px;
        padding: 1px 4px;
        font-size: 11px;
        min-height: 18px;
    }}
    QFrame#formatToolbar QComboBox:hover {{
        border-color: {t['text_dim']};
    }}
    QFrame#formatToolbar QComboBox QAbstractItemView {{
        background: {t['panel']};
        color: {t['text']};
        border: 1px solid {t['border']};
        selection-background-color: {t['selection']};
    }}
    QFrame#formatToolbar QMenu {{
        background: {t['panel']};
        border: 1px solid {t['border']};
    }}
    QWidget {{
        color: {t['text']};
        font-size: 13px;
    }}
    QToolBar {{
        background: {t['panel']};
        border: none;
        border-bottom: 1px solid {t['border']};
        padding: 3px 6px;
        spacing: 4px;
    }}
    QToolButton {{
        background: transparent;
        color: {t['text_dim']};
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 4px 10px;
        font-weight: 500;
    }}
    QToolButton:hover {{
        background: {t['panel2']};
        color: {t['text']};
    }}
    QToolButton:pressed, QToolButton:checked {{
        background: {t['border']};
        color: {t['text']};
    }}
    QTabWidget::pane {{
        border: none;
        background: {t['editor_bg']};
    }}
    QTabBar {{
        background: {t['panel']};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {t['text_dim']};
        border: none;
        border-right: 1px solid {t['border']};
        padding: 6px 10px 6px 12px;
        min-width: 110px;
        max-height: 24px;
    }}
    QTabBar::tab:selected {{
        background: {t['editor_bg']};
        color: {t['text']};
        border-top: 2px solid {t['accent']};
    }}
    QTabBar::tab:hover:!selected {{
        background: {t['panel2']};
    }}
    QStatusBar {{
        background: {t['panel']};
        border-top: 1px solid {t['border']};
        color: {t['text_dim']};
    }}
    QStatusBar::item {{ border: none; }}
    QLineEdit, QSpinBox, QComboBox {{
        background: {t['editor_bg']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        padding: 4px 8px;
        selection-background-color: {t['selection']};
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {t['accent']};
    }}
    QPushButton {{
        background: {t['panel2']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        padding: 5px 14px;
    }}
    QPushButton:hover {{ border-color: {t['accent']}; }}
    QPushButton:pressed {{ background: {t['border']}; }}
    QPushButton:default {{
        background: {t['accent']};
        color: {t['accent_text']};
        border-color: {t['accent']};
    }}
    QMenuBar {{
        background: {t['panel']};
        border: none;
        border-bottom: 1px solid {t['border']};
        padding: 2px 4px;
        spacing: 2px;
    }}
    QMenuBar::item {{
        background: transparent;
        color: {t['text_dim']};
        border-radius: 5px;
        padding: 4px 10px;
    }}
    QMenuBar::item:selected {{
        background: {t['panel2']};
        color: {t['text']};
    }}
    QMenuBar::item:pressed {{
        background: {t['border']};
        color: {t['text']};
    }}
    QMenu {{
        background: {t['panel']};
        border: 1px solid {t['border']};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 5px 24px 5px 12px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: {t['panel2']};
        color: {t['text']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {t['border']};
        margin: 4px 8px;
    }}
    QLabel#dimLabel, QCheckBox {{ color: {t['text_dim']}; }}
    QLabel#welcomeTitle {{
        color: {t['text']};
        font-size: 30px;
        font-weight: 700;
    }}
    QLabel#welcomeSection {{
        color: {t['text_dim']};
        font-size: 11px;
        font-weight: 600;
    }}
    QListWidget#recentList {{
        background: {t['panel']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 7px;
        padding: 4px;
        outline: none;
    }}
    QListWidget#recentList::item {{
        border-radius: 4px;
        padding: 5px 10px;
    }}
    QListWidget#recentList::item:hover {{
        background: {t['panel2']};
    }}
    QListWidget#recentList::item:selected {{
        background: {t['selection']};
        color: {t['editor_text']};
    }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {t['border']};
        border-radius: 4px;
        background: {t['editor_bg']};
    }}
    QCheckBox::indicator:checked {{
        background: {t['accent']};
        border-color: {t['accent']};
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {t['border']};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        margin: -6px 0;
        border-radius: 7px;
        background: {t['accent']};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 11px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t['border']};
        border-radius: 4px;
        min-height: 30px;
        margin: 2px 3px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t['text_dim']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 11px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['border']};
        border-radius: 4px;
        min-width: 30px;
        margin: 3px 2px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {t['text_dim']}; }}
    QToolTip {{
        background: {t['panel2']};
        color: {t['text']};
        border: 1px solid {t['border']};
        padding: 4px 8px;
    }}
    QMessageBox {{ background: {t['window_bg']}; }}
    """
