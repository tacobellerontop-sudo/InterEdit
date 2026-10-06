import os
_tmp_config = __import__('tempfile').mkdtemp(prefix='smoothcursor-test-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp_config, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp_config, 'data')
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Qt
app = QApplication([])

from smoothcursor.editor.editor import CodeEditor
from smoothcursor.core.theme import THEMES

class FakeSettings(dict):
    def get(self, k, d=None):
        return self.get(k, d) if False else dict.get(self, k, d)

def make(text, cursor_at_end=True):
    from smoothcursor.core.settings import Settings, DEFAULTS
    s = Settings()
    for k, v in DEFAULTS.items():
        s.set(k, v)
    ed = CodeEditor(s, THEMES["dark"])
    ed.setPlainText(text)
    c = ed.textCursor()
    if cursor_at_end:
        c.movePosition(QTextCursor.End)
    ed.setTextCursor(c)
    return ed

def press_enter(ed):
    ed._smart_newline()
    return ed.toPlainText()

fails = []
def check(name, start, expected, cursor_end=True, mid=None):
    ed = make(start, cursor_at_end=cursor_end)
    if mid is not None:
        c = ed.textCursor(); c.setPosition(mid); ed.setTextCursor(c)
    got = press_enter(ed)
    ok = got == expected
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        print("  start:    %r" % start)
        print("  expected: %r" % expected)
        print("  got:      %r" % got)
        fails.append(name)

# 1. ordered list
check("ordered 1. -> 2.", "1. hello", "1. hello\n2. ")
check("ordered 1) -> 2)", "1) hello", "1) hello\n2) ")
check("ordered 9 -> 10", "9. nine", "9. nine\n10. ")
check("nested ordered", "    3. hi", "    3. hi\n    4. ")
# empty-item exit: cursor stays, marker removed
ed = make("1. "); press_enter(ed)
got = ed.toPlainText()
print(("PASS " if got == "" else "FAIL ") + "empty ordered exits (got %r)" % got)
if got != "": fails.append("empty ordered exits")

ed = make("- "); press_enter(ed)
got = ed.toPlainText()
print(("PASS " if got == "" else "FAIL ") + "empty bullet exits (got %r)" % got)
if got != "": fails.append("empty bullet exits")

check("bullet - continues", "- hello", "- hello\n- ")
check("bullet * continues", "* hello", "* hello\n* ")
ed = make("- [x] done"); got = press_enter(ed)
print(("PASS " if got == "- [x] done\n- [ ] " else "FAIL ") + "task resets (got %r)" % got)
if got != "- [x] done\n- [ ] ": fails.append("task resets")

check("quote continues", "> hello", "> hello\n> ")
ed = make("> "); press_enter(ed)
got = ed.toPlainText()
print(("PASS " if got == "" else "FAIL ") + "empty quote exits (got %r)" % got)
if got != "": fails.append("empty quote exits")

check("quote+list", "> 1. hi", "> 1. hi\n> 2. ")
check("colon indent", "def f():", "def f():\n    ")

# renumber forward: 1,2,4 -> enter after 2. gives 3 and fixes 4->4? let's test 1,3
ed = make("1. a\n2. b\n7. c")
c = ed.textCursor()
# move to end of line 2 ("2. b")
blk = ed.document().findBlockByNumber(1)
c.setPosition(blk.position() + len(blk.text()))
ed.setTextCursor(c)
got = press_enter(ed)
exp = "1. a\n2. b\n3. \n4. c"
print(("PASS " if got == exp else "FAIL ") + "renumber forward (got %r)" % got)
if got != exp: fails.append("renumber")

# pairs
ed = make(""); ed._handle_opening_pair("(")
print(("PASS " if ed.toPlainText() == "()" else "FAIL ") + "auto-close paren (got %r)" % ed.toPlainText())
if ed.toPlainText() != "()": fails.append("paren")

ed = make(""); ed._handle_opening_pair('"')
print(("PASS " if ed.toPlainText() == '""' else "FAIL ") + "auto-close quote")
if ed.toPlainText() != '""': fails.append("quote-pair")

# skip-over
ed = make("()")
c = ed.textCursor(); c.setPosition(1); ed.setTextCursor(c)
ed._handle_closing_skip(")")
pos = ed.textCursor().position()
print(("PASS " if pos == 2 else "FAIL ") + "skip-over closer (pos %r)" % pos)
if pos != 2: fails.append("skip")

# backspace pair
ed = make("()")
c = ed.textCursor(); c.setPosition(1); ed.setTextCursor(c)
ed._handle_backspace_pair()
print(("PASS " if ed.toPlainText() == "" else "FAIL ") + "backspace pair (got %r)" % ed.toPlainText())
if ed.toPlainText() != "": fails.append("backspace")

# brace expand
ed = make("{}")
c = ed.textCursor(); c.setPosition(1); ed.setTextCursor(c)
ed._smart_newline()
got = ed.toPlainText()
print(("PASS " if got == "{\n    \n}" else "FAIL ") + "brace expand (got %r)" % got)
if got != "{\n    \n}": fails.append("brace")

print("\n%d failures: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
