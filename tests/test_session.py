import os
_tmp_config = __import__('tempfile').mkdtemp(prefix='smoothcursor-test-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp_config, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp_config, 'data')
import sys, tempfile
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
app = QApplication([])
from smoothcursor.core.settings import Settings
from smoothcursor.views.window import MainWindow

fails=[]
def check(name, got, exp):
    ok = got==exp
    print(('PASS ' if ok else 'FAIL ')+name+('' if ok else ' got=%r exp=%r'%(got,exp)))
    if not ok: fails.append(name)

tmp = tempfile.mkdtemp()
fa = os.path.join(tmp, 'a.py'); open(fa,'w').write('x = 1\ny = 2\nz = 3\n')
fb = os.path.join(tmp, 'b.txt'); open(fb,'w').write('hello\nworld\n')

# session 1: two files + one untitled with content + one blank scratch
w1 = MainWindow(Settings())
w1.close_tab(0)  # drop auto-created untitled
assert w1.open_path(fa) and w1.open_path(fb)
w1.new_file()
ed = w1.current_editor()
ed.setPlainText('unsaved notes\nline2\n')
c = ed.textCursor(); c.setPosition(5); ed.setTextCursor(c)
w1.tabs.add_editor(w1._make_editor(), 'scratch', '')
# cursors in file tabs
e0 = w1.tabs.editor_at(0); c0 = e0.textCursor(); c0.setPosition(4); e0.setTextCursor(c0)
w1.tabs.setCurrentIndex(1)
e1 = w1.tabs.editor_at(1); c1 = e1.textCursor(); c1.setPosition(8); e1.setTextCursor(c1)
w1.tabs.setCurrentIndex(0)
w1.resize(640, 480)
from PySide6.QtWidgets import QApplication as QA
QA.processEvents()
w1._save_session()
w1.settings.set_value('session/geometry', w1.saveGeometry())
check('recent has files', w1.settings.get_recent()[:2], [fb, fa])

# fresh window restores everything
w2 = MainWindow(Settings())
check('tab count (2 files + untitled, blank skipped)',
      w2.tabs.count(), 3)
paths = [w2.tabs.editor_at(i).file_path for i in range(3)]
check('restored paths', paths, [fa, fb, None])
check('file cursor', w2.tabs.editor_at(0).textCursor().position(), 4)
check('file2 cursor', w2.tabs.editor_at(1).textCursor().position(), 8)
check('untitled text', w2.tabs.editor_at(2).toPlainText(), 'unsaved notes\nline2\n')
check('untitled cursor', w2.tabs.editor_at(2).textCursor().position(), 5)
check('untitled modified', w2.tabs.editor_at(2).document().isModified(), True)
check('active tab', w2.tabs.currentIndex(), 0)
check('geometry restored', (w2.width(), w2.height()), (640, 480))

# recent menu rebuild + missing-file drop
w2._rebuild_recent_menu()
check('recent menu items', len(w2.recent_menu.actions()), 2)
gone = os.path.join(tmp, 'gone.py')
w2.settings.push_recent(gone)
w2._open_recent(gone)
check('missing dropped', gone in w2.settings.get_recent(), False)

# empty session -> startup screen, no tabs
w2.settings.save_session([], 0)
w3 = MainWindow(Settings())
check('empty session welcome', w3.stack.currentWidget() is w3.welcome, True)
check('empty session no tabs', w3.tabs.count(), 0)

print('fails:', fails)
sys.exit(1 if fails else 0)
