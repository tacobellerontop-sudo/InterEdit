# SmoothCursor

A lightweight, native Python code editor for Ubuntu built with **PySide6 / Qt**.
Its defining feature is a **Microsoft Word–style smooth caret**: the real
`QTextCursor` updates instantly, while a custom-painted caret overlay glides
toward it with frame-rate-independent exponential smoothing (~120 FPS).

![Feature summary](https://img.shields.io/badge/python-3.9%2B-blue)

## Features

- **Smooth caret** — interpolated horizontal *and* vertical movement, natural
  catch-up while typing fast, no overshoot, instant repositioning on huge
  jumps (e.g. `Ctrl+Home`) or scrolls, blinking with subtle opacity fades
  when idle.
- **Real Qt editing** — built on `QPlainTextEdit`: typing, Backspace/Delete,
  arrows, Home/End, `Ctrl+Arrow` word navigation, Shift selection, mouse and
  double-click selection, `Ctrl+A/C/V/X/Z/Y`.
- **Python syntax highlighting** — keywords, strings (including multi-line
  triple-quoted strings), numbers, comments, `def`/`class` names, builtins,
  decorators, operators. JSON files get their own lightweight highlighter
  (keys, strings, numbers, `true`/`false`/`null`).
- **Line-number gutter** — on both code and rich (Word-style) tabs,
  auto-resizes with digit count, highlights the current line number,
  scrolls in sync, click-to-select-line. Settings → Line numbers picks
  Off / Absolute / Relative / Hybrid (relative shows distance from the
  cursor line, Hybrid keeps the absolute number on it).
- **Editor niceties** — current-line highlight, auto-indent, indent/dedent
  selected lines with `Tab`/`Shift+Tab`, indent-after-`:` on newline.
- **Auto-format** — `Enter` continues ordered (`1.`/`1)`) lists with
  auto-renumber, `-`/`*`/`+` bullets, `- [ ]` task lists (reset unchecked),
  and `>` blockquotes; `Enter` on an empty item exits it (nested items
  dedent first). Auto-closes `()[]{}`/`""`/`''`, skips over typed closers,
  deletes empty pairs with `Backspace`, and expands `{|}` onto three lines.
  Both can be toggled in Settings.
- **Tabs** — closable, movable, modified indicator (`●`), `Ctrl+W` close,
  `Ctrl+Tab` / `Ctrl+Shift+Tab` switching.
- **File operations** — New / Open / Save / Save As with unsaved-changes
  prompts (Save / Don't Save / Cancel), filename and modified state in the
  title bar. Handles `.py`, `.json`, `.txt`, `.md` — and rich documents
  (`.docx` Word, `.odt` OpenDocument, `.html`) with formatting and real
  tables, plus Save As → `.pdf` export. New documents default to Word
  (.docx).
- **Session persistence** — window size/position, open tabs with cursor
  positions, unsaved-tab backups, and a toolbar **Recent** files menu are
  all restored on launch. Every preference (including caret speed) is
  flushed to disk the moment it changes.
- **Startup screen** — when there is no session to restore, launch lands
  on a welcome page with New / Open / Settings actions, a clickable
  recent-files list, and a shortcut cheat sheet.
- **Search** — `Ctrl+F` find bar with next/prev (`F3` / `Shift+F3`), live
  match highlighting, `1 / n` counter, `Escape` to close; `Ctrl+H` adds
  Replace / Replace-All in a single undo step.
- **Menu bar + Help** — File / Edit / View / Insert / Help menus with
  every shortcut, a Keyboard Shortcuts reference, an About box, print
  (`Ctrl+P`) and Export-to-PDF actions.
- **Spellcheck** — wavy underlines on prose tabs (never inside code),
  right-click suggestions, personal dictionary, toggle in Settings.
  Uses the system hunspell dictionaries when present and stays silent
  otherwise.
- **Line editing** — `Ctrl+/` toggles comments (`#` / `//` per language),
  `Ctrl+D` duplicates, `Ctrl+Shift+K` deletes, `Alt+↑/↓` moves lines
  (formatting-preserving, single undo), `Ctrl+J` joins lines.
- **Settings** — font family/size, tab size, spaces vs tabs, word wrap,
  **caret animation speed (with live typing preview)**, blink cycle length, theme (built-in
  dark/light plus your own JSON themes) — all applied live and persisted.
- **Dark theme UI** — menu bar, subtle borders, styled scrollbars,
  status bar with Ln/Col, word count, and selection size.

## Install (Ubuntu)

Requires Python 3.9+. A virtual environment is recommended:

```bash
cd smoothcursor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On some minimal Ubuntu installs you may also need the Qt runtime deps:

```bash
sudo apt install libgl1 libegl1 libxkbcommon0
```

`requirements.txt` already includes the rich-document libraries
(`python-docx` for `.docx`, `odfpy` for `.odt`, `Pillow` for photo
scaling). If you installed with `--no-deps` or removed them, restore
with:

```bash
pip install python-docx odfpy Pillow
```

### Rich document editing

`.docx`, `.odt` and `.html` tabs get a **floating format toolbar** that
appears when you select text (Microsoft Word / Google Docs style):
**Bold**, *Italic*, <u>Underline</u>, text highlight (8 colors), text
color, and clear-formatting. Toggles stay in sync with the selection
under the cursor. Bold/italic/underline/highlight/color survive the
save → reopen round trip as real formatting. Save As → `.pdf` exports
any tab (export-only; PDFs can't be reopened for editing).

The **Insert** menu adds structured content anywhere:

- **Table…** — rows/columns plus style (border width, cell padding,
  bold header, header fill color) inserting a real editable table
  (Word-style grid in rich `.docx`/`.odt`/`.html` tabs, Markdown `|…|`
  pipes in plain `.md`/`.txt` tabs) with the cursor in the first cell.
- **Table Properties…** (right-click a table cell) — restyle the table
  under the cursor (border, padding, header bold/fill). **Format Table**
  applies the default header style (or pipe alignment for Markdown).
  `Tab` / `Shift+Tab` move between cells (`Tab` in the last cell
  appends a row); pasted `|…|` pipes convert via Format.
- **Row/column editing** — right-click any table cell for Table
  Properties, Insert Row Above/Below, Insert Column Left/Right, Delete
  Row/Column/Table and Toggle Header Row (rich tabs only).
- **Image…** — photo picker inserting `![alt](path)` (relative paths when
  the image sits next to the document).
- **Horizontal Rule** (`---`) and **Link…** (`[text](url)`, wrapping the
  selection when there is one).

On `.docx`/`.odt` save, real tables stay real tables (header bold +
fill preserved via cell shading) and `![…](…)` refs become real
embedded pictures (sized down to page width); missing image files stay
literal so nothing is lost. Opening a `.docx`/`.odt` loads tables as
real editable tables (including header shading) and embedded pictures
as `![…](…)` refs (saved under the app's media dir), so both
round-trip. `.html` tabs save with `document.toHtml()` and reopen with
`setHtml`, preserving tables and formatting the same way.

### Custom themes (JSON)

Settings → Theme lists `dark`, `light`, plus any `*.json` theme in the
app's `themes` folder (Settings → Folder opens it and drops in an
`example-custom.json`). Each file is one theme named after the file:

```json
{
  "$extends": "dark",
  "accent": "#ff9e00",
  "editor_bg": "#101020",
  "editor_text": "#e6e6e6"
}
```

Only `"#rrggbb"` values for known color keys are used; missing keys fall
back to the `$extends` theme (default `dark`). Press Reload in Settings
after adding files. Unknown keys are ignored so old themes keep working.

## Run

```bash
python main.py        # or: python -m smoothcursor
```

## Tests

```bash
python tests/run_all.py
```

## Keyboard shortcuts

| Action            | Shortcut                          |
| ----------------- | --------------------------------- |
| New file          | `Ctrl+N`                          |
| Open file         | `Ctrl+O`                          |
| Save              | `Ctrl+S`                          |
| Save as           | `Ctrl+Shift+S`                    |
| Print             | `Ctrl+P`                          |
| Close tab         | `Ctrl+W`                          |
| Preferences       | `Ctrl+,`                          |
| Next / prev tab   | `Ctrl+Tab` / `Ctrl+Shift+Tab`     |
| Find              | `Ctrl+F`                          |
| Replace           | `Ctrl+H`                          |
| Next / prev match | `F3` / `Shift+F3`                 |
| Toggle comment    | `Ctrl+/`                          |
| Duplicate line    | `Ctrl+D`                          |
| Delete line       | `Ctrl+Shift+K`                    |
| Move line up/down | `Alt+Up` / `Alt+Down`             |
| Join lines        | `Ctrl+J`                          |
| Zoom in / out     | `Ctrl+=` / `Ctrl+-` (`Ctrl+wheel`)|
| Reset zoom        | `Ctrl+0`                          |
| Undo / Redo       | `Ctrl+Z` / `Ctrl+Y` or `Ctrl+Shift+Z` |
| Select all        | `Ctrl+A`                          |
| Indent / dedent   | `Tab` / `Shift+Tab` (on selection)|

## Architecture

```
smoothcursor/
├── main.py                     # thin launcher
├── requirements.txt
├── README.md
├── tests/                      # headless regression scripts + runner
└── smoothcursor/               # app package (`python -m smoothcursor`)
    ├── __init__.py             # version
    ├── __main__.py             # app bootstrap, theming
    ├── core/
    │   ├── settings.py         # Settings (QSettings) + SettingsDialog
    │   └── theme.py            # dark/light palettes + global QSS
    ├── editor/
    │   ├── editor.py           # CodeEditor: gutter + caret + auto-format
    │   ├── rich.py             # RichEditor (QTextEdit): real QTextTables
    │   ├── spellcheck.py       # hunspell backend + wavy-underline layer
    │   ├── caret.py            # SmoothCaret: animated caret (star feature)
    │   ├── syntax.py           # Python/JSON syntax highlighting
    │   ├── line_numbers.py     # gutter widget + painting helpers
    │   └── docx_toolbar.py     # floating format toolbar for rich tabs
    ├── documents/
    │   ├── docx_io.py          # Word import/export: markers, tables, pics
    │   ├── odt_io.py           # OpenDocument import/export (needs odfpy)
    │   ├── html_io.py          # HTML import/export via Qt rich text
    │   └── pdf_io.py           # PDF export via Qt printing (write-only)
    └── views/
        ├── window.py           # MainWindow: files, tabs, menus, Insert
        ├── help.py             # Shortcuts reference + About dialogs
        ├── tabs.py             # EditorTabs: closable/movable tab widget
        ├── search.py           # FindBar: find + replace UI
        └── welcome.py          # WelcomePage: startup screen + recents
```

### How the smooth caret works

`smoothcursor/editor/caret.py` implements `SmoothCaret`, a transparent child widget of the
editor's viewport with `WA_TransparentForMouseEvents`, so all real editing
and mouse handling is untouched (`QPlainTextEdit`'s own caret is hidden via
`setCursorWidth(0)`).

Every animation tick (8 ms timer) it:

1. reads the real cursor's pixel position with `cursorRect()`,
2. snaps if the move wasn't a "travel" move (first paint, > 2000 px jumps,
   caret scrolled off-screen) — so `Ctrl+Home` or page scrolls reposition
   instantly instead of streaking across the document,
3. otherwise moves `current` toward `target` using
   `current += (target - current) * (1 - e^(-speed·dt))` — frame-rate
   independent, critically damped, no overshoot,
4. repaints **only the small rectangle** the caret occupies (old ∪ new),
   keeping per-frame cost negligible; the actual text cursor is never
   delayed by the animation.

While the caret is moving it stays solid; ~350 ms after the last cursor
activity it starts its blink cycle with short opacity fades in/out.

## Settings persistence

Settings are stored with `QSettings` (ini under `~/.config/smoothcursor/`)
and take effect immediately for every open tab.
