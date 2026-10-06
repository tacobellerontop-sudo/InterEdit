"""OpenDocument Text (.odt) import/export: formatting, tables, pictures.

Mirrors documents/docx_io.py so .odt tabs behave like .docx tabs: the
editor holds real QTextTable objects and character formatting, while this
module translates to/from ODF via odfpy (optional, same pattern as
python-docx for Word files).
"""

import os
import re
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor

from smoothcursor.core.settings import Settings
from smoothcursor.documents.docx_io import (
    _IMAGE_TOKEN,
    _MD_TOKEN,
    _TABLE_ROW,
    _is_separator_row,
    _iter_format_runs,
    _only_images,
    _qt_cell_fill_hex,
    _qtext_cell_blocks,
    _resolve_image,
    _save_imported_image,
    _split_table_row,
)

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def odt_available():
    try:
        import odf  # noqa: F401
        return True
    except ImportError:
        return False


def is_odt(path):
    return (path or "").lower().endswith(".odt")


def looks_like_odt(path):
    """True when the file is a ZIP whose mimetype is OpenDocument Text."""
    try:
        with zipfile.ZipFile(path) as zf:
            try:
                return zf.read("mimetype").strip() == \
                    b"application/vnd.oasis.opendocument.text"
            except KeyError:
                return False
    except Exception:
        return False


def _attr(elem, local):
    """Attribute value by local name, regardless of namespace."""
    try:
        attrs = getattr(elem, "attributes", None) or {}
        for (_ns, name), val in attrs.items():
            if name == local:
                return val
    except Exception:
        pass
    return None


def _norm_hex(value):
    if not value:
        return None
    value = value.strip()
    if _HEX_COLOR.match(value):
        return value.lower()
    return None


def _int_attr(elem, local, default=1):
    try:
        return max(1, int(_attr(elem, local) or default))
    except (TypeError, ValueError):
        return default


def _style_maps(doc):
    """({text style: props}, {cell style: fill}) from all style containers."""
    text_props, cell_fill = {}, {}
    for container in (getattr(doc, "styles", None),
                      getattr(doc, "automaticstyles", None)):
        try:
            nodes = container.childNodes
        except Exception:
            continue
        for st in nodes:
            if getattr(st, "tagName", None) != "style:style":
                continue
            name = _attr(st, "name")
            if not name:
                continue
            try:
                children = st.childNodes
            except Exception:
                continue
            for ch in children:
                tag = getattr(ch, "tagName", None)
                if tag == "style:text-properties":
                    props = text_props.setdefault(name, {})
                    fw = _attr(ch, "font-weight")
                    if fw and fw.lower() == "bold":
                        props["bold"] = True
                    fs = _attr(ch, "font-style")
                    if fs and fs.lower() == "italic":
                        props["italic"] = True
                    ul = _attr(ch, "text-underline-style")
                    if ul and ul.lower() not in ("none",):
                        props["underline"] = True
                    color = _norm_hex(_attr(ch, "color") or "")
                    if color and color != "#000000":
                        props["color"] = color
                    bg = _norm_hex(_attr(ch, "background-color") or "")
                    if bg:
                        props["bg"] = bg
                    fn = _attr(ch, "font-name")
                    if fn:
                        props["font"] = fn
                    sz = (_attr(ch, "font-size") or "").strip()
                    m = re.match(r"^([\d.]+)pt$", sz)
                    if m:
                        try:
                            props["size"] = float(m.group(1))
                        except ValueError:
                            pass
                elif tag == "style:table-cell-properties":
                    bg = _norm_hex(_attr(ch, "background-color") or "")
                    if bg:
                        cell_fill[name] = bg
    return text_props, cell_fill


def _odt_image_bytes(odt_path, href, doc):
    """Raw bytes for an ODT-internal image reference, else None."""
    if not href:
        return None, None
    href = href.split("?", 1)[0]
    if href.startswith("./"):
        href = href[2:]
    if "://" in href or href.startswith("/"):
        return None, None
    try:
        with zipfile.ZipFile(odt_path) as zf:
            try:
                data = zf.read(href)
            except KeyError:
                return None, None
    except Exception:
        data = None
    if data is None:
        try:
            pictures = getattr(doc, "Pictures", {}) or {}
            rec = pictures.get(href)
            if rec is not None and rec[1] not in (None, b""):
                content = rec[1]
                if isinstance(content, bytes):
                    data = content
        except Exception:
            pass
    if not data:
        return None, None
    ext = os.path.splitext(href)[1].lstrip(".").lower() or "png"
    ext = {"jpeg": "jpg", "pjpeg": "jpg"}.get(ext, ext)
    if not ext.isalnum():
        ext = "png"
    return data, ext


def _iter_node_runs(elem, text_props, odt_path, doc, counter, inherited=None):
    """Yield ('text', str, props) / ('break',) / ('image', md) depth-first."""
    inherited = dict(inherited or {})
    try:
        children = elem.childNodes
    except Exception:
        return
    for ch in children:
        tag = getattr(ch, "tagName", None)
        if tag is None or tag == "Text" or ":" not in tag:
            # odfpy character-data node: literal text.
            try:
                text = str(ch)
            except Exception:
                continue
            if text:
                yield ("text", text, dict(inherited))
            continue
        if tag == "text:span":
            props = dict(inherited)
            props.update(text_props.get(_attr(ch, "style-name") or "", {}))
            yield from _iter_node_runs(ch, text_props, odt_path, doc,
                                       counter, props)
        elif tag == "text:a":
            yield from _iter_node_runs(ch, text_props, odt_path, doc,
                                       counter, inherited)
        elif tag == "text:line-break":
            yield ("break",)
        elif tag in ("text:s", "text:tab"):
            yield ("text", "\t" if tag == "text:tab" else " ", dict(inherited))
        elif tag == "draw:frame":
            found = _frame_image_md(ch, odt_path, doc, counter)
            if found:
                yield ("image", found)
        elif tag in ("draw:image",):
            found = _href_image_md(_attr(ch, "href"), odt_path, doc, counter)
            if found:
                yield ("image", found)
        else:
            # Unknown inline element (e.g. text:bookmark): keep its text.
            try:
                text = "".join(
                    str(c) for c in ch.childNodes
                    if getattr(c, "tagName", None) is None)
            except Exception:
                text = ""
            if text:
                yield ("text", text, dict(inherited))


def _href_image_md(href, odt_path, doc, counter):
    data, ext = _odt_image_bytes(odt_path, href or "", doc)
    if data is None:
        return ""
    hint = f"image{counter[0]}"
    dest = _save_imported_image(data, ext, hint)
    if dest is None:
        return ""
    counter[0] += 1
    return f"![{hint}]({dest})"


def _frame_image_md(frame, odt_path, doc, counter):
    try:
        descendants = frame.getElementsByType(
            __import__("odf.draw", fromlist=["Image"]).Image)
    except Exception:
        descendants = []
    for img in descendants:
        md = _href_image_md(_attr(img, "href"), odt_path, doc, counter)
        if md:
            return md
    return ""


def _para_runs(elem, text_props, odt_path, doc, counter):
    """Runs of a text:p / text:h element (images included)."""
    return list(_iter_node_runs(elem, text_props, odt_path, doc, counter))


def _iter_odt_blocks(doc):
    """Yield ('para', elem) / ('table', elem) / ('list', elem) in order."""
    try:
        top = doc.text.childNodes
    except Exception:
        return
    for node in top:
        tag = getattr(node, "tagName", None)
        if tag in ("text:p", "text:h"):
            yield "para", node
        elif tag == "table:table":
            yield "table", node
        elif tag == "text:list":
            yield "list", node


def _list_paragraphs(list_elem):
    """Flatten text:list items to their text:p elements, in order."""
    out = []
    try:
        children = list_elem.childNodes
    except Exception:
        return out
    for item in children:
        if getattr(item, "tagName", None) not in (
                "text:list-item", "text:list-header"):
            continue
        try:
            sub = item.childNodes
        except Exception:
            continue
        for node in sub:
            tag = getattr(node, "tagName", None)
            if tag in ("text:p", "text:h"):
                out.append(node)
            elif tag == "text:list":
                out.extend(_list_paragraphs(node))
    return out


def _expand_table(table_elem):
    """Grid of cell elements; repeated rows/cols and covered cells kept."""
    grid = []
    try:
        children = table_elem.childNodes
    except Exception:
        return grid
    for row in children:
        if getattr(row, "tagName", None) != "table:table-row":
            continue
        for _ in range(_int_attr(row, "number-rows-repeated", 1)):
            cells = []
            try:
                row_children = row.childNodes
            except Exception:
                row_children = []
            for cell in row_children:
                tag = getattr(cell, "tagName", None)
                if tag not in ("table:table-cell", "table:covered-table-cell"):
                    continue
                for _ in range(_int_attr(
                        cell, "number-columns-repeated", 1)):
                    cells.append(cell if tag == "table:table-cell" else None)
            grid.append(cells)
    width = max((len(r) for r in grid), default=0)
    return [r + [None] * (width - len(r)) for r in grid]


def _cell_paragraphs(cell_elem):
    try:
        return [c for c in cell_elem.childNodes
                if getattr(c, "tagName", None) in ("text:p", "text:h")]
    except Exception:
        return []


def _fmt_from_props(props):
    fmt = QTextCharFormat()
    if props.get("bold"):
        fmt.setFontWeight(QFont.Bold)
    if props.get("italic"):
        fmt.setFontItalic(True)
    if props.get("underline"):
        fmt.setFontUnderline(True)
    if props.get("bg"):
        fmt.setBackground(QColor(props["bg"]))
    if props.get("color"):
        fmt.setForeground(QColor(props["color"]))
    if props.get("font"):
        fmt.setFontFamilies([props["font"]])
    if props.get("size"):
        try:
            fmt.setFontPointSize(float(props["size"]))
        except (TypeError, ValueError):
            pass
    return fmt


def _with_defaults(fmt):
    if fmt.fontPointSize() <= 0:
        fmt.setFontPointSize(11.0)
    if fmt.fontFamilies() is None or not fmt.fontFamilies():
        fmt.setFontFamilies(["Calibri"])
    return fmt


def odt_to_document(path, qdoc):
    """Load an .odt into a QTextDocument with real tables + formatting.

    Headings become '# ' prefixed lines, character formatting lands in
    QTextCharFormats, ODT tables become editable QTextTable objects (first
    row bold header) and embedded pictures become `![…](…)` refs saved to
    the media dir — the same model as .docx tabs.
    """
    from odf.opendocument import load as _load

    document = _load(path)
    text_props, cell_fill = _style_maps(document)
    qdoc.clear()
    cursor = QTextCursor(qdoc)
    first = True
    counter = [0]

    def emit_line(text):
        nonlocal first, cursor
        if not first:
            cursor.insertBlock()
        first = False
        cursor.insertText(text)

    def emit_runs(runs, prefix=""):
        nonlocal first, cursor
        if not runs:
            emit_line(prefix)
            return
        if not first:
            cursor.insertBlock()
        first = False
        if prefix:
            cursor.insertText(prefix)
        for run in runs:
            if run[0] == "break":
                cursor.insertBlock()
            elif run[0] == "image":
                cursor.insertText(run[1])
            else:
                parts = run[1].split("\n")
                for i, part in enumerate(parts):
                    if i:
                        cursor.insertBlock()
                    if part:
                        cursor.setCharFormat(
                            _with_defaults(_fmt_from_props(run[2])))
                        cursor.insertText(part)

    def emit_para(elem):
        tag = getattr(elem, "tagName", None)
        prefix = ""
        if tag == "text:h":
            try:
                level = min(max(int(_attr(elem, "outline-level") or 1), 1), 9)
            except (TypeError, ValueError):
                level = 1
            prefix = "#" * level + " "
        runs = _para_runs(elem, text_props, path, document, counter)
        if not runs:
            emit_line(prefix)
            return
        emit_runs(runs, prefix)

    def emit_table(table_elem):
        nonlocal first, cursor
        grid = _expand_table(table_elem)
        grid = [r for r in grid if any(c is not None for c in r)]
        if not grid:
            return
        width = max(len(r) for r in grid)
        if not first:
            cursor.movePosition(QTextCursor.End)
            cursor.insertBlock()
        else:
            cursor.movePosition(QTextCursor.Start)
        first = False
        from PySide6.QtGui import QTextTableFormat
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderStyle(QTextTableFormat.BorderStyle_Solid)
        fmt.setCellPadding(4)
        fmt.setCellSpacing(0)
        qtable = cursor.insertTable(len(grid), width, fmt)
        for ri, row in enumerate(grid):
            for ci in range(width):
                cell = qtable.cellAt(ri, ci)
                cc = cell.firstCursorPosition()
                src = row[ci] if ci < len(row) else None
                fill = None
                if src is not None:
                    fill = cell_fill.get(
                        _attr(src, "style-name") or "", None)
                    first_para = True
                    for para in _cell_paragraphs(src):
                        if not first_para:
                            cc.insertBlock()
                        first_para = False
                        for run in _para_runs(
                                para, text_props, path, document, counter):
                            if run[0] == "break":
                                cc.insertBlock()
                            elif run[0] == "image":
                                cc.insertText(run[1])
                            else:
                                parts = run[1].split("\n")
                                for i, part in enumerate(parts):
                                    if i:
                                        cc.insertBlock()
                                    if part:
                                        cc.setCharFormat(_with_defaults(
                                            _fmt_from_props(run[2])))
                                        cc.insertText(part)
                    if fill:
                        try:
                            cf = cell.format()
                            cf.setBackground(QColor(fill))
                            cell.setFormat(cf)
                        except Exception:
                            pass
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
        cursor = QTextCursor(qdoc)
        cursor.movePosition(QTextCursor.End)

    for kind, item in _iter_odt_blocks(document):
        if kind == "table":
            emit_table(item)
        elif kind == "list":
            for para in _list_paragraphs(item):
                emit_para(para)
        else:
            emit_para(item)
    cursor.movePosition(QTextCursor.Start)
    return qdoc


def odt_to_text(path):
    """Extract text from .odt, encoding formatting with docx-style markers.

    Markers: **bold**, *italic*, __underline__, ==highlight==,
    {color:RRGGBB}…{/color}. Tables become `| a | b |` lines and embedded
    pictures become `![…](…)` refs.
    """
    from odf.opendocument import load as _load

    document = _load(path)
    text_props, _cell_fill = _style_maps(document)
    counter = [0]

    def encode_runs(elem):
        parts = []
        for run in _para_runs(elem, text_props, path, document, counter):
            if run[0] == "image":
                parts.append(run[1])
                continue
            if run[0] == "break":
                parts.append("\n")
                continue
            text, props = run[1], run[2]
            if not text:
                continue
            lead, trail = "", ""
            if props.get("bold"):
                lead += "**"
                trail = "**" + trail
            if props.get("italic"):
                lead += "*"
                trail = "*" + trail
            if props.get("underline"):
                lead += "__"
                trail = "__" + trail
            if props.get("bg"):
                lead += "=="
                trail = "==" + trail
            color = props.get("color")
            if color:
                lead += "{color:%s}" % color.lstrip("#").upper()
                trail = "{/color}" + trail
            if lead:
                parts.append(lead + text + trail)
            else:
                parts.append(text)
        return "".join(parts)

    lines = []
    for kind, item in _iter_odt_blocks(document):
        if kind == "table":
            grid = _expand_table(item)
            rows = []
            for row in grid:
                cells = []
                for cell in row:
                    if cell is None:
                        cells.append("")
                    else:
                        cells.append(" ".join(
                            encode_runs(p).replace("\n", " ").strip()
                            for p in _cell_paragraphs(cell)).strip())
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            lines.append("| " + " | ".join(rows[0]) + " |")
            lines.append("|" + "|".join("---" for _ in rows[0]) + "|")
            lines.extend("| " + " | ".join(r) + " |" for r in rows[1:])
            continue
        paras = _list_paragraphs(item) if kind == "list" else [item]
        for para in paras:
            tag = getattr(para, "tagName", None)
            text = encode_runs(para)
            if tag == "text:h":
                try:
                    level = min(max(
                        int(_attr(para, "outline-level") or 1), 1), 9)
                except (TypeError, ValueError):
                    level = 1
                lines.append("#" * level + " " + text)
            elif text.strip() or (lines and lines[-1].strip()):
                lines.append(text)
    return "\n".join(lines)


class _OdtWriter:
    """odfpy document builder with cached text/cell styles."""

    def __init__(self):
        from odf.opendocument import OpenDocumentText
        self.doc = OpenDocumentText()
        self._text_styles = {}
        self._cell_styles = {}
        self._counter = 0

    def text_style(self, bold=False, italic=False, underline=False,
                   color=None, bg=None, font=None, size=None):
        key = (bool(bold), bool(italic), bool(underline), color, bg,
               font, size)
        if key in self._text_styles:
            return self._text_styles[key]
        from odf.style import Style, TextProperties
        if not any(key):
            self._text_styles[key] = None
            return None
        attrs = {}
        if bold:
            attrs["fontweight"] = "bold"
        if italic:
            attrs["fontstyle"] = "italic"
        if underline:
            attrs["textunderlinestyle"] = "solid"
        if color:
            attrs["color"] = color
        if bg:
            attrs["backgroundcolor"] = bg
        if font:
            attrs["fontname"] = font
        if size:
            try:
                attrs["fontsize"] = "%gpt" % float(size)
            except (TypeError, ValueError):
                pass
        name = f"sc{len(self._text_styles)}"
        st = Style(name=name, family="text")
        st.addElement(TextProperties(attributes=attrs))
        self.doc.automaticstyles.addElement(st)
        self._text_styles[key] = st
        return st

    def cell_style(self, fill):
        if not fill:
            return None
        if fill in self._cell_styles:
            return self._cell_styles[fill]
        from odf.style import Style, TableCellProperties
        name = f"sccell{len(self._cell_styles)}"
        st = Style(name=name, family="table-cell")
        st.addElement(TableCellProperties(
            attributes={"backgroundcolor": fill}))
        self.doc.automaticstyles.addElement(st)
        self._cell_styles[fill] = st
        return st

    def add_markers(self, para, text):
        """Marker-encoded text (**bold** etc.) as styled spans."""
        from odf.text import Span
        pos = 0
        for m in _MD_TOKEN.finditer(text):
            if m.start() > pos:
                para.addText(text[pos:m.start()])
            bold = bool(m.group(1) or m.group(3))
            italic = bool(m.group(1) or m.group(9))
            underline = bool(m.group(5))
            bg = None
            body = ""
            if m.group(1):
                body = m.group(2)
            elif m.group(3):
                body = m.group(4)
            elif m.group(5):
                body = m.group(6)
            elif m.group(7):
                body = m.group(8)
                bg = "#ffff00"
            elif m.group(9):
                body = m.group(10)
            elif m.group(11):
                body = m.group(13)
            color = None
            if m.group(11):
                color = "#" + m.group(12).upper()
            st = self.text_style(bold=bold, italic=italic,
                                 underline=underline, color=color, bg=bg)
            if st is not None:
                span = Span(stylename=st)
                span.addText(body)
                para.addElement(span)
            else:
                para.addText(body)
            pos = m.end()
        if pos < len(text):
            para.addText(text[pos:])

    def picture_size_cm(self, image_path, max_cm=14.0):
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(image_path) as img:
                w, h = img.size[0] or 1, img.size[1] or 1
        except Exception:
            return max_cm, max_cm * 0.75
        width_cm = min(w / 150.0 * 2.54, max_cm)
        return width_cm, width_cm * h / w

    def add_picture_frame(self, para, image_path):
        """Embed an image; False when missing (caller keeps it literal)."""
        from odf.draw import Frame, Image
        if not image_path or not os.path.exists(image_path):
            return False
        try:
            manifestfn = self.doc.addPictureFromFile(image_path)
        except Exception:
            return False
        try:
            w, h = self.picture_size_cm(image_path)
            frame = Frame(width=f"{w:.2f}cm", height=f"{h:.2f}cm",
                          anchortype="as-char")
            frame.addElement(Image(href=manifestfn))
            para.addElement(frame)
            return True
        except Exception:
            return False

    def add_runs(self, para, text, base_dir=""):
        """Marker text plus inline `![alt](src)` pictures."""
        from odf import text as _t
        pos = 0
        for m in _IMAGE_TOKEN.finditer(text):
            if m.start() > pos:
                self.add_markers(para, text[pos:m.start()])
            src = (m.group(2) or "").strip()
            resolved = None
            if src:
                if os.path.isabs(src):
                    resolved = src if os.path.exists(src) else None
                else:
                    if base_dir:
                        cand = os.path.normpath(
                            os.path.join(base_dir, src))
                        if os.path.exists(cand):
                            resolved = cand
                    if resolved is None and os.path.exists(src):
                        resolved = src
            if resolved is not None and \
                    self.add_picture_frame(para, resolved):
                pass
            else:
                para.addText(m.group(0))
            pos = m.end()
        if pos < len(text):
            self.add_markers(para, text[pos:])


def _add_odt_table(writer, rows):
    """Append a table from `|…|` markdown rows; first row is the header."""
    from odf import table as _ot
    from odf import text as _t
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
    tab = _ot.Table(name=f"Table{writer._counter}")
    writer._counter += 1
    for _ in range(width):
        tab.addElement(_ot.TableColumn())
    if header is not None:
        head_row = _ot.TableRow()
        for text in header:
            cell = _ot.TableCell()
            para = _t.P()
            st = writer.text_style(bold=True)
            if st is not None:
                span = _t.Span(stylename=st)
                span.addText(text)
                para.addElement(span)
            else:
                para.addText(text)
            cell.addElement(para)
            head_row.addElement(cell)
        tab.addElement(head_row)
    for row in data:
        tr = _ot.TableRow()
        for text in row:
            cell = _ot.TableCell()
            para = _t.P()
            writer.add_markers(para, text)
            cell.addElement(para)
            tr.addElement(cell)
        tab.addElement(tr)
    writer.doc.text.addElement(tab)


def _add_qtext_odt_table(writer, qtable, qdoc, base_dir=""):
    """Append a table mirroring a live QTextTable (header fill kept)."""
    from PySide6.QtGui import QTextCharFormat
    from odf import table as _ot
    from odf import text as _t
    rows, cols = qtable.rows(), qtable.columns()
    if rows <= 0 or cols <= 0:
        return
    tab = _ot.Table(name=f"Table{writer._counter}")
    writer._counter += 1
    for _ in range(cols):
        tab.addElement(_ot.TableColumn())
    for r in range(rows):
        tr = _ot.TableRow()
        for c in range(cols):
            try:
                cell = qtable.cellAt(r, c)
            except Exception:
                continue
            fill = _qt_cell_fill_hex(qdoc, qtable, r, c)
            kwargs = {}
            if fill:
                st = writer.cell_style(fill)
                if st is not None:
                    kwargs["stylename"] = st
            wcell = _ot.TableCell(**kwargs)
            blocks, sp, ep = _qtext_cell_blocks(qdoc, cell)
            wrote_para = False
            for b in blocks:
                bs = max(b.position(), sp)
                be = min(b.position() + len(b.text()), ep)
                if be <= bs:
                    continue
                body = b.text()[bs - b.position():be - b.position()]
                if not body:
                    continue
                para = _t.P()
                if _IMAGE_TOKEN.search(body):
                    writer.add_runs(para, body, base_dir)
                else:
                    for frag_text, fmt in _iter_format_runs(
                            qdoc, bs, be):
                        if not frag_text:
                            continue
                        brush = fmt.foreground()
                        color = None
                        try:
                            if brush.style() == Qt.SolidPattern:
                                cc = brush.color()
                                if cc != QColor("#ffffff") and \
                                        cc != QColor("#000000"):
                                    color = "#%02x%02x%02x" % (
                                        cc.red(), cc.green(), cc.blue())
                        except Exception:
                            color = None
                        bg = None
                        if fill:
                            pass  # shading already on the cell
                        elif fmt.background().style() != Qt.NoBrush:
                            try:
                                bc = fmt.background().color()
                                bg = "#%02x%02x%02x" % (
                                    bc.red(), bc.green(), bc.blue())
                            except Exception:
                                bg = None
                        families = fmt.fontFamilies()
                        st = writer.text_style(
                            bold=(fmt.fontWeight() == QFont.Bold),
                            italic=fmt.fontItalic(),
                            underline=fmt.fontUnderline(),
                            color=color, bg=bg,
                            font=families[0] if families else None,
                            size=(fmt.fontPointSize()
                                  if fmt.fontPointSize() > 0 else None))
                        if st is not None:
                            span = _t.Span(stylename=st)
                            span.addText(frag_text)
                            para.addElement(span)
                        else:
                            para.addText(frag_text)
                wcell.addElement(para)
                wrote_para = True
            if not wrote_para:
                wcell.addElement(_t.P())
            tr.addElement(wcell)
        tab.addElement(tr)
    writer.doc.text.addElement(tab)


def text_to_odt(path, text, document=None):
    """Write editor content to .odt (headings, tables, pictures).

    With a QTextDocument (preferred), character formatting and real
    QTextTables are read straight from the document. Without one,
    inline markers and `|…|` pipe tables are parsed instead.
    """
    from odf import text as _t
    writer = _OdtWriter()
    base_dir = os.path.dirname(os.path.abspath(path))

    def images_only(line):
        from smoothcursor.documents.docx_io import _only_images
        return _only_images(line)

    if document is not None:
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
                _add_qtext_odt_table(writer, qtable, document, base_dir)
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
                para = _t.H(outlinelevel=level)
                writer.add_runs(para, heading.group(2), base_dir)
                writer.doc.text.addElement(para)
                block = block.next()
                continue
            if not line.strip():
                writer.doc.text.addElement(_t.P())
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
                _add_odt_table(writer, rows)
                continue
            body = line
            imgs = images_only(body)
            if imgs:
                for _alt, src in imgs:
                    para = _t.P()
                    resolved = _resolve_image(src, base_dir)
                    if resolved is not None and \
                            writer.add_picture_frame(para, resolved):
                        pass
                    else:
                        para.addText(f"![{_alt}]({src})")
                    writer.doc.text.addElement(para)
                block = block.next()
                continue
            para = _t.P()
            if _IMAGE_TOKEN.search(body):
                writer.add_runs(para, body, base_dir)
            else:
                bs, be = block.position(), block.position() + len(body)
                for frag_text, fmt in _iter_format_runs(
                        document, bs, be):
                    if not frag_text:
                        continue
                    brush = fmt.foreground()
                    color = None
                    try:
                        if brush.style() == Qt.SolidPattern:
                            cc = brush.color()
                            if cc != QColor("#ffffff") and \
                                    cc != QColor("#000000"):
                                color = "#%02x%02x%02x" % (
                                    cc.red(), cc.green(), cc.blue())
                    except Exception:
                        color = None
                    bg = None
                    if fmt.background().style() != Qt.NoBrush:
                        try:
                            bc = fmt.background().color()
                            bg = "#%02x%02x%02x" % (
                                bc.red(), bc.green(), bc.blue())
                        except Exception:
                            bg = None
                    families = fmt.fontFamilies()
                    st = writer.text_style(
                        bold=(fmt.fontWeight() == QFont.Bold),
                        italic=fmt.fontItalic(),
                        underline=fmt.fontUnderline(),
                        color=color, bg=bg,
                        font=families[0] if families else None,
                        size=(fmt.fontPointSize()
                              if fmt.fontPointSize() > 0 else None))
                    if st is not None:
                        span = _t.Span(stylename=st)
                        span.addText(frag_text)
                        para.addElement(span)
                    else:
                        para.addText(frag_text)
            writer.doc.text.addElement(para)
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
                _add_odt_table(writer, rows)
                continue
            heading = re.match(r"^(#{1,9})\s+(.*)$", line)
            if heading:
                para = _t.H(outlinelevel=min(
                    max(len(heading.group(1)), 1), 9))
                writer.add_runs(para, heading.group(2), base_dir)
            elif images_only(line):
                for _alt, src in images_only(line):
                    para = _t.P()
                    resolved = _resolve_image(src, base_dir)
                    if resolved is not None and \
                            writer.add_picture_frame(para, resolved):
                        pass
                    else:
                        para.addText(f"![{_alt}]({src})")
                    writer.doc.text.addElement(para)
                i += 1
                continue
            elif line.strip():
                para = _t.P()
                writer.add_runs(para, line, base_dir)
            else:
                para = _t.P()
            writer.doc.text.addElement(para)
            i += 1
    writer.doc.save(path)
