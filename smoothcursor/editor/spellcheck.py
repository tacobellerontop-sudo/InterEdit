"""Spellcheck for prose tabs: hunspell backend, wavy underlines, menus.

Zero new dependencies: the backend talks to the system libhunspell over
ctypes and reads the dictionaries Ubuntu ships
(/usr/share/hunspell/en_US.*). When no library or dictionary is found,
everything degrades to "unavailable" — nothing crashes, the Settings
checkbox simply reports it.
"""

import ctypes
import ctypes.util
import os
import re

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)

WORD_RE = re.compile(r"[A-Za-z]+(?:['\u2019\-][A-Za-z]+)*")
_MAX_WORD = 48
_CACHE_SIZE = 5000


def _find_hunspell_lib():
    try:
        return ctypes.util.find_library("hunspell-1.7") or \
            ctypes.util.find_library("hunspell")
    except Exception:
        return None


def _find_dicts():
    """(aff, dic) paths for en_US (then en_GB), else None."""
    candidates = [
        "/usr/share/hunspell/en_US",
        "/usr/share/hunspell/en_GB",
        os.path.join(os.path.expanduser("~"), ".local/share/hunspell/en_US"),
    ]
    for base in candidates:
        if os.path.exists(base + ".aff") and os.path.exists(base + ".dic"):
            return base + ".aff", base + ".dic"
    return None


class _Hunspell:
    """Minimal ctypes wrapper around libhunspell (create/spell/suggest)."""

    def __init__(self, aff, dic):
        from ctypes import POINTER, byref, c_char_p, c_int, c_void_p
        libname = _find_hunspell_lib()
        if not libname:
            raise RuntimeError("no hunspell library")
        self._lib = ctypes.CDLL(libname)
        lib = self._lib
        lib.Hunspell_create.argtypes = [c_char_p, c_char_p]
        lib.Hunspell_create.restype = c_void_p
        lib.Hunspell_destroy.argtypes = [c_void_p]
        lib.Hunspell_spell.argtypes = [c_void_p, c_char_p]
        lib.Hunspell_spell.restype = c_int
        lib.Hunspell_suggest.argtypes = [
            c_void_p, POINTER(POINTER(c_char_p)), c_char_p]
        lib.Hunspell_suggest.restype = c_int
        lib.Hunspell_free_list.argtypes = [
            c_void_p, POINTER(POINTER(c_char_p)), c_int]
        lib.Hunspell_add.argtypes = [c_void_p, c_char_p]
        lib.Hunspell_add.restype = c_int
        lib.Hunspell_get_dic_encoding.argtypes = [c_void_p]
        lib.Hunspell_get_dic_encoding.restype = c_char_p
        handle = lib.Hunspell_create(aff.encode(), dic.encode())
        if not handle:
            raise RuntimeError("Hunspell_create failed")
        self._h = handle
        try:
            self._enc = (lib.Hunspell_get_dic_encoding(handle) or b"UTF-8") \
                .decode("ascii", "replace")
        except Exception:
            self._enc = "UTF-8"
        self._pp = POINTER(c_char_p)
        self._byref = byref

    def check(self, word):
        try:
            return bool(self._lib.Hunspell_spell(
                self._h, word.encode(self._enc, "replace")))
        except Exception:
            return True

    def suggest(self, word, limit=5):
        from ctypes import POINTER, c_char_p
        out = []
        try:
            slst = POINTER(c_char_p)()
            n = self._lib.Hunspell_suggest(
                self._h, self._byref(slst), word.encode(self._enc, "replace"))
            for i in range(min(max(int(n), 0), limit)):
                try:
                    out.append(ctypes.string_at(slst[i]).decode(
                        self._enc, "replace"))
                except Exception:
                    break
            if n > 0:
                self._lib.Hunspell_free_list(self._h, self._byref(slst), n)
        except Exception:
            pass
        return out

    def add(self, word):
        try:
            self._lib.Hunspell_add(
                self._h, word.encode(self._enc, "replace"))
            return True
        except Exception:
            return False

    def close(self):
        try:
            if getattr(self, "_h", None):
                self._lib.Hunspell_destroy(self._h)
        except Exception:
            pass
        self._h = None


_checker = None
_checker_failed = False
_cache = {}
_cache_generation = [0]
_backend_label = [None]


def user_dict_path():
    """File holding the user's own words (created on demand)."""
    try:
        from PySide6.QtCore import QStandardPaths
        loc = QStandardPaths.writableLocation(
            QStandardPaths.AppDataLocation)
    except Exception:
        loc = ""
    if not loc:
        loc = os.path.expanduser("~/.local/share/smoothcursor")
    try:
        os.makedirs(loc, exist_ok=True)
    except OSError:
        pass
    return os.path.join(loc, "user_words.txt")


def load_user_words():
    words = []
    try:
        with open(user_dict_path(), "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word and len(word) <= _MAX_WORD:
                    words.append(word)
    except OSError:
        pass
    return words


def get_checker():
    """Shared hunspell backend, or None when unavailable."""
    global _checker, _checker_failed
    if _checker is not None or _checker_failed:
        return _checker
    try:
        found = _find_dicts()
        if found is None:
            raise RuntimeError("no dictionaries")
        aff, dic = found
        _checker = _Hunspell(aff, dic)
        for word in load_user_words():
            _checker.add(word)
        _backend_label[0] = "hunspell " + os.path.basename(dic)
    except Exception:
        _checker = None
        _checker_failed = True
    return _checker


def reset_checker():
    """Test hook: drop the cached backend (and result cache)."""
    global _checker, _checker_failed
    try:
        if _checker is not None:
            _checker.close()
    except Exception:
        pass
    _checker = None
    _checker_failed = False
    _cache.clear()


def spell_available():
    return get_checker() is not None


def spell_backend_name():
    get_checker()
    return _backend_label[0]


def _invalidate_cache():
    _cache_generation[0] += 1
    _cache.clear()


def add_to_user_dict(word):
    """Add `word` for this session and persist it. Returns True on success."""
    word = (word or "").strip()
    if not word or len(word) > _MAX_WORD:
        return False
    checker = get_checker()
    if checker is None:
        return False
    if not checker.add(word):
        return False
    try:
        existing = set(load_user_words())
        if word.lower() not in {w.lower() for w in existing}:
            with open(user_dict_path(), "a", encoding="utf-8") as f:
                f.write(word + "\n")
    except OSError:
        pass
    _invalidate_cache()
    return True


def is_skippable(word):
    """True for tokens spellcheck should never flag."""
    if len(word) < 2 or len(word) > _MAX_WORD:
        return True
    if word.isupper():  # acronyms: HTML, README, …
        return True
    return False


def is_misspelled(word):
    """True when `word` should get a wavy underline."""
    if not word or is_skippable(word):
        return False
    key = word.lower()
    hit = _cache.get(key)
    if hit is not None and hit[0] == _cache_generation[0]:
        return hit[1]
    checker = get_checker()
    bad = False
    if checker is not None:
        try:
            bad = not checker.check(word)
        except Exception:
            bad = False
    if len(_cache) >= _CACHE_SIZE:
        _cache.clear()
    _cache[key] = (_cache_generation[0], bad)
    return bad


def suggestions_for(word, limit=5):
    checker = get_checker()
    if checker is None:
        return []
    try:
        return checker.suggest(word, limit) or []
    except Exception:
        return []


class SpellHighlighter(QSyntaxHighlighter):
    """Wavy red underlines for misspelled words (prose tabs only).

    Only sets underline style/color, so it composes with the syntax
    highlighter instead of clobbering it. Attach with set_active().
    """

    def __init__(self, document=None, colors=None):
        super().__init__(document)
        self._document = document
        self._active = document is not None
        self._fmt = QTextCharFormat()
        self.apply_colors(colors or {})

    def apply_colors(self, colors):
        try:
            danger = colors.get("danger", "#f14c4c")
        except Exception:
            danger = "#f14c4c"
        self._fmt = QTextCharFormat()
        self._fmt.setUnderlineStyle(
            QTextCharFormat.SpellCheckUnderline)
        self._fmt.setUnderlineColor(QColor(danger))
        self._fmt.setFontUnderline(True)
        if self._active:
            self.rehighlight()

    def set_active(self, active):
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        try:
            self.setDocument(self._document if active else None)
        except Exception:
            pass
        if active:
            self.rehighlight()

    def is_active(self):
        return self._active and self.document() is not None

    # pylint: disable=invalid-name
    def highlightBlock(self, text):
        if not self._active or get_checker() is None:
            return
        for m in WORD_RE.finditer(text or ""):
            word = m.group(0)
            if is_misspelled(word):
                self.setFormat(m.start(), len(word), self._fmt)


def misspelled_word_at(editor, event_pos):
    """(word, select_cursor) for a misspelled word at a context-menu click.

    `event_pos` is in editor-widget coordinates (as QContextMenuEvent
    gives). Returns None for correctly spelled / non-word targets.
    """
    try:
        viewport = editor.viewport()
        candidates = []
        try:
            candidates.append(viewport.mapFromGlobal(
                editor.mapToGlobal(event_pos)))
        except Exception:
            pass
        candidates.append(event_pos)
        for pt in candidates:
            try:
                cursor = editor.cursorForPosition(pt)
            except Exception:
                continue
            try:
                word_cursor = type(cursor)(cursor)
            except Exception:
                continue
            try:
                word_cursor.select(QTextCursor.WordUnderCursor)
                word = word_cursor.selectedText().replace("\u2029", "")
            except Exception:
                continue
            if not word or not WORD_RE.fullmatch(word):
                continue
            if is_misspelled(word):
                return word, word_cursor
            return None
    except Exception:
        pass
    return None


def append_spelling_section(menu, editor, event_pos):
    """Suggestions + 'Add to dictionary' atop `menu`. True when added."""
    found = misspelled_word_at(editor, event_pos)
    if found is None:
        return False
    word, word_cursor = found
    try:
        for suggestion in suggestions_for(word):
            act = menu.addAction(suggestion)
            act.triggered.connect(
                lambda _checked=False, s=suggestion,
                wc=QTextCursor(word_cursor):
                (editor.setTextCursor(wc),
                 editor.textCursor().insertText(s)))
        add_act = menu.addAction("Add '%s' to dictionary" % word)
        def _add(_checked=False, w=word):
            if add_to_user_dict(w):
                try:
                    editor.spell_highlighter.rehighlight()
                except Exception:
                    pass
        add_act.triggered.connect(_add)
        menu.addSeparator()
        return True
    except Exception:
        return False
