import os
_tmp_config = __import__('tempfile').mkdtemp(prefix='smoothcursor-test-')
os.environ['XDG_CONFIG_HOME'] = os.path.join(_tmp_config, 'config')
os.environ['XDG_DATA_HOME'] = os.path.join(_tmp_config, 'data')
import sys
import tempfile
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor, QTextDocument
app = QApplication([])
from smoothcursor.views.window import (
    FILE_FILTER, OPEN_FILTER, SAVE_FILTER, MainWindow, is_rich_document,
)
from smoothcursor.editor.rich import RichEditor
from smoothcursor.core.settings import Settings, DEFAULTS
from smoothcursor.core.theme import THEMES
from smoothcursor.documents.html_io import (
    html_to_document, is_html, looks_like_html, text_to_html,
)
from smoothcursor.documents.odt_io import (
    is_odt, looks_like_odt, odt_available, odt_to_document, odt_to_text,
    text_to_odt,
)
from smoothcursor.documents.pdf_io import export_qdoc_to_pdf, is_pdf

fails = []
def check(name, got, exp):
    ok = got == exp
    print(('PASS ' if ok else 'FAIL ') + name +
          ('' if ok else ' got=%r exp=%r' % (got, exp)))
    if not ok:
        fails.append(name)


def make_rich():
    s = Settings()
    for k, v in DEFAULTS.items():
        s.set(k, v)
    return RichEditor(s, THEMES['dark'])


# --- format detection + window routing (no optional deps needed) ---
check('is_odt', (is_odt('a.odt'), is_odt('a.docx')), (True, False))
check('is_html', (is_html('a.html'), is_html('a.htm'), is_html('a.txt')),
      (True, True, False))
check('is_pdf', (is_pdf('a.pdf'), is_pdf('a.odt')), (True, False))
check('is_rich', (is_rich_document('a.docx'), is_rich_document('a.odt'),
                  is_rich_document('a.html'), is_rich_document('a.htm'),
                  is_rich_document('a.py')),
      (True, True, True, True, False))
check('filters mention odt/html',
      ('*.odt' in FILE_FILTER, '*.html' in FILE_FILTER,
       '*.pdf' in SAVE_FILTER, '*.pdf' not in OPEN_FILTER),
      (True, True, True, True))
check('looks_like_html',
      (looks_like_html.__name__,), ('looks_like_html',))

w = MainWindow(Settings())
for path, kind in (('/tmp/x.odt', 'RichEditor'), ('/tmp/x.html', 'RichEditor'),
                   ('/tmp/x.py', 'CodeEditor')):
    ed = w._make_editor(file_path=path)
    check('editor for ' + path, type(ed).__name__, kind)
    ed.deleteLater()
w.deleteLater()

tmp = tempfile.mkdtemp()

# --- HTML (Qt native, always available) ---
red = make_rich()
red.insert_real_table(1, 2, True, header_fill="#d6e4f0")
tbl = red.textCursor().currentTable()
tbl.cellAt(1, 0).firstCursorPosition().insertText("a")
tbl.cellAt(1, 1).firstCursorPosition().insertText("b")
hp = os.path.join(tmp, "t.html")
text_to_html(hp, "", document=red.document())
with open(hp, encoding="utf-8") as f:
    html = f.read()
check('html has table', ("<table" in html, "Header 1" in html), (True, True))
qdoc = QTextDocument()
html_to_document(hp, qdoc)
blk = qdoc.firstBlock()
has_table = False
while blk.isValid():
    probe = QTextCursor(qdoc)
    probe.setPosition(blk.position())
    if probe.currentTable() is not None:
        has_table = True
        break
    blk = blk.next()
check('html reimport table', has_table, True)
check('html reimport text',
      ("Header 1" in qdoc.toPlainText(), " b" in qdoc.toPlainText()
       or "\nb" in qdoc.toPlainText()),
      (True, True))
check('looks_like_html file', looks_like_html(hp), True)
check('looks_like_html code', looks_like_html(__file__), False)
text_to_html(os.path.join(tmp, "m.html"),
             "Hello\n\n![pic](/nonexistent.png)\n")
with open(os.path.join(tmp, "m.html"), encoding="utf-8") as f:
    marker_html = f.read()
check('html marker img', ("<img" in marker_html, "Hello" in marker_html),
      (True, True))

# --- PDF export (Qt native, always available) ---
pdf = os.path.join(tmp, "t.pdf")
export_qdoc_to_pdf(red.document(), pdf)
check('pdf written', os.path.exists(pdf) and os.path.getsize(pdf) > 0, True)

# --- window-level save/load for html + pdf ---
w2 = MainWindow(Settings())
w2.new_file()
ed2 = w2.current_editor()
check('new file is rich', type(ed2).__name__, "RichEditor")
ed2.insert_real_table(1, 1, True)
hp2 = os.path.join(tmp, "w.html")
check('window save html', w2._write_editor(ed2, hp2), True)
check('window html exists', os.path.exists(hp2), True)
w2b = MainWindow(Settings())
check('window open html', w2b.open_path(hp2), True)
opened = w2b.current_editor()
check('opened html is rich', type(opened).__name__, "RichEditor")
pdf2 = os.path.join(tmp, "w.pdf")
check('window save pdf', w2._write_editor(ed2, pdf2), True)
w2.deleteLater()
w2b.deleteLater()

# --- ODT (needs odfpy; skip gracefully without it) ---
if odt_available():
    op = os.path.join(tmp, "t.odt")
    text_to_odt(op, "# Report\n\nHello **bold**.\n\n"
                    "| Name | Age |\n|------|-----|\n| Ann | 30 |")
    check('odt written', os.path.exists(op), True)
    check('looks_like_odt', looks_like_odt(op), True)
    md = odt_to_text(op)
    check('odt markers', ("# Report" in md, "**bold**" in md,
                           "| Ann | 30 |" in md), (True, True, True))
    red3 = make_rich()
    red3.insert_real_table(1, 2, True, header_fill="#c6efce")
    t3 = red3.textCursor().currentTable()
    t3.cellAt(1, 0).firstCursorPosition().insertText("x")
    t3.cellAt(1, 1).firstCursorPosition().insertText("y")
    rp = os.path.join(tmp, "r.odt")
    text_to_odt(rp, "", document=red3.document())
    q3 = QTextDocument()
    odt_to_document(rp, q3)
    plain3 = q3.toPlainText()
    check('odt rich cells',
          all(x in plain3 for x in ("Header 1", "Header 2", "x", "y")),
          True)
    b3 = q3.firstBlock()
    found_fill = None
    while b3.isValid():
        pp = QTextCursor(q3)
        pp.setPosition(b3.position())
        t = pp.currentTable()
        if t is not None:
            from smoothcursor.documents.docx_io import _qt_cell_fill_hex
            found_fill = _qt_cell_fill_hex(q3, t, 0, 0)
            break
        b3 = b3.next()
    check('odt fill round-trip', found_fill, "#c6efce")
    # images embed + reimport as refs
    from PIL import Image
    img = os.path.join(tmp, "pic.png")
    Image.new("RGB", (400, 300), "red").save(img)
    red4 = make_rich()
    red4.setPlainText("See ![pic](%s)." % img)
    ip = os.path.join(tmp, "i.odt")
    text_to_odt(ip, red4.toPlainText(), document=red4.document())
    from odf.opendocument import load as _load
    check('odt embeds image', bool(_load(ip).Pictures), True)
    md4 = odt_to_text(ip)
    check('odt image ref', "![image" in md4, True)
    # window-level odt save/open
    w3 = MainWindow(Settings())
    w3.new_file()
    ed3 = w3.current_editor()
    ed3.insert_real_table(1, 1, True)
    wp = os.path.join(tmp, "w.odt")
    check('window save odt', w3._write_editor(ed3, wp), True)
    w3b = MainWindow(Settings())
    check('window open odt', w3b.open_path(wp), True)
    check('opened odt is rich',
          type(w3b.current_editor()).__name__, "RichEditor")
    check('opened odt editor kind',
          type(w3._make_editor(file_path=wp)).__name__, "RichEditor")
    w3.deleteLater()
    w3b.deleteLater()
else:
    print("SKIP odt round-trips (odfpy not installed)")

print('fails:', fails)
sys.exit(1 if fails else 0)
