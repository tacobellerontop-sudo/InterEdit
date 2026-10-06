import os
_tmp_config = __import__('tempfile').mkdtemp(prefix='smoothcursor-test-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp_config, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp_config, 'data')
import sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QTextCursor
app = QApplication([])
from smoothcursor.editor.editor import CodeEditor
from smoothcursor.editor.rich import RichEditor
from smoothcursor.editor.line_numbers import gutter_label
from smoothcursor.core.settings import (
    DEFAULTS, LINE_NUMBER_MODES, Settings, SettingsDialog,
)
from smoothcursor.core.theme import THEMES

fails = []
def check(name, got, exp):
    ok = got == exp
    print(('PASS ' if ok else 'FAIL ') + name +
          ('' if ok else ' got=%r exp=%r' % (got, exp)))
    if not ok:
        fails.append(name)


def make_settings():
    s = Settings()
    for k, v in DEFAULTS.items():
        s.set(k, v)
    return s


# --- label math for every mode ---
check('label absolute', gutter_label('absolute', 4, 9), '5')
check('label relative self', gutter_label('relative', 9, 9), '0')
check('label relative above', gutter_label('relative', 6, 9), '3')
check('label relative below', gutter_label('relative', 12, 9), '3')
check('label hybrid self', gutter_label('hybrid', 9, 9), '10')
check('label hybrid other', gutter_label('hybrid', 6, 9), '3')

# --- settings default + dialog round-trip ---
s = make_settings()
check('default mode', s.get('line_numbers'), 'absolute')
dlg = SettingsDialog(s)
check('dialog shows absolute', dlg.lnum_combo.currentText(), 'Absolute')
dlg.lnum_combo.setCurrentText('Relative')
dlg.accept()
check('dialog persists relative', s.get('line_numbers'), 'relative')
s2 = make_settings()
s2.set('line_numbers', 'bogus')
dlg2 = SettingsDialog(s2)
check('dialog falls back', dlg2.lnum_combo.currentText(), 'Absolute')

# --- code editor gutter in every mode ---
s3 = make_settings()
ed = CodeEditor(s3, THEMES['dark'])
ed.resize(500, 400)
ed.show()
ed.setPlainText('\n'.join('l%d' % i for i in range(50)))
for mode, width_expected in (('absolute', True), ('relative', True),
                             ('hybrid', True), ('off', False)):
    s3.set('line_numbers', mode)
    ed.apply_settings()
    check('code %s width' % mode, ed.gutter_width() > 0, width_expected)
    check('code %s visible' % mode, ed.gutter.isVisible(), width_expected)
    pix = QPixmap(500, 400)
    ed.render(pix)  # full repaint incl. gutter must not crash
check('code render ok', True, True)

# --- rich editor gutter (previously stubbed to 0) ---
s4 = make_settings()
red = RichEditor(s4, THEMES['dark'])
red.resize(500, 400)
red.show()
red.setPlainText('\n'.join('line %d' % i for i in range(200)))
for mode, width_expected in (('absolute', True), ('relative', True),
                             ('hybrid', True), ('off', False)):
    s4.set('line_numbers', mode)
    red.apply_settings()
    check('rich %s width' % mode, red.gutter_width() > 0, width_expected)
    check('rich %s visible' % mode, red.gutter.isVisible(), width_expected)
    pix = QPixmap(500, 400)
    red.render(pix)
check('rich render ok', True, True)

# --- rich gutter tracks real document lines ---
s4.set('line_numbers', 'absolute')
red.apply_settings()
first = red._first_visible_block()
check('first visible valid', first.isValid(), True)
probe = QTextCursor(first)
probe.setPosition(first.position())
expected = red.cursorRect(probe).top()
check('gutter aligned', abs(expected - red._block_top(
    first, red._calibrate(first))) <= 1, True)
red.select_line_at(50)
check('click selects line', red.textCursor().block().text(), 'line 2')
# relative numbers move with the cursor without crashing
s4.set('line_numbers', 'relative')
red.apply_settings()
cur = red.textCursor()
cur.setPosition(red.document().findBlockByNumber(60).position())
red.setTextCursor(cur)
pix = QPixmap(500, 400)
red.render(pix)
check('relative follows cursor', red.textCursor().blockNumber(), 60)

print('fails:', fails)
sys.exit(1 if fails else 0)
