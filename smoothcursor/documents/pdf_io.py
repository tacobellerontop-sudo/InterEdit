"""PDF export (write-only) via Qt printing.

PDF files cannot be opened for editing — there is no text model to round
trip — but any tab can be exported through Save As (*.pdf) or the same
code path. Tables, images and formatting render as laid out.
"""

import os


def is_pdf(path):
    return (path or "").lower().endswith(".pdf")


def export_qdoc_to_pdf(qdoc, path):
    """Render a QTextDocument to `path`. Raises on failure."""
    from PySide6.QtPrintSupport import QPrinter
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(os.path.abspath(path))
    qdoc.print_(printer)
    if not os.path.exists(path) or os.path.getsize(path) <= 0:
        raise RuntimeError("Could not write PDF (printer produced no file)")
