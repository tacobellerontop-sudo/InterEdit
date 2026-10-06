"""HTML (.html) import/export via Qt rich text.

QTextDocument reads and writes a large HTML subset natively — including
real tables, lists and images — so this module is a thin wrapper: open
loads the file with setHtml (relative image paths resolve against the
file's folder), save writes document.toHtml(). Without a QTextDocument
(tests/CLI), plain text is wrapped into simple paragraphs.
"""

import html as _html
import os
import re

from PySide6.QtCore import QUrl


def is_html(path):
    low = (path or "").lower()
    return low.endswith(".html") or low.endswith(".htm")


def looks_like_html(path):
    """True when the file starts with an HTML doctype or <html> tag."""
    try:
        with open(path, "rb") as f:
            head = f.read(512).lstrip().lower()
        return head.startswith(b"<!doctype html") or \
            head.startswith(b"<html")
    except OSError:
        return False


def html_to_document(path, qdoc):
    """Load an .html file into a QTextDocument (real tables included)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    try:
        qdoc.setBaseUrl(QUrl.fromLocalFile(
            os.path.dirname(os.path.abspath(path)) + os.sep))
    except Exception:
        pass
    qdoc.setHtml(content)
    return qdoc


def _escape(text):
    return _html.escape(text, quote=True)


def text_to_html(path, text, document=None):
    """Write editor content to .html.

    With a QTextDocument (preferred), document.toHtml() preserves real
    tables, lists, images and character formatting. Without one, plain
    text becomes simple paragraphs and `![alt](src)` image refs become
    <img> tags so nothing is lost.
    """
    from smoothcursor.documents.docx_io import _IMAGE_TOKEN, _only_images
    if document is not None:
        content = document.toHtml()
    else:
        parts = ["<!DOCTYPE html>", "<html><head>",
                 '<meta charset="utf-8">',
                 "</head><body>"]
        for line in text.split("\n"):
            imgs = _only_images(line)
            if imgs:
                for alt, src in imgs:
                    parts.append('<p><img src="%s" alt="%s"></p>' % (
                        _escape(src), _escape(alt)))
                continue
            pos, out = 0, []
            for m in _IMAGE_TOKEN.finditer(line):
                if m.start() > pos:
                    out.append(_escape(line[pos:m.start()]))
                out.append('<img src="%s" alt="%s">' % (
                    _escape(m.group(2)), _escape(m.group(1))))
                pos = m.end()
            if pos:
                out.append(_escape(line[pos:]))
                parts.append("<p>" + "".join(out) + "</p>")
            elif line.strip():
                parts.append("<p>" + _escape(line) + "</p>")
            else:
                parts.append("<p><br></p>")
        parts.append("</body></html>")
        content = "\n".join(parts)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
