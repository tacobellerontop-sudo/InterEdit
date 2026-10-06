import os
_tmp_config = __import__('tempfile').mkdtemp(prefix='smoothcursor-test-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp_config, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp_config, 'data')
import sys
import tempfile
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
app = QApplication([])
from smoothcursor import __version__
from smoothcursor.views.help import AboutDialog, ShortcutsDialog, SHORTCUTS
from smoothcursor.views.window import MainWindow
from smoothcursor.editor import spellcheck
from smoothcursor.editor.editor import CodeEditor
from smoothcursor.editor.rich import RichEditor
from smoothcursor.core.settings import Settings, DEFAULTS
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


# --- help dialogs ---
w = MainWindow(make_settings())
about = AboutDialog(w)
check('about title', 'SmoothCursor' in about.windowTitle(), True)
check('about version', __version__ in about.version_label.text(), True)
dlg = ShortcutsDialog(w)
check('shortcuts rows', dlg.table.rowCount(), len(SHORTCUTS))
check('shortcuts has print',
      any('Ctrl+P' in dlg.table.item(r, 1).text()
          for r in range(dlg.table.rowCount())), True)

# --- menu bar structure (single bar: no leftover toolbar) ---
from PySide6.QtWidgets import QToolBar
from PySide6.QtGui import QPixmap
from smoothcursor.core.theme import THEMES, build_qss
check('no toolbar', w.findChildren(QToolBar), [])
for theme_name in ('dark', 'light'):
    QApplication.instance().setStyleSheet(build_qss(THEMES[theme_name]))
    w.settings.set('theme', theme_name)
    w.apply_settings()
    pix = QPixmap(w.menuBar().size())
    w.menuBar().render(pix)
    check('menubar follows %s theme' % theme_name,
          pix.toImage().pixelColor(3, 3).name(),
          THEMES[theme_name]['panel'])
menus = [m.menu().title() for m in w.menuBar().actions()]
check('menu bar', menus, ['&File', '&Edit', '&View', '&Insert', '&Help'])
file_menu = [m.menu() for m in w.menuBar().actions()
             if m.menu().title() == '&File'][0]
labels = [a.text() for a in file_menu.actions()]
check('file has print/export/quit',
      (any('Print' in t for t in labels),
       any('PDF' in t for t in labels),
       any('Quit' in t for t in labels)), (True, True, True))
print_act = [a for a in file_menu.actions() if 'Print' in a.text()][0]
check('print shortcut', print_act.shortcut().toString(), 'Ctrl+P')
check('file has recent submenu',
      any(a.menu() is w.recent_menu for a in file_menu.actions()
          if a.menu() is not None), True)
w.settings.push_recent('/tmp/fake_recent.docx')
w._rebuild_recent_menu()
check('recent lists files',
      any('fake_recent' in a.text() for a in w.recent_menu.actions()),
      True)
edit_menu = [m.menu() for m in w.menuBar().actions()
             if m.menu().title() == '&Edit'][0]
prefs = [a for a in edit_menu.actions() if 'Preferences' in a.text()]
check('edit has preferences', len(prefs), 1)
check('prefs shortcut', prefs[0].shortcut().toString(), 'Ctrl+,')

# --- edit ops + view sync ---
w.new_file()
ed = w.current_editor()
ed.setPlainText('hello')
w._edit_op('selectAll')
check('menu selectAll', ed.textCursor().hasSelection(), True)
w._edit_op('copy')
cur = ed.textCursor()
cur.clearSelection()
cur.movePosition(QTextCursor.End)
ed.setTextCursor(cur)
w._edit_op('paste')
check('menu copy/paste', ed.toPlainText(), 'hellohello')
w._edit_op('undo')
check('menu undo', ed.toPlainText(), 'hello')
w._sync_view_menu()
check('view sync wrap', w.wrap_action.isChecked(), False)
w.close_tab(w.tabs.currentIndex())

# --- print reject path never touches a printer ---
from PySide6.QtPrintSupport import QPrintDialog
w.new_file()
orig_exec = QPrintDialog.exec
QPrintDialog.exec = lambda self: 0
try:
    w.print_current()
    check('print cancel noop', True, True)
finally:
    QPrintDialog.exec = orig_exec

# --- export pdf success path ---
from PySide6.QtWidgets import QFileDialog
tmp = tempfile.mkdtemp()
dest = os.path.join(tmp, 'ex.pdf')
orig_save = QFileDialog.getSaveFileName
QFileDialog.getSaveFileName = lambda *a, **k: (dest, 'PDF document (*.pdf)')
try:
    w.export_pdf()
    check('export pdf', os.path.exists(dest)
          and os.path.getsize(dest) > 0, True)
finally:
    QFileDialog.getSaveFileName = orig_save
QFileDialog.getSaveFileName = lambda *a, **k: ('', '')
try:
    w.export_pdf()
    check('export cancel noop', True, True)
finally:
    QFileDialog.getSaveFileName = orig_save

# --- spell backend (hunspell present in this image) ---
check('spell available', spellcheck.spell_available(), True)
check('spell check',
      (spellcheck.is_misspelled('hello'),
       spellcheck.is_misspelled('zxqy'),
       spellcheck.is_misspelled('HTML')), (False, True, False))
check('spell skips', (spellcheck.is_skippable('a'),
                      spellcheck.is_skippable('README')), (True, True))
sugs = spellcheck.suggestions_for('helo')
check('spell suggestions', any('hell' in s for s in sugs), True)
check('spell add word', spellcheck.add_to_user_dict('smothconsumer'), True)
check('spell added ok', spellcheck.is_misspelled('smothconsumer'), False)
check('spell dict file',
      'smothconsumer' in open(spellcheck.user_dict_path()).read(), True)

# --- highlighter attach rules + live toggle ---
s = make_settings()
py = CodeEditor(s, THEMES['dark'], language='python')
check('no spell in code', py.spell_highlighter.is_active(), False)
md = CodeEditor(s, THEMES['dark'], language=None)
check('spell in prose', md.spell_highlighter.is_active(), True)
md.setPlainText('hello zxqy')
first = md.document().firstBlock()
ranges = [(r.start, r.length) for r in first.layout().formats()]
check('underline on zxqy', (6, 4) in ranges, True)
s.set('spellcheck', False)
md.apply_settings()
check('spell toggle off', md.spell_highlighter.is_active(), False)
s.set('spellcheck', True)
md.apply_settings()
red = RichEditor(s, THEMES['dark'])
check('spell in rich', red.spell_highlighter.is_active(), True)

# --- context-menu spelling sections (fake menus, no modal loop) ---
class FakeSig:
    def __init__(self):
        self.cb = None
    def connect(self, cb):
        self.cb = cb


class FakeAction:
    def __init__(self, text):
        self._t = text
        self.triggered = FakeSig()
    def text(self):
        return self._t


class FakeMenu:
    def __init__(self):
        self.items = []
    def addAction(self, text):
        a = FakeAction(text)
        self.items.append(a)
        return a
    def addSeparator(self):
        self.items.append('---')
    def exec(self, pos=None):
        pass
    def deleteLater(self):
        pass


class FakeEvent:
    def __init__(self, pos, glob):
        self._pos, self._glob = pos, glob
    def pos(self):
        return self._pos
    def globalPos(self):
        return self._glob


def editor_point(editor, word_start):
    cur = editor.textCursor()
    cur.setPosition(word_start)
    rect = editor.cursorRect(cur)
    vp = QPoint(rect.left() + 3, rect.center().y())
    return vp + editor.viewport().pos(), editor.viewport().mapToGlobal(vp)


orig_standard = CodeEditor.createStandardContextMenu
orig_rich_standard = RichEditor.createStandardContextMenu
captured = {}


def fake_standard(self):
    m = FakeMenu()
    captured['menu'] = m
    return m


CodeEditor.createStandardContextMenu = fake_standard
RichEditor.createStandardContextMenu = fake_standard
try:
    md2 = CodeEditor(make_settings(), THEMES['dark'], language=None)
    md2.resize(500, 400)
    md2.show()
    md2.setPlainText('say helo now')
    pos, glob = editor_point(md2, 4)
    md2.contextMenuEvent(FakeEvent(pos, glob))
    items = [i.text() if hasattr(i, 'text') else i
             for i in captured['menu'].items]
    check('code suggestions offered',
          any('hello' in t for t in items), True)
    check('code add-to-dict offered',
          any('dictionary' in t for t in items), True)
    # apply the first suggestion
    sug = [i for i in captured['menu'].items
           if hasattr(i, 'text') and 'hello' in i.text()][0]
    sug.triggered.cb()
    check('suggestion replaces', 'hello' in md2.toPlainText(), True)

    md2.setPlainText('say hello now')
    pos, glob = editor_point(md2, 4)
    md2.contextMenuEvent(FakeEvent(pos, glob))
    items2 = [i.text() if hasattr(i, 'text') else i
              for i in captured['menu'].items]
    check('no section for good word',
          not any('dictionary' in t for t in items2), True)

    red2 = RichEditor(make_settings(), THEMES['dark'])
    red2.resize(500, 400)
    red2.show()
    red2.setPlainText('say helo now')
    pos, glob = editor_point(red2, 4)
    red2.contextMenuEvent(FakeEvent(pos, glob))
    items3 = [i.text() if hasattr(i, 'text') else i
              for i in captured['menu'].items]
    check('rich suggestions offered',
          any('hello' in t for t in items3), True)
finally:
    CodeEditor.createStandardContextMenu = orig_standard
    RichEditor.createStandardContextMenu = orig_rich_standard

# --- unavailable backend degrades silently (restored afterwards) ---
orig_find = spellcheck._find_hunspell_lib
spellcheck._find_hunspell_lib = lambda: None
spellcheck.reset_checker()
try:
    check('spell unavailable', spellcheck.spell_available(), False)
    check('misspelled w/o backend', spellcheck.is_misspelled('zxqy'), False)
    check('suggest w/o backend', spellcheck.suggestions_for('helo'), [])
    check('add w/o backend', spellcheck.add_to_user_dict('zzword'), False)
    md3 = CodeEditor(make_settings(), THEMES['dark'], language=None)
    md3.resize(300, 200)
    md3.show()
    md3.setPlainText('zxqy words here')
    from PySide6.QtGui import QPixmap
    md3.render(QPixmap(300, 200))
    check('highlight w/o backend ok', True, True)
finally:
    spellcheck._find_hunspell_lib = orig_find
    spellcheck.reset_checker()
check('spell restored', spellcheck.spell_available(), True)

# --- settings dialog spell checkbox ---
from smoothcursor.core.settings import SettingsDialog
s5 = make_settings()
d5 = SettingsDialog(s5)
d5.spell_check.setChecked(False)
d5.accept()
check('spell setting persists', s5.get('spellcheck'), False)

print('fails:', fails)
sys.exit(1 if fails else 0)
