"""SmoothCaret: a custom-painted caret overlay with Word-style interpolation.

The real QTextCursor updates instantly; this overlay owns a purely visual
caret that glides toward the cursor's pixel position at ~120 FPS using
frame-rate-independent exponential smoothing.
"""

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

TICK_MS = 8                 # ~120 FPS animation clock
MOVE_HOLD_MS = 0.35         # stay solid after movement before blinking resumes
SNAP_DISTANCE = 2000.0      # px; beyond this the jump is instant (Ctrl+Home etc.)
OFFSCREEN_MARGIN = 40       # px; caret outside this rect snaps on next tick
MIN_ALPHA = 0.08            # caret never fully vanishes (subtle pulse)


class SmoothCaret(QWidget):
    def __init__(self, editor, accent_color: QColor, parent=None):
        # Parent is the viewport: coordinates stay in sync with cursorRect().
        super().__init__(editor.viewport())
        self._editor = editor
        self._accent = QColor(accent_color)

        self.current = QPointF(-1, -1)   # animated caret position (viewport px)
        self.target = QPointF(-1, -1)    # where the real cursor is now
        self._caret_height = 0.0
        self._alpha = 0.0
        self._last_alpha = -1.0
        self._last_paint_rect = QRectF()

        self.speed = 14.0                # smoothing rate (1/s)
        self.blink_ms = 1100
        self._focused = editor.hasFocus()
        self._last_activity = time.monotonic()
        self._last_tick = time.monotonic()

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)

        editor.cursorPositionChanged.connect(self.on_activity)
        editor.textChanged.connect(self.on_activity)
        editor.selectionChanged.connect(self.on_activity)
        editor.verticalScrollBar().valueChanged.connect(self._snap_now)
        editor.horizontalScrollBar().valueChanged.connect(self._snap_now)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------ API

    def apply_theme(self, accent_color: QColor):
        self._accent = QColor(accent_color)
        self.update()

    def set_focus_state(self, focused: bool):
        self._focused = focused
        if focused:
            self._snap_now()
            self.on_activity()

    def resize_to_viewport(self):
        self.setGeometry(self._editor.viewport().rect())
        self._snap_now()

    def on_activity(self):
        """Called on every cursor move / text change: caret goes solid."""
        self._last_activity = time.monotonic()

    def snap_to_cursor(self):
        """Public hook: teleport the visual caret to the real cursor."""
        self._snap_now()

    def _snap_now(self, *_):
        """Teleport the visual caret (scroll, resize, focus, huge jumps)."""
        cr = self._editor.cursorRect()
        self.current = QPointF(cr.x(), cr.y())
        self.target = self.current
        self._caret_height = cr.height()
        self._last_activity = time.monotonic()
        self._repaint_region(self._caret_rect(), True)

    # ------------------------------------------------------------- animation

    def _tick(self):
        if not self._editor.isVisible():
            return
        editor = self._editor
        cr = editor.cursorRect()
        self.target = QPointF(cr.x(), cr.y())
        self._caret_height = cr.height()

        now = time.monotonic()
        dt = min(now - self._last_tick, 0.1)
        self._last_tick = now

        # Snap instead of animating when the move is not a "travel" move:
        # first paint, gigantic jumps, or anything the viewport scrolled.
        dx = self.target.x() - self.current.x()
        dy = self.target.y() - self.current.y()
        dist = math.hypot(dx, dy)
        first_paint = self.current.x() < 0
        vp = editor.viewport().rect()
        caret_lost = (
            self.current.x() < vp.x() - OFFSCREEN_MARGIN
            or self.current.x() > vp.right() + OFFSCREEN_MARGIN
            or self.current.y() < vp.y() - OFFSCREEN_MARGIN
            or self.current.y() > vp.bottom() + OFFSCREEN_MARGIN
        )
        if first_paint or dist > SNAP_DISTANCE or caret_lost:
            self.current = self.target
        elif dist > 0.25:
            # Frame-rate-independent exponential smoothing, no overshoot.
            k = 1.0 - math.exp(-self.speed * dt)
            self.current += QPointF(dx * k, dy * k)

        self._update_alpha(now, dist)
        self._repaint_region(self._caret_rect(), False)

    def _update_alpha(self, now, dist):
        if not self._focused:
            self._alpha = 0.0
            return
        if dist > 0.7:
            self._last_activity = now
            self._alpha = 1.0
            return
        idle = now - self._last_activity
        if idle < MOVE_HOLD_MS:
            self._alpha = 1.0
            return
        # Blink cycle: solid, quick fade out, faint hold, quick fade in.
        period = max(self.blink_ms, 300) / 1000.0
        frac = ((idle - MOVE_HOLD_MS) / period) % 1.0
        if frac < 0.55:
            a = 1.0
        elif frac < 0.70:
            a = 1.0 - (frac - 0.55) / 0.15 * (1.0 - MIN_ALPHA)
        elif frac < 0.85:
            a = MIN_ALPHA
        else:
            a = MIN_ALPHA + (frac - 0.85) / 0.15 * (1.0 - MIN_ALPHA)
        self._alpha = a

    # ---------------------------------------------------------------- paint

    def _caret_rect(self) -> QRectF:
        if self._caret_height <= 0:
            return QRectF()
        return QRectF(self.current.x() - 1.0, self.current.y(), 2.0,
                      self._caret_height)

    def _repaint_region(self, rect: QRectF, force: bool):
        """Repaint only the pixels the caret actually touches."""
        if rect.isEmpty():
            return
        alpha_changed = abs(self._alpha - self._last_alpha) > 0.004
        moved = rect != self._last_paint_rect
        if not (force or moved or alpha_changed):
            return
        region = rect.united(self._last_paint_rect).toAlignedRect()
        self.update(region.adjusted(-2, -2, 2, 2))
        self._last_paint_rect = QRectF(rect)
        self._last_alpha = self._alpha

    def paintEvent(self, event):
        if self._alpha <= 0.012 or self._caret_height <= 0:
            return
        painter = QPainter(self)
        color = QColor(self._accent)
        color.setAlphaF(min(max(self._alpha, 0.0), 1.0))
        painter.fillRect(self._caret_rect(), color)
        painter.end()
