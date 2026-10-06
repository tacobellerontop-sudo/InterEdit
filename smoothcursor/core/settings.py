"""Persistent settings + settings dialog for SmoothCursor."""

import math
import os
import time

from PySide6.QtCore import (QSettings, QStandardPaths, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from smoothcursor.core.theme import (THEMES, available_themes,
                                       load_custom_themes, themes_dir,
                                       write_example_theme)

RECENT_LIMIT = 10

DEFAULTS = {
    "font_family": "",          # "" = auto-pick best available mono font
    "font_size": 13,
    "tab_size": 4,
    "insert_spaces": True,
    "word_wrap": False,
    "auto_lists": True,       # Enter continues 1./-/[ ] lists + > quotes
    "auto_pairs": True,       # auto-close ()[]{}"' + skip-over + {} expand
    "caret_speed": 14.0,        # exponential smoothing rate (higher = snappier)
    "caret_blink_ms": 1100,     # full blink cycle in ms
    "theme": "dark",
    "line_numbers": "absolute",  # off | absolute | relative | hybrid
    "spellcheck": True,         # wavy underlines on prose tabs
}

LINE_NUMBER_MODES = (
    ("Off", "off"),
    ("Absolute", "absolute"),
    ("Relative", "relative"),
    ("Hybrid", "hybrid"),
)

MONO_FONT_CANDIDATES = [
    "JetBrains Mono", "Fira Code", "Cascadia Code", "Source Code Pro",
    "Hack", "Ubuntu Mono", "Noto Sans Mono", "Liberation Mono",
    "DejaVu Sans Mono", "monospace",
]


class Settings:
    """Thin wrapper around QSettings with typed defaults."""

    def __init__(self):
        self._qs = QSettings("smoothcursor", "SmoothCursor")
        self._cache = dict(DEFAULTS)
        for key in DEFAULTS:
            if self._qs.contains(key):
                self._cache[key] = self._qs.value(key, DEFAULTS[key])
        # QSettings may hand back strings; coerce to declared types.
        for key, default in DEFAULTS.items():
            val = self._cache[key]
            if isinstance(default, bool):
                self._cache[key] = val in (True, "true", "True", 1, "1")
            elif isinstance(default, (int, float)):
                try:
                    self._cache[key] = type(default)(val)
                except (TypeError, ValueError):
                    self._cache[key] = default

    def get(self, key):
        return self._cache.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self._cache[key] = value
        self._qs.setValue(key, value)
        self._qs.sync()  # flush now so a crash/restart never loses prefs

    # ------------------------------------------------- raw value passthrough

    def value(self, key, default=None):
        """Read a non-pref value (geometry, active tab, …)."""
        return self._qs.value(key, default)

    def set_value(self, key, value):
        self._qs.setValue(key, value)
        self._qs.sync()

    # ------------------------------------------------------------- recent

    def get_recent(self, limit=RECENT_LIMIT):
        val = self._qs.value("recent", [])
        files = val if isinstance(val, list) else [val]
        return [str(f) for f in files if f][:limit]

    def push_recent(self, path, limit=RECENT_LIMIT):
        files = [p for p in self.get_recent(limit) if p != path]
        self._qs.setValue("recent", [path] + files[:limit - 1])
        self._qs.sync()

    def drop_recent(self, path):
        self._qs.setValue("recent",
                          [p for p in self.get_recent() if p != path])
        self._qs.sync()

    # ------------------------------------------------------------ session

    @staticmethod
    def backup_dir():
        """Directory holding hot-exit backups of unsaved tabs."""
        loc = QStandardPaths.writableLocation(
            QStandardPaths.AppDataLocation)
        if not loc:
            loc = os.path.expanduser("~/.local/share/smoothcursor")
        path = os.path.join(loc, "backups")
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _to_int(val, default=0):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def save_session(self, tabs, active=0):
        """Persist open tabs: [{kind, path, backup, cursor}]."""
        qs = self._qs
        qs.beginGroup("session")
        qs.remove("tabs")  # avoid stale entries when shrinking
        qs.beginWriteArray("tabs")
        for i, tab in enumerate(tabs):
            qs.setArrayIndex(i)
            qs.setValue("kind", tab.get("kind", "file"))
            qs.setValue("path", tab.get("path", ""))
            qs.setValue("backup", tab.get("backup", ""))
            qs.setValue("cursor", int(tab.get("cursor", 0)))
        qs.endArray()
        qs.setValue("active", int(active))
        qs.endGroup()
        qs.sync()

    def load_session(self):
        """Returns ([{kind, path, backup, cursor}], active_index)."""
        qs = self._qs
        tabs = []
        try:
            qs.beginGroup("session")
            count = qs.beginReadArray("tabs")
            for i in range(count):
                qs.setArrayIndex(i)
                tabs.append({
                    "kind": str(qs.value("kind", "file")),
                    "path": str(qs.value("path", "") or ""),
                    "backup": str(qs.value("backup", "") or ""),
                    "cursor": self._to_int(qs.value("cursor", 0)),
                })
            qs.endArray()
            active = self._to_int(qs.value("active", 0))
            qs.endGroup()
        except Exception:
            try:
                qs.endGroup()
            except Exception:
                pass
            return [], 0
        return tabs, active

    def resolved_font_family(self):
        family = self.get("font_family")
        if family:
            return family
        available = set(QFontDatabase.families())
        for cand in MONO_FONT_CANDIDATES:
            if cand in available:
                return cand
        return QFontDatabase.systemFont(QFontDatabase.FixedFont).family()


class LabeledSlider(QWidget):
    """Slider + live value label on one row."""

    def __init__(self, minimum, maximum, value, fmt="{:g}", parent=None):
        super().__init__(parent)
        self._fmt = fmt
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(int(value))
        self.label = QLabel(fmt.format(value))
        self.label.setObjectName("dimLabel")
        self.label.setMinimumWidth(64)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(
            lambda v: self.label.setText(fmt.format(v)))

    def value(self):
        return self.slider.value()


class CaretPreview(QWidget):
    """Live preview of the caret-speed slider.

    Simulates typing the sample lines, gliding a caret with the exact
    exponential smoothing used by SmoothCaret, so dragging the speed
    slider visibly changes how tightly the caret tracks each keystroke.
    """

    LINES = ("def greet(name):", '    return f"hi {name}"')
    STEP_MS = 120      # simulated typing rate
    TICK_MS = 8        # animation clock, same as SmoothCaret
    HOLD_STEPS = 7     # pause on the finished text before looping
    PAD = 10

    def __init__(self, accent="#4fc1ff", bg="#1e2127", fg="#dcdfe4",
                 font_family="monospace", font_size=12, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(72)
        self._accent = QColor(accent)
        self._bg = QColor(bg)
        self._fg = QColor(fg)
        self._font = QFont(font_family)
        self._font.setPointSize(max(8, int(font_size)))
        self.speed = 14.0
        self.blink_ms = 1100
        self._route = [(li, col) for li, line in enumerate(self.LINES)
                       for col in range(len(line) + 1)]
        self._idx = 0
        self._hold = 0
        self._cur = [0.0, 0.0]
        self._tgt = [0.0, 0.0]
        self._alpha = 1.0
        self._primed = False
        self._last_activity = time.monotonic()
        self._last_tick = time.monotonic()
        self._anim = QTimer(self)
        self._anim.setInterval(self.TICK_MS)
        self._anim.timeout.connect(self._tick)
        self._step = QTimer(self)
        self._step.setInterval(self.STEP_MS)
        self._step.timeout.connect(self._advance)

    # ------------------------------------------------- dialog control hooks

    def set_speed(self, speed):
        self.speed = max(1.0, float(speed))

    def set_blink(self, ms):
        self.blink_ms = int(ms)

    def set_font(self, family, size):
        self._font = QFont(family)
        self._font.setPointSize(max(8, int(size)))
        self._primed = False
        self.update()

    def set_theme(self, accent, bg, fg):
        self._accent = QColor(accent)
        self._bg = QColor(bg)
        self._fg = QColor(fg)
        self.update()

    # ---------------------------------------------------------- simulation

    def showEvent(self, event):
        super().showEvent(event)
        self._last_tick = time.monotonic()
        self._anim.start()
        self._step.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._anim.stop()
        self._step.stop()

    def _pos(self, li, col):
        fm = QFontMetrics(self._font)
        line = self.LINES[li]
        return (self.PAD + fm.horizontalAdvance(line[:col]),
                self.PAD + li * fm.lineSpacing())

    def _advance(self):
        """Simulate the next keystroke; loop with a snap back to start."""
        self._last_activity = time.monotonic()
        if self._idx >= len(self._route) - 1:
            self._hold += 1
            if self._hold >= self.HOLD_STEPS:
                self._idx, self._hold = 0, 0
                self._tgt = list(self._pos(0, 0))
                self._cur = list(self._tgt)  # teleport, like huge jumps do
            self.update()
            return
        self._idx += 1
        self._tgt = list(self._pos(*self._route[self._idx]))

    def _tick(self):
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now
        if not self._primed:
            self._tgt = list(self._pos(*self._route[self._idx]))
            self._cur = list(self._tgt)
            self._primed = True
        dx, dy = self._tgt[0] - self._cur[0], self._tgt[1] - self._cur[1]
        dist = math.hypot(dx, dy)
        if dist > 0.25:
            k = 1.0 - math.exp(-self.speed * dt)
            self._cur[0] += dx * k
            self._cur[1] += dy * k
        self._alpha = self._blink_alpha(now, dist)
        self.update()

    @staticmethod
    def _blink_frac(now_idle, period):
        return (now_idle / period) % 1.0

    def _blink_alpha(self, now, dist):
        # Same feel as SmoothCaret: solid while travelling, then blink.
        if dist > 0.7:
            self._last_activity = now
            return 1.0
        idle = now - self._last_activity
        if idle < 0.35:
            return 1.0
        period = max(self.blink_ms, 300) / 1000.0
        frac = self._blink_frac(idle - 0.35, period)
        if frac < 0.55:
            return 1.0
        if frac < 0.70:
            return 1.0 - (frac - 0.55) / 0.15 * 0.92
        if frac < 0.85:
            return 0.08
        return 0.08 + (frac - 0.85) / 0.15 * 0.92

    # -------------------------------------------------------------- painting

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._bg)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

        fm = QFontMetrics(self._font)
        painter.setFont(self._font)
        li_now, col_now = self._route[self._idx]
        text_color = QColor(self._fg)
        text_color.setAlphaF(0.7)
        painter.setPen(text_color)
        for li, line in enumerate(self.LINES):
            if li > li_now:
                break
            shown = line if li < li_now else line[:col_now]
            painter.drawText(self.PAD, self.PAD + li * fm.lineSpacing()
                             + fm.ascent(), shown)

        if self._alpha > 0.012:
            caret = QColor(self._accent)
            caret.setAlphaF(min(max(self._alpha, 0.0), 1.0))
            painter.fillRect(int(self._cur[0]) - 1, int(self._cur[1]), 2,
                             fm.height(), caret)
        painter.end()


class SettingsDialog(QDialog):
    """Modal settings editor. Writes back through `settings` on accept."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)

        outer = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(12)
        outer.addLayout(form)

        self.font_combo = QComboBox()
        families = QFontDatabase.families()
        fixed = [f for f in MONO_FONT_CANDIDATES if f in families]
        # Offer all fixed-pitch candidates plus whatever is currently chosen.
        items = fixed or MONO_FONT_CANDIDATES[:]
        current = settings.resolved_font_family()
        if current not in items:
            items.insert(0, current)
        self.font_combo.addItems(items)
        self.font_combo.setCurrentText(current)
        form.addRow("Font", self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 40)
        self.size_spin.setValue(int(settings.get("font_size")))
        form.addRow("Font size", self.size_spin)

        self.tab_spin = QSpinBox()
        self.tab_spin.setRange(1, 12)
        self.tab_spin.setValue(int(settings.get("tab_size")))
        form.addRow("Tab size", self.tab_spin)

        self.spaces_check = QCheckBox("Insert spaces instead of tabs")
        self.spaces_check.setChecked(bool(settings.get("insert_spaces")))
        form.addRow("", self.spaces_check)

        self.wrap_check = QCheckBox("Word wrap")
        self.wrap_check.setChecked(bool(settings.get("word_wrap")))
        form.addRow("", self.wrap_check)

        self.lists_check = QCheckBox("Auto-continue lists & quotes")
        self.lists_check.setToolTip(
            "Enter after '1. ', '- ', '* ', '- [ ] ' or '> ' continues it; "
            "Enter on an empty item exits it.")
        self.lists_check.setChecked(bool(settings.get("auto_lists")))
        form.addRow("", self.lists_check)

        self.pairs_check = QCheckBox("Auto-close brackets & quotes")
        self.pairs_check.setToolTip(
            "Typing ( [ { \" ' inserts the closing pair; typing the "
            "closer skips past it; Enter between {} expands.")
        self.pairs_check.setChecked(bool(settings.get("auto_pairs")))
        form.addRow("", self.pairs_check)

        self.lnum_combo = QComboBox()
        for label, _mode in LINE_NUMBER_MODES:
            self.lnum_combo.addItem(label)
        current_mode = settings.get("line_numbers")
        for label, mode in LINE_NUMBER_MODES:
            if mode == current_mode:
                self.lnum_combo.setCurrentText(label)
                break
        else:
            self.lnum_combo.setCurrentText("Absolute")
        self.lnum_combo.setToolTip(
            "Left gutter: Off hides it, Absolute shows 1..n, Relative "
            "shows distance from the cursor line, Hybrid shows both.")
        form.addRow("Line numbers", self.lnum_combo)

        self.spell_check = QCheckBox("Spellcheck prose tabs")
        self.spell_check.setToolTip(
            "Wavy underlines for misspelled words in text/rich tabs "
            "(never inside code); right-click a word for suggestions.")
        self.spell_check.setChecked(bool(settings.get("spellcheck")))
        form.addRow("", self.spell_check)
        try:
            from smoothcursor.editor.spellcheck import (
                spell_available, spell_backend_name,
            )
            if spell_available():
                spell_status = "Dictionary: %s" % spell_backend_name()
            else:
                spell_status = ("No dictionaries found — install a "
                                "hunspell dictionary (e.g. hunspell-en-us).")
        except Exception:
            spell_status = ""
        self.spell_hint = QLabel(spell_status)
        self.spell_hint.setObjectName("dimLabel")
        form.addRow("", self.spell_hint)

        self.speed_slider = LabeledSlider(4, 40, settings.get("caret_speed"), "{:.0f}")
        form.addRow("Caret speed", self.speed_slider)

        self.blink_spin = QSpinBox()
        self.blink_spin.setRange(300, 2500)
        self.blink_spin.setSuffix(" ms")
        self.blink_spin.setSingleStep(50)
        self.blink_spin.setValue(int(settings.get("caret_blink_ms")))
        form.addRow("Blink cycle", self.blink_spin)

        theme = THEMES.get(settings.get("theme"), THEMES["dark"])
        self.caret_preview = CaretPreview(
            accent=theme["accent"], bg=theme["editor_bg"],
            fg=theme["editor_text"],
            font_family=settings.resolved_font_family(),
            font_size=settings.get("font_size"))
        self.caret_preview.set_speed(settings.get("caret_speed"))
        self.caret_preview.set_blink(settings.get("caret_blink_ms"))
        form.addRow("Preview", self.caret_preview)

        try:
            load_custom_themes()
        except Exception:
            pass
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(available_themes())
        current_theme = settings.get("theme")
        if current_theme not in THEMES:
            current_theme = "dark"
        self.theme_combo.setCurrentText(current_theme)
        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(0, 0, 0, 0)
        theme_row.addWidget(self.theme_combo, 1)
        from PySide6.QtWidgets import QPushButton
        self.themes_button = QPushButton("Folder")
        self.themes_button.setToolTip(
            "Open the JSON themes folder (~/.local/share/…/themes)")
        self.themes_button.clicked.connect(self._open_themes_folder)
        theme_row.addWidget(self.themes_button)
        self.themes_reload = QPushButton("Reload")
        self.themes_reload.setToolTip("Reload *.json themes from disk")
        self.themes_reload.clicked.connect(self._reload_themes)
        theme_row.addWidget(self.themes_reload)
        theme_wrap = QWidget()
        theme_wrap.setLayout(theme_row)
        form.addRow("Theme", theme_wrap)
        self.themes_hint = QLabel(
            "Custom themes: <theme>.json with \"#rrggbb\" colors.")
        self.themes_hint.setObjectName("dimLabel")
        form.addRow("", self.themes_hint)

        self.speed_slider.slider.valueChanged.connect(
            lambda _v: self.caret_preview.set_speed(
                float(self.speed_slider.value())))
        self.blink_spin.valueChanged[int].connect(
            lambda _v: self.caret_preview.set_blink(self.blink_spin.value()))
        self.size_spin.valueChanged[int].connect(
            lambda _v: self.caret_preview.set_font(
                self.font_combo.currentText(), self.size_spin.value()))
        self.font_combo.currentTextChanged.connect(
            lambda _t: self.caret_preview.set_font(
                self.font_combo.currentText(), self.size_spin.value()))
        self.theme_combo.currentTextChanged.connect(
            self._on_preview_theme_changed)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("dimLabel")
        outer.addWidget(line)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _open_themes_folder(self):
        folder = themes_dir()
        try:
            write_example_theme(folder)
        except Exception:
            pass
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception:
            pass

    def _reload_themes(self):
        try:
            loaded, errors = load_custom_themes()
        except Exception:
            loaded, errors = [], {}
        current = self.theme_combo.currentText()
        self.theme_combo.clear()
        self.theme_combo.addItems(available_themes())
        if current in THEMES:
            self.theme_combo.setCurrentText(current)
        if errors:
            self.themes_hint.setText(
                "Reloaded (%d). Skipped: %s" % (
                    len(loaded),
                    ", ".join(sorted(errors)[:3])))
        else:
            self.themes_hint.setText(
                "Reloaded %d custom theme(s) from JSON." % len(loaded)
                if loaded else
                "Themes folder ready — add <name>.json and Reload.")

    def _on_preview_theme_changed(self, name):
        theme = THEMES.get(name, THEMES["dark"])
        self.caret_preview.set_theme(theme["accent"], theme["editor_bg"],
                                     theme["editor_text"])

    def accept(self):
        s = self.settings
        s.set("font_family", self.font_combo.currentText())
        s.set("font_size", self.size_spin.value())
        s.set("tab_size", self.tab_spin.value())
        s.set("insert_spaces", self.spaces_check.isChecked())
        s.set("word_wrap", self.wrap_check.isChecked())
        s.set("auto_lists", self.lists_check.isChecked())
        s.set("auto_pairs", self.pairs_check.isChecked())
        s.set("spellcheck", self.spell_check.isChecked())
        s.set("caret_speed", float(self.speed_slider.value()))
        for label, mode in LINE_NUMBER_MODES:
            if label == self.lnum_combo.currentText():
                s.set("line_numbers", mode)
                break
        s.set("caret_blink_ms", self.blink_spin.value())
        s.set("theme", self.theme_combo.currentText())
        super().accept()
