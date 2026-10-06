"""Lightweight Python syntax highlighting via QSyntaxHighlighter."""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

KEYWORDS = (
    "and as assert async await break class continue def del elif else except "
    "finally for from global if import in is lambda nonlocal not or pass "
    "raise try while with yield match case"
).split()

CONSTANTS = ("True", "False", "None")

BUILTINS = (
    "abs all any ascii bin bool bytearray bytes callable chr classmethod "
    "compile complex delattr dict dir divmod enumerate eval exec filter "
    "float format frozenset getattr globals hasattr hash help hex id input "
    "int isinstance issubclass iter len list locals map max memoryview min "
    "next object oct open ord pow print property range repr reversed round "
    "set setattr slice sorted staticmethod str sum super tuple type vars zip"
).split()

# Block states: 0 = normal, 1 = inside triple-double-quote, 2 = inside
# triple-single-quote.
_TRIPLE = {"\"\"\"": 1, "'''": 2}
_OPENERS = re.compile(r'''([fFrRbBuU]{0,2})("""|\'\'\'|"|')''')
_STRING_BODY = {'"': re.compile(r'(?:\\.|[^"\\\n])*'),
                "'": re.compile(r"(?:\\.|[^'\\\n])*")}
_COMMENT = re.compile(r'#[^\n]*')


_JSON_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"'          # strings / property names
    r'|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    r'|\b(?:true|false|null)\b'
)


class JSONHighlighter(QSyntaxHighlighter):
    """Tiny JSON highlighter: keys, strings, numbers, true/false/null."""

    def __init__(self, document, colors: dict):
        super().__init__(document)
        self._key_fmt = None
        self._string_fmt = None
        self._number_fmt = None
        self._const_fmt = None
        self._default_fmt = None
        self.apply_colors(colors)

    def apply_colors(self, colors: dict):
        self._key_fmt = _fmt(colors["syn_funcdef"])
        self._string_fmt = _fmt(colors["syn_string"])
        self._number_fmt = _fmt(colors["syn_number"])
        self._const_fmt = _fmt(colors["syn_constant"], bold=True)
        self._default_fmt = _fmt(colors["editor_text"])
        self.rehighlight()

    # pylint: disable=invalid-name
    def highlightBlock(self, text):
        length = len(text)
        if length == 0:
            return
        self.setFormat(0, length, self._default_fmt)
        for m in _JSON_TOKEN.finditer(text):
            token = m.group(0)
            if token.startswith('"'):
                after = text[m.end():].lstrip()
                fmt = self._key_fmt if after.startswith(":") \
                    else self._string_fmt
            elif token[0].isdigit() or token[0] == "-":
                fmt = self._number_fmt
            else:
                fmt = self._const_fmt
            self.setFormat(m.start(), m.end() - m.start(), fmt)


def create_highlighter(language, document, colors: dict):
    """Factory: right highlighter for a file type, or None for plain text."""
    if language == "python":
        return PythonHighlighter(document, colors)
    if language == "json":
        return JSONHighlighter(document, colors)
    return None

    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.DemiBold)
    if italic:
        f.setFontItalic(True)
    return f


def _fmt(color, bold=False, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.DemiBold)
    if italic:
        f.setFontItalic(True)
    return f


class PythonHighlighter(QSyntaxHighlighter):
    """Single-pass, per-line highlighter with multi-line string support."""

    def __init__(self, document, colors: dict):
        super().__init__(document)
        self._rules = []
        self._string_fmt = None
        self._comment_fmt = None
        self._default_fmt = None
        self.apply_colors(colors)

    def apply_colors(self, colors: dict):
        def rx(pattern, color, **kw):
            return (re.compile(pattern), _fmt(colors[color], **kw))

        self._string_fmt = _fmt(colors["syn_string"])
        self._comment_fmt = _fmt(colors["syn_comment"])
        self._default_fmt = _fmt(colors["editor_text"])

        self._rules = [
            (re.compile(
                r'\b(?:' + '|'.join(KEYWORDS) + r')\b'),
             _fmt(colors["syn_keyword"])),
            (re.compile(r'\b(?:' + '|'.join(CONSTANTS) + r')\b'),
             _fmt(colors["syn_constant"], bold=True)),
            (re.compile(r'\bself\b|\bcls\b'),
             _fmt(colors["syn_self"], italic=True)),
            (re.compile(r'\b(?:' + '|'.join(BUILTINS) + r')\b'),
             _fmt(colors["syn_builtin"])),
            (re.compile(r'^\s*(?:async\s+)?def\s+(\w+)'),
             _fmt(colors["syn_funcdef"])),
            (re.compile(r'^\s*class\s+(\w+)'),
             _fmt(colors["syn_classdef"], bold=True)),
            (re.compile(r'(?<![\w@])@[\w.]+'),
             _fmt(colors["syn_decorator"])),
            (re.compile(
                r'\b(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|'
                r'\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?[jJ]?)\b'),
             _fmt(colors["syn_number"])),
            (re.compile(r'[-+*/%=<>!&|^~]'),
             _fmt(colors["syn_operator"])),
        ]
        self.rehighlight()

    # pylint: disable=invalid-name
    def highlightBlock(self, text):
        length = len(text)
        if length == 0:
            self.setCurrentBlockState(0)
            return
        self.setFormat(0, length, self._default_fmt)

        covered = []  # (start, end) spans handled as string/comment

        # 1. Continue a multi-line string from the previous block.
        state = self.previousBlockState()
        pos = 0
        self.setCurrentBlockState(0)
        if state in (1, 2):
            delim = '\"\"\"' if state == 1 else "'''"
            end = text.find(delim)
            if end == -1:
                self.setFormat(0, length, self._string_fmt)
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, end + 3, self._string_fmt)
            covered.append((0, end + 3))
            pos = end + 3

        # 2. Scan the rest of the line for strings and comments.
        for m in _OPENERS.finditer(text, pos):
            prefix, quote = m.group(1), m.group(2)
            start = m.start(1) if prefix else m.start(2)
            if quote in _TRIPLE:
                close = text.find(quote, m.end(2))
                if close == -1:
                    self.setFormat(start, length - start, self._string_fmt)
                    self.setCurrentBlockState(_TRIPLE[quote])
                    covered.append((start, length))
                    pos = length
                    break
                stop = close + 3
                self.setFormat(start, stop - start, self._string_fmt)
                covered.append((start, stop))
                pos = stop
            else:
                body = _STRING_BODY[quote].match(text, m.end(2))
                stop = min(body.end() + 1, length) if body is not None \
                    else length
                self.setFormat(start, stop - start, self._string_fmt)
                covered.append((start, stop))
                pos = stop

        if pos < length:
            cm = _COMMENT.match(text, pos)
            if cm:
                self.setFormat(cm.start(), length - cm.start(),
                               self._comment_fmt)
                covered.append((cm.start(), length))

        # 3. Mask strings/comments out so structural rules can't match
        #    inside them, then run the cheap regex rules.
        mask = list(text)
        for s, e in covered:
            for i in range(s, e):
                mask[i] = ' '
        masked = ''.join(mask)

        for idx, (regex, fmt) in enumerate(self._rules):
            for m in regex.finditer(masked):
                groups = m.groups()
                if len(groups) == 1 and groups[0] is not None:
                    s, e = m.start(1), m.end(1)
                else:
                    s, e = m.start(), m.end()
                if e > s:
                    self.setFormat(s, e - s, fmt)
