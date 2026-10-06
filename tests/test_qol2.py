import os
_tmp_config = __import__('tempfile').mkdtemp(prefix='smoothcursor-test-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp_config, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp_config, 'data')
import sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
app = QApplication([])
from smoothcursor.editor.editor import CodeEditor
from smoothcursor.views.search import FindBar
from smoothcursor.core.settings import Settings, DEFAULTS
from smoothcursor.core.theme import THEMES
from smoothcursor.views.window import MainWindow

def make(text, lang='python'):
    s = Settings()
    for k,v in DEFAULTS.items(): s.set(k,v)
    ed = CodeEditor(s, THEMES['dark'], language=lang)
    ed.setPlainText(text)
    return ed

fails=[]
def check(name, got, exp):
    ok = got==exp
    print(('PASS ' if ok else 'FAIL ')+name+('' if ok else ' got=%r exp=%r'%(got,exp)))
    if not ok: fails.append(name)

# replace one / all
ed = make('foo bar foo baz foo')
bar = FindBar()
bar.open_for(ed)
bar.field.setText('foo')
bar._refresh()
check('find count', bar.count_label.text(), '1 / 3')
bar.replace_field.setText('qux')
bar.replace_one()
check('replace one', ed.toPlainText(), 'qux bar foo baz foo')
bar.replace_all()
check('replace all', ed.toPlainText(), 'qux bar qux baz qux')
check('replace all label', bar.count_label.text(), '2 replaced')

# replace with no matches
bar2 = FindBar()
ed2 = make('hello')
bar2.open_for(ed2)
bar2.field.setText('zzz'); bar2._refresh()
bar2.replace_field.setText('q')
bar2.replace_one()
check('replace none noop', ed2.toPlainText(), 'hello')
bar2.replace_all()
check('replace all none', ed2.toPlainText(), 'hello')
check('replace all none label', bar2.count_label.text(), '0 replaced')

# replace mode visibility
bar3 = FindBar()
ed3 = make('x')
bar3.open_for(ed3, replace=False)
check('find hides replace', bar3.replace_field.isVisible(), False)
bar3.open_for(ed3, replace=True)
check('replace shows field', bar3.replace_field.isVisible(), True)

# window: zoom + status + shortcuts exist
w = MainWindow(Settings())
w.new_file()
w.zoom_font(2)
check('zoom in', w.settings.get('font_size'), 15)
w.zoom_font(-100)
check('zoom clamp min', w.settings.get('font_size'), 8)
w.zoom_font(1000)
check('zoom clamp max', w.settings.get('font_size'), 40)
w.reset_zoom()
check('zoom reset', w.settings.get('font_size'), 13)

ed4 = w.current_editor()
ed4.setPlainText('hello world foo')
w._refresh_ui()
check('status words', w.position_label.text(), 'Ln 1, Col 1 · 3 words')
c = ed4.textCursor(); c.setPosition(0); c.setPosition(5, QTextCursor.KeepAnchor)
ed4.setTextCursor(c)
w._refresh_ui()
check('status sel', w.position_label.text(), 'Ln 1, Col 6 · 5 selected')

# editor wheel-zoom routing (fake wheel event)
from PySide6.QtGui import QWheelEvent
from PySide6.QtCore import QPointF, QPoint, Qt
ev = QWheelEvent(QPointF(10,10), QPointF(10,10), QPoint(0,0), QPoint(0,120),
                 Qt.NoButton, Qt.ControlModifier, Qt.ScrollUpdate, False)
ed4.wheelEvent(ev)
check('wheel zoom', w.settings.get('font_size'), 14)

# key bindings fire through keyPressEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
def key(ed, code, mods, text=''):
    ed.keyPressEvent(QKeyEvent(QEvent.KeyPress, code, mods, text))
ed5 = make('x = 1')
c = ed5.textCursor(); c.movePosition(QTextCursor.End); ed5.setTextCursor(c)
key(ed5, Qt.Key_Slash, Qt.ControlModifier, '/')
check('ctrl+/ via key', ed5.toPlainText(), '# x = 1')
key(ed5, Qt.Key_D, Qt.ControlModifier, 'd')
check('ctrl+d via key', ed5.toPlainText(), '# x = 1\n# x = 1')

print('fails:', fails)
sys.exit(1 if fails else 0)
