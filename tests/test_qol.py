import os
_tmp_config = __import__('tempfile').mkdtemp(prefix='smoothcursor-test-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp_config, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp_config, 'data')
import sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor, QFont
app = QApplication([])
from smoothcursor.editor.editor import CodeEditor
from smoothcursor.core.settings import Settings, DEFAULTS
from smoothcursor.core.theme import THEMES

def make(text, lang='python', pos=None, sel=None):
    s = Settings()
    for k,v in DEFAULTS.items(): s.set(k,v)
    ed = CodeEditor(s, THEMES['dark'], language=lang)
    ed.setPlainText(text)
    c = ed.textCursor()
    if sel: c.setPosition(sel[0]); c.setPosition(sel[1], QTextCursor.KeepAnchor)
    elif pos is not None: c.setPosition(pos)
    else: c.movePosition(QTextCursor.End)
    ed.setTextCursor(c)
    return ed

fails=[]
def check(name, got, exp):
    ok = got==exp
    print(('PASS ' if ok else 'FAIL ')+name+('' if ok else ' got=%r exp=%r'%(got,exp)))
    if not ok: fails.append(name)

ed = make('x = 1'); ed.toggle_comment(); check('comment line', ed.toPlainText(), '# x = 1')
ed.toggle_comment(); check('uncomment line', ed.toPlainText(), 'x = 1')
ed = make('a\n\nb', sel=(0,4)); ed.toggle_comment(); check('comment sel skip blank', ed.toPlainText(), '# a\n\n# b')
ed.toggle_comment(); check('uncomment sel', ed.toPlainText(), 'a\n\nb')
ed = make('{"a": 1}', lang='json'); ed.toggle_comment(); check('json comment', ed.toPlainText(), '// {"a": 1}')
ed = make('    x = 1'); ed.toggle_comment(); check('indented comment', ed.toPlainText(), '    # x = 1')
ed = make('#x = 1'); ed.toggle_comment(); check('uncomment nospace', ed.toPlainText(), 'x = 1')
ed = make('\n  \n', pos=0); ed.toggle_comment(); check('comment blank noop', ed.toPlainText(), '\n  \n')

ed = make('ab', pos=1); ed.duplicate_line_or_selection()
check('dup line', ed.toPlainText(), 'ab\nab')
check('dup cursor col', ed.textCursor().positionInBlock(), 1)
ed = make('hello world', sel=(0,5)); ed.duplicate_line_or_selection()
check('dup sel', ed.toPlainText(), 'hellohello world')

ed = make('a\nb\nc', pos=2); ed.delete_lines(); check('del middle', ed.toPlainText(), 'a\nc')
ed = make('a\nb\nc', pos=0); ed.delete_lines(); check('del first', ed.toPlainText(), 'b\nc')
ed = make('a\nb\nc', pos=4); ed.delete_lines(); check('del last', ed.toPlainText(), 'a\nb')
ed = make('solo', pos=2); ed.delete_lines(); check('del solo', ed.toPlainText(), '')
ed = make('a\nb\nc', sel=(0,3)); ed.delete_lines(); check('del sel lines', ed.toPlainText(), 'c')

ed = make('a\nb\nc', pos=0); ed.move_lines(1); check('move down', ed.toPlainText(), 'b\na\nc')
ed = make('a\nb\nc', pos=2); ed.move_lines(1); check('move down 2', ed.toPlainText(), 'a\nc\nb')
ed = make('a\nb\nc', pos=4); ed.move_lines(1); check('move down noop', ed.toPlainText(), 'a\nb\nc')
ed = make('a\nb\nc', pos=0); ed.move_lines(-1); check('move up noop', ed.toPlainText(), 'a\nb\nc')
ed = make('a\nb\nc', pos=4); ed.move_lines(-1); check('move up', ed.toPlainText(), 'a\nc\nb')
ed = make('a\nb\nc', pos=2); ed.move_lines(-1); check('move up 2', ed.toPlainText(), 'b\na\nc')
ed = make('a\nb\nc', sel=(2,5)); ed.move_lines(-1); check('move sel up', ed.toPlainText(), 'b\nc\na')
ed = make('a\nb\nc', sel=(0,2)); ed.move_lines(1); check('move sel down', ed.toPlainText(), 'b\na\nc')
ed = make('a\nb\nc', sel=(0,3)); ed.move_lines(1); check('move 2 lines down', ed.toPlainText(), 'c\na\nb')
ed = make('a\nb\nc', sel=(0,5)); ed.move_lines(1); check('move sel down noop', ed.toPlainText(), 'a\nb\nc')
ed = make('solo', pos=2); ed.move_lines(1); check('move solo noop', ed.toPlainText(), 'solo')
ed = make('a\nb\nc', pos=3); ed.move_lines(1)
check('move keeps col', ed.textCursor().positionInBlock(), 1)
check('move lands line3', ed.textCursor().blockNumber(), 2)

ed = make('foo\n    bar', pos=0); ed.join_with_next(); check('join', ed.toPlainText(), 'foo bar')
ed = make('foo\nbar', pos=0); ed.join_with_next(); check('join nospace', ed.toPlainText(), 'foo bar')
ed = make('foo', pos=0); ed.join_with_next(); check('join noop', ed.toPlainText(), 'foo')
ed = make('foo\n', pos=0); ed.join_with_next(); check('join empty next', ed.toPlainText(), 'foo')

ed = make('plain\nboldme', pos=6)
c = ed.textCursor(); c.setPosition(6); c.setPosition(12, QTextCursor.KeepAnchor)
ed.setTextCursor(c); ed.apply_char_format(bold=True)
c = ed.textCursor(); c.setPosition(0); ed.setTextCursor(c)
ed.move_lines(1)
check('move text', ed.toPlainText(), 'boldme\nplain')
frag = ed.document().findBlockByNumber(0).begin().fragment()
check('move keeps bold', frag.charFormat().fontWeight() == QFont.Bold, True)

print('fails:', fails)
sys.exit(1 if fails else 0)
