"""Word (.docx) import/export: markers, tables, pictures.

Plain-text buffer <-> real Word formatting. Tables travel as `| a | b |`
markdown lines, photos as `![alt](src)` references.
"""

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor

from smoothcursor.core.settings import Settings


def _docx_cell_fill(docx_cell):
    """Hex fill like '#c6efce' from a Word cell's shading, else None."""
    try:
        tc = docx_cell._tc
        tcPr = tc.find(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tcPr")
        if tcPr is None:
            return None
        shd = tcPr.find(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd")
        if shd is None:
            return None
        fill = shd.get(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill")
        if not fill or fill.lower() in ("auto", "ffffff", "none"):
            # FFFFFF is the default (no intentional fill).
            if not fill or fill.lower() in ("auto", "none"):
                return None
            return None
        fill = fill.strip()
        if len(fill) == 6 and all(c in "0123456789abcdefABCDEF"
                                  for c in fill):
            return "#" + fill.lower()
    except Exception:
        pass
    return None


def _set_docx_cell_fill(docx_cell, hex_color):
    """Apply cell shading; silently ignores bad input."""
    if not hex_color:
        return
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) != 6:
        return
    try:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tcPr = docx_cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color.upper())
        tcPr.append(shd)
    except Exception:
        pass


def _qt_cell_fill_hex(qdoc, qtable, row, col):
    """Header/fill color of a live QTextTableCell, else None."""
    try:
        cell = qtable.cellAt(row, col)
        cfmt = cell.format()
        bg = cfmt.background()
        if bg.style() != Qt.NoBrush:
            c = bg.color()
            return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())
        blk = cell.firstCursorPosition().block()
        it = blk.begin()
        while not it.atEnd():
            frag = it.fragment()
            it += 1
            fbg = frag.charFormat().background()
            if fbg.style() != Qt.NoBrush:
                c = fbg.color()
                return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())
    except Exception:
        pass
    return None


def docx_available():
    try:
        import docx  # noqa: F401
        return True
    except ImportError:
        return False


def is_docx(path):
    return path.lower().endswith(".docx")


def looks_like_docx(path):
    """True when the file has a ZIP container magic ('PK')."""
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"PK"
    except OSError:
        return False


def _iter_docx_blocks(document):
    """Yield ("para", Paragraph) / ("table", Table) in document order."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxPara
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield "para", DocxPara(child, document)
        elif isinstance(child, CT_Tbl):
            yield "table", DocxTable(child, document)


def _run_image(run, document):
    """(blob, ext) for a run's inline picture, else None."""
    try:
        blips = run._element.xpath(".//a:blip")
        if not blips:
            return None
        rid = blips[0].get("{http://schemas.openxmlformats.org/"
                           "officeDocument/2006/relationships}embed")
        part = document.part.related_parts.get(rid)
        if part is None or not getattr(part, "blob", None):
            return None
        ctype = part.content_type or ""
        ext = ctype.split("/")[-1].lower() if "/" in ctype else "png"
        ext = {"jpeg": "jpg", "pjpeg": "jpg"}.get(ext, ext)
        if not ext.isalnum():
            ext = "png"
        return part.blob, ext
    except Exception:
        return None


def _save_imported_image(blob, ext, hint):
    """Persist an imported picture to the media dir; returns its path."""
    media = os.path.join(Settings.backup_dir(), "media")
    try:
        os.makedirs(media, exist_ok=True)
    except OSError:
        return None
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", hint or "image").strip("_") \
        or "image"
    dest = os.path.join(media, f"{safe}.{ext}")
    for i in range(1, 1000):
        if not os.path.exists(dest):
            break
        dest = os.path.join(media, f"{safe}_{i}.{ext}")
    try:
        with open(dest, "wb") as f:
            f.write(blob)
        return dest
    except OSError:
        return None


def _extract_run_image_md(run, document, hint):
    """`![hint](path)` for a run's inline picture (saved to the media dir)."""
    found = _run_image(run, document)
    if found is None:
        return ""
    dest = _save_imported_image(found[0], found[1], hint)
    return f"![{hint}]({dest})" if dest is not None else ""


def _docx_table_markdown(table):
    """Word table cells as markdown lines (first row treated as header)."""
    rows = [[c.text.strip() for c in row.cells] for row in table.rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |",
             "|" + "|".join("---" for _ in rows[0]) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines


def docx_to_document(path, qdoc):
    """Load a .docx into a QTextDocument with real character formatting.

    Headings become '# ' prefixed lines (the level is stored in the run
    formatting round trip via the heading style on save). Character
    formatting (bold/italic/underline/highlight/color) is applied as
    QTextCharFormats so the editor renders it natively. Word tables become
    real editable QTextTable objects (first row bold header) and inline
    pictures become `![…](…)` refs (saved to the media dir) so both
    round-trip through the writer.
    """
    import docx  # python-docx
    from docx.enum.text import WD_COLOR_INDEX
    from PySide6.QtGui import QTextTableFormat

    palette_text = QColor("#ffffff")  # docxView text color (theme QSS)
    default_fg = QColor("#000000")

    def fmt_for(run, heading=False):
        fmt = QTextCharFormat()
        if run.bold:
            fmt.setFontWeight(QFont.Bold)
        if run.italic:
            fmt.setFontItalic(True)
        if run.underline:
            fmt.setFontUnderline(True)
        if run.font.highlight_color:
            color_map = {
                WD_COLOR_INDEX.YELLOW: "#ffff00",
                WD_COLOR_INDEX.BRIGHT_GREEN: "#00ff00",
                WD_COLOR_INDEX.TURQUOISE: "#00ffff",
                WD_COLOR_INDEX.PINK: "#ff00ff",
                WD_COLOR_INDEX.BLUE: "#0000ff",
                WD_COLOR_INDEX.RED: "#ff0000",
                WD_COLOR_INDEX.DARK_YELLOW: "#808000",
                WD_COLOR_INDEX.GRAY_50: "#808080",
            }
            hex_color = color_map.get(run.font.highlight_color, "#ffff00")
            fmt.setBackground(QColor(hex_color))
        if run.font.color and run.font.color.rgb:
            c = QColor("#" + str(run.font.color.rgb))
            if c != default_fg:
                fmt.setForeground(c)
        if run.font.name:
            fmt.setFontFamilies([run.font.name])
        if run.font.size:
            fmt.setFontPointSize(run.font.size.pt)
        return fmt

    def with_defaults(fmt):
        if fmt.fontPointSize() <= 0:
            fmt.setFontPointSize(11.0)
        if fmt.fontFamilies() is None or not fmt.fontFamilies():
            fmt.setFontFamilies(["Calibri"])
        return fmt

    document = docx.Document(path)
    qdoc.clear()
    cursor = QTextCursor(qdoc)
    first = True
    img_no = 0

    def emit_line(text):
        nonlocal first, cursor
        if not first:
            cursor.insertBlock()
        first = False
        cursor.insertText(text)

    def emit_table(docx_table):
        """Insert a real QTextTable for a python-docx table."""
        nonlocal first, cursor, img_no
        rows = list(docx_table.rows)
        if not rows:
            return
        width = max(len(r.cells) for r in rows)
        if not first:
            cursor.movePosition(QTextCursor.End)
            cursor.insertBlock()
        else:
            cursor.movePosition(QTextCursor.Start)
        first = False
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderStyle(
            QTextTableFormat.BorderStyle_Solid)
        fmt.setCellPadding(4)
        fmt.setCellSpacing(0)
        table = cursor.insertTable(len(rows), width, fmt)
        for ri, docx_row in enumerate(rows):
            for ci in range(width):
                cell = table.cellAt(ri, ci)
                cc = cell.firstCursorPosition()
                if ci < len(docx_row.cells):
                    src = docx_row.cells[ci]
                    wrote = False
                    for pi, para in enumerate(src.paragraphs):
                        if pi > 0:
                            cc.insertBlock()
                        for run in para.runs:
                            if run.text:
                                cc.setCharFormat(
                                    with_defaults(fmt_for(run)))
                                cc.insertText(run.text)
                                wrote = True
                            md = _extract_run_image_md(
                                run, document, f"image{img_no}")
                            if md:
                                img_no += 1
                                cc.insertText(md)
                                wrote = True
                        if not para.runs and para.text:
                            cc.insertText(para.text)
                            wrote = True
                    fill = _docx_cell_fill(src)
                    if fill:
                        try:
                            cf = cell.format()
                            cf.setBackground(QColor(fill))
                            cell.setFormat(cf)
                        except Exception:
                            pass
                    # First row is the header: ensure bold.
                    if ri == 0:
                        start = cell.firstCursorPosition().position()
                        end = cell.lastCursorPosition().position()
                        if end > start:
                            sel = cell.firstCursorPosition()
                            sel.setPosition(end, QTextCursor.KeepAnchor)
                            bold = QTextCharFormat()
                            bold.setFontWeight(QFont.Bold)
                            if fill:
                                bold.setBackground(QColor(fill))
                            sel.mergeCharFormat(bold)
                        elif not wrote:
                            fmt0 = with_defaults(QTextCharFormat())
                            if fill:
                                fmt0.setBackground(QColor(fill))
                            cc.setCharFormat(fmt0)
                    elif fill:
                        start = cell.firstCursorPosition().position()
                        end = cell.lastCursorPosition().position()
                        if end > start:
                            sel = cell.firstCursorPosition()
                            sel.setPosition(end, QTextCursor.KeepAnchor)
                            bg = QTextCharFormat()
                            bg.setBackground(QColor(fill))
                            sel.mergeCharFormat(bg)
                else:
                    pass
        # Reset the append cursor to the end so the next paragraph or
        # table does not land inside this table's last cell.
        cursor = QTextCursor(qdoc)
        cursor.movePosition(QTextCursor.End)

    for kind, item in _iter_docx_blocks(document):
        if kind == "table":
            emit_table(item)
            continue
        para = item
        style = (para.style.name or "") if para.style is not None else ""
        is_heading = style.startswith("Heading")
        prefix = ""
        if is_heading:
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 1
            prefix = "#" * level + " "
        if not para.runs:
            emit_line(prefix + para.text if para.text else "")
            continue
        if not first:
            cursor.insertBlock()
        first = False
        cursor.insertText(prefix)
        for run in para.runs:
            if run.text:
                # Build the full format FIRST (including the run's font
                # name/size defaults), then insert the text with that format
                # in one step. Insert-then-merge let Qt extend the previous
                # run's char format over the newly inserted text
                # (insertText inherits the cursor's current char format),
                # smearing bold/color across runs.
                fmt = fmt_for(run)
                if fmt.fontPointSize() <= 0:
                    fmt.setFontPointSize(11.0)
                if fmt.fontFamilies() is None or not fmt.fontFamilies():
                    fmt.setFontFamilies(["Calibri"])
                cursor.setCharFormat(fmt)
                cursor.insertText(run.text)
            md = _extract_run_image_md(run, document, f"image{img_no}")
            if md:
                img_no += 1
                cursor.insertText(md)
    cursor.movePosition(QTextCursor.Start)
    return qdoc


def docx_to_text(path):
    """Extract text from a .docx file, encoding formatting as inline markers.

    Markers: **bold**, *italic*, __underline__, ==highlight==,
    {color:RRGGBB}…{/color}. Word tables become `| a | b |` lines and inline
    pictures become `![…](…)` refs. The editor stays a plain-text buffer;
    the writer converts markers back to real Word formatting on save.
    """
    import docx  # python-docx

    def encode_runs(paragraph, document, counter):
        parts = []
        for run in paragraph.runs:
            text = run.text
            md = _extract_run_image_md(run, document, f"image{counter[0]}")
            if md:
                counter[0] += 1
            if not text:
                if md:
                    parts.append(md)
                continue
            lead = ""
            trail = ""
            if run.bold:
                lead += "**"
                trail = "**" + trail
            if run.italic:
                lead += "*"
                trail = "*" + trail
            if run.underline:
                lead += "__"
                trail = "__" + trail
            if run.font.highlight_color:
                lead += "=="
                trail = "==" + trail
            color = run.font.color.rgb if run.font.color and \
                run.font.color.rgb else None
            if color:
                lead += "{color:%s}" % color
                trail = "{/color}" + trail
            if run.bold or run.italic or run.underline or \
                    run.font.highlight_color or color:
                parts.append(lead + text + trail)
            else:
                parts.append(text)
            if md:
                parts.append(md)
        return "".join(parts)

    document = docx.Document(path)
    lines = []
    counter = [0]
    for kind, item in _iter_docx_blocks(document):
        if kind == "table":
            lines.extend(_docx_table_markdown(item))
            continue
        para = item
        style = (para.style.name or "") if para.style is not None else ""
        text = encode_runs(para, document, counter)
        if style.startswith("Heading"):
            try:
                level = int(style.split()[-1])
            except ValueError:
                level = 1
            lines.append("#" * level + " " + text)
        elif text.strip() or (lines and lines[-1].strip()):
            lines.append(text)
    return "\n".join(lines)

# Marker regexes shared by the docx writer. Longest/most-specific first:
# bold+italic, bold, underline, highlight, italic, color span.
_MD_TOKEN = re.compile(
    r"(\*\*\*(.+?)\*\*\*)"                          # 1,2 ***bold italic***
    r"|(\*\*(.+?)\*\*)"                             # 3,4 **bold**
    r"|(__(.+?)__)"                                 # 5,6 __underline__
    r"|(\{\{(.+?)\}\})"                             # 7,8 ==highlight== (alt)
    r"|(\*(.+?)\*)"                                 # 9,10 *italic*
    r"|(\{color:([0-9a-fA-F]{6})\}(.*?)\{/color\})" # 11,12,13 color span
)

_IMAGE_TOKEN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")

_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def _split_table_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator_row(line):
    cells = _split_table_row(line)
    return bool(cells) and all(_SEPARATOR_CELL.match(c) for c in cells)


def _only_images(line):
    """[(alt, src)] when the line holds nothing but image tokens."""
    stripped = line.strip()
    if not stripped.startswith("!["):
        return None
    pos, out = 0, []
    for m in _IMAGE_TOKEN.finditer(stripped):
        if stripped[pos:m.start()].strip():
            return None
        out.append((m.group(1), m.group(2)))
        pos = m.end()
    if not out or stripped[pos:].strip():
        return None
    return out


def _resolve_image(src, base_dir):
    """Absolute path for an image reference, or None when missing."""
    src = src.strip()
    if os.path.isabs(src):
        return src if os.path.exists(src) else None
    if base_dir:
        cand = os.path.normpath(os.path.join(base_dir, src))
        if os.path.exists(cand):
            return cand
    return src if os.path.exists(src) else None


def _picture_width(path, max_inches=5.5):
    """Display width: native size capped at `max_inches` (needs PIL)."""
    try:
        from PIL import Image as _PILImage
        from docx.shared import Inches
        with _PILImage.open(path) as img:
            px = img.size[0] or 1
        return Inches(min(px / 150.0, max_inches))
    except Exception:
        try:
            from docx.shared import Inches
            return Inches(max_inches)
        except Exception:
            return None


def _add_docx_picture(run_or_para, image_path):
    """Attach a picture; returns True on success."""
    try:
        width = _picture_width(image_path)
        if width is None:
            run_or_para.add_picture(image_path)
        else:
            run_or_para.add_picture(image_path, width=width)
        return True
    except Exception:
        return False


def _add_docx_table(document_, rows):
    """Append a 'Table Grid' table; first row is the header when a
    `|---|---|` separator row follows it."""
    data = [_split_table_row(r) for r in rows]
    header = None
    if len(data) >= 2 and _is_separator_row(rows[1]):
        header, data = data[0], data[2:]
    if not data and header is None:
        return
    if not data:
        data = [header]
        header = None
    width = max(len(r) for r in data + ([header] if header else []))
    data = [r + [""] * (width - len(r)) for r in data]
    if header is not None:
        header = header + [""] * (width - len(header))
    table = document_.add_table(
        rows=len(data) + (1 if header is not None else 0), cols=width)
    try:
        table.style = "Table Grid"
    except Exception:
        pass
    if header is not None:
        for i, text in enumerate(header):
            cell = table.rows[0].cells[i]
            cell.text = text
            for run in cell.paragraphs[0].runs:
                run.bold = True
    # Fill body rows (the header occupies row 0 when present).
    for ri, row in enumerate(data):
        tr = table.rows[(1 if header is not None else 0) + ri]
        for i, text in enumerate(row):
            tr.cells[i].text = text


def _add_markers(paragraph, text):
    """Write marker-encoded text into a python-docx paragraph."""
    from docx.shared import RGBColor
    from docx.enum.text import WD_COLOR_INDEX
    pos = 0
    for m in _MD_TOKEN.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        if m.group(1):      # ***bold italic***
            run = paragraph.add_run(m.group(2))
            run.bold = True
            run.italic = True
        elif m.group(3):    # **bold**
            run = paragraph.add_run(m.group(4))
            run.bold = True
        elif m.group(5):    # __underline__
            run = paragraph.add_run(m.group(6))
            run.underline = True
        elif m.group(7):    # ==highlight== (alt syntax)
            run = paragraph.add_run(m.group(8))
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        elif m.group(9):    # *italic*
            run = paragraph.add_run(m.group(10))
            run.italic = True
        elif m.group(11):   # {color:…}…{/color}
            run = paragraph.add_run(m.group(13))
            run.font.color.rgb = RGBColor.from_string(m.group(12).upper())
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def _add_formatted_runs(paragraph, text, base_dir=""):
    """Marker text plus inline `![alt](src)` pictures (missing files stay
    literal so nothing is ever silently dropped)."""
    pos = 0
    for m in _IMAGE_TOKEN.finditer(text):
        if m.start() > pos:
            _add_markers(paragraph, text[pos:m.start()])
        resolved = _resolve_image(m.group(2), base_dir)
        if resolved is not None and \
                _add_docx_picture(paragraph.add_run(), resolved):
            pass
        else:
            paragraph.add_run(m.group(0))
        pos = m.end()
    if pos < len(text):
        _add_markers(paragraph, text[pos:])


def _add_image_paragraphs(document_, images, base_dir):
    """One paragraph per picture; unresolvable refs stay literal."""
    for alt, src in images:
        resolved = _resolve_image(src, base_dir)
        para = document_.add_paragraph()
        if resolved is not None and \
                _add_docx_picture(para.add_run(), resolved):
            continue
        para.add_run(f"![{alt}]({src})")


def _iter_format_runs(qdoc, start, end):
    """Yield (text, QTextCharFormat) for uniform-format runs in [start, end).

    Reads fragment boundaries directly — QTextCursor.charFormat() reports the
    format of the character *before* the position, which shifts run splits
    by one, so we never rely on it here.
    """
    block = qdoc.findBlock(start)
    while block.isValid() and block.position() <= end:
        block_start = block.position()
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            it += 1
            if not frag.isValid():
                continue
            fs, fe = frag.position(), frag.position() + len(frag.text())
            s, e = max(fs, start), min(fe, end)
            if e <= s:
                continue
            yield frag.text()[s - fs:e - fs], frag.charFormat()
        if not block.length():
            break
        block = block.next()


def _qtext_cell_blocks(qdoc, cell):
    """List of QTextBlocks belonging to a QTextTableCell."""
    sp = cell.firstCursorPosition().position()
    ep = cell.lastCursorPosition().position()
    start = qdoc.findBlock(sp)
    end = qdoc.findBlock(ep)
    blocks = []
    b = start
    guard = 0
    while b.isValid() and guard < 10000:
        blocks.append(b)
        if b == end:
            break
        b = b.next()
        guard += 1
    return blocks, sp, ep


def _add_qtext_table(document_, qtable, qdoc, styled_run, base_dir=""):
    """Append a Word table mirroring a live QTextTable (real tables)."""
    rows, cols = qtable.rows(), qtable.columns()
    if rows <= 0 or cols <= 0:
        return
    wtable = document_.add_table(rows=rows, cols=cols)
    try:
        wtable.style = "Table Grid"
    except Exception:
        pass
    for r in range(rows):
        for c in range(cols):
            try:
                cell = qtable.cellAt(r, c)
            except Exception:
                continue
            wcell = wtable.rows[r].cells[c]
            wcell.text = ""
            fill = _qt_cell_fill_hex(qdoc, qtable, r, c)
            if fill:
                _set_docx_cell_fill(wcell, fill)
            blocks, sp, ep = _qtext_cell_blocks(qdoc, cell)
            first_para = True
            for b in blocks:
                bs = max(b.position(), sp)
                be = min(b.position() + len(b.text()), ep)
                if be <= bs:
                    continue
                body = b.text()[bs - b.position():be - b.position()]
                if not body and len(blocks) == 1:
                    continue
                if first_para:
                    wpara = wcell.paragraphs[0]
                    first_para = False
                else:
                    wpara = wcell.add_paragraph()
                if _IMAGE_TOKEN.search(body):
                    _add_formatted_runs(wpara, body, base_dir)
                else:
                    wrote = False
                    for frag_text, fmt in _iter_format_runs(
                            qdoc, bs, be):
                        if frag_text:
                            if fill and fmt.background().style() != \
                                    Qt.NoBrush:
                                # Cell fill is exported as shading above;
                                # don't also smear it as yellow highlight.
                                fmt = QTextCharFormat(fmt)
                                fmt.clearBackground()
                            styled_run(wpara, frag_text, fmt)
                            wrote = True
                    if not wrote and body:
                        wpara.add_run(body)


def text_to_docx(path, text, document=None):
    """Write editor content back to .docx.

    With a QTextDocument (preferred), character formatting is read straight
    from the document's char formats. Without one (tests/CLI), inline
    markers (**bold**, *italic*, __underline__, ==highlight==,
    {color:…}…{/color}) are parsed instead. '#' line prefixes become
    headings either way. `| a | b |` table blocks become real Word tables
    and `![alt](src)` becomes a real picture (relative paths resolve
    against the saved file's directory).
    """
    import docx
    from docx.shared import Pt
    from docx.enum.text import WD_COLOR_INDEX
    document_ = docx.Document()
    base_dir = os.path.dirname(os.path.abspath(path))

    def styled_run(para, text, fmt):
        run = para.add_run(text)
        if fmt is not None:
            if fmt.fontWeight() == QFont.Bold:
                run.bold = True
            if fmt.fontItalic():
                run.italic = True
            if fmt.fontUnderline():
                run.underline = True
            if fmt.background().style() != Qt.NoBrush:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            brush = fmt.foreground()
            if brush.style() == Qt.SolidPattern and brush.color() != \
                    QColor("#ffffff") and brush.color() != \
                    QColor("#000000"):
                from docx.shared import RGBColor
                c = brush.color()
                run.font.color.rgb = RGBColor(c.red(), c.green(), c.blue())
            families = fmt.fontFamilies()
            if families:
                run.font.name = families[0]
            pt = fmt.fontPointSize()
            if pt > 0:
                from docx.shared import Pt
                run.font.size = Pt(pt)
        return run

    if document is not None:
        # Walk blocks in order. Real QTextTables (rich .docx tabs) export
        # via _add_qtext_table; legacy `|…|` pipe blocks (plain tabs) fall
        # back to the markdown table writer so both round-trip.
        block = document.firstBlock()
        while block.isValid():
            probe = QTextCursor(document)
            try:
                probe.setPosition(block.position())
                qtable = probe.currentTable()
            except Exception:
                qtable = None
            if qtable is not None:
                try:
                    anchor = qtable.cellAt(0, 0).firstCursorPosition() \
                        .position()
                except Exception:
                    anchor = None
                _add_qtext_table(document_, qtable, document, styled_run,
                                 base_dir)
                # Skip every block owned by this table.
                while block.isValid():
                    p2 = QTextCursor(document)
                    try:
                        p2.setPosition(block.position())
                        t2 = p2.currentTable()
                    except Exception:
                        t2 = None
                    if t2 is None:
                        break
                    try:
                        a2 = t2.cellAt(0, 0).firstCursorPosition() \
                            .position()
                    except Exception:
                        break
                    if anchor is not None and a2 != anchor:
                        break
                    block = block.next()
                continue
            line = block.text()
            heading = re.match(r"^(#{1,9})\s+(.*)$", line)
            if heading:
                level = min(max(len(heading.group(1)), 1), 9)
                body = heading.group(2)
                body_start = block.position() + len(line) - len(body)
                para = document_.add_heading("", level)
                if _IMAGE_TOKEN.search(body):
                    _add_formatted_runs(para, body, base_dir)
                else:
                    for frag_text, fmt in _iter_format_runs(
                            document, body_start, body_start + len(body)):
                        styled_run(para, frag_text, fmt)
                block = block.next()
                continue
            if not line.strip():
                document_.add_paragraph()
                block = block.next()
                continue
            if _TABLE_ROW.match(line):
                rows = []
                while block.isValid():
                    probe2 = QTextCursor(document)
                    try:
                        probe2.setPosition(block.position())
                        in_table = probe2.currentTable() is not None
                    except Exception:
                        in_table = False
                    if in_table or not _TABLE_ROW.match(block.text()):
                        break
                    rows.append(block.text())
                    block = block.next()
                _add_docx_table(document_, rows)
                continue
            body, body_start = line, block.position()
            images = _only_images(body)
            if images:
                _add_image_paragraphs(document_, images, base_dir)
                block = block.next()
                continue
            para = document_.add_paragraph()
            if _IMAGE_TOKEN.search(body):
                # Image markdown cuts across char-format fragments; parse
                # the paragraph from markers instead of slicing runs.
                _add_formatted_runs(para, body, base_dir)
            else:
                # One python-docx run per uniform char-format fragment.
                for frag_text, fmt in _iter_format_runs(
                        document, body_start, body_start + len(body)):
                    styled_run(para, frag_text, fmt)
            block = block.next()
    else:
        lines = text.split("\n")
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if _TABLE_ROW.match(line):
                rows = []
                while i < n and _TABLE_ROW.match(lines[i]):
                    rows.append(lines[i])
                    i += 1
                _add_docx_table(document_, rows)
                continue
            heading = re.match(r"^(#{1,9})\s+(.*)$", line)
            if heading:
                para = document_.add_heading(
                    "", min(max(len(heading.group(1)), 1), 9))
                _add_formatted_runs(para, heading.group(2), base_dir)
            elif _only_images(line):
                _add_image_paragraphs(document_, _only_images(line),
                                      base_dir)
            elif line.strip():
                para = document_.add_paragraph()
                _add_formatted_runs(para, line, base_dir)
            else:
                document_.add_paragraph()
            i += 1

    # Style runs that carry no explicit font with a consistent default.
    for para in document_.paragraphs:
        if para.style.name == "Normal":
            for run in para.runs:
                if not run.font.name:
                    run.font.name = "Calibri"
                if not run.font.size:
                    run.font.size = Pt(11)
    document_.save(path)
