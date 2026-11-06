# File Organizer

<p align="center">
  <img src="icons/organize-cut.png" alt="File Organizer icon" width="128">
</p>

A **cross-platform** (Windows, macOS, Linux) organizer for a messy folder — usually
Downloads. It doesn't just sort by extension: it reads each file's **metadata and
contents** to put everything in **chronological order** and to spot **recurring
patterns** worth their own folder.

```
Downloads/Gatsby final.docx        ->  Documents/English 3/2024-10-12 Gatsby final.docx
Downloads/Persuasive essay.docx    ->  Documents/English 3/Essays/2024-12-01 Persuasive essay.docx
Downloads/Vocab list unit 2.docx   ->  Documents/English 3/Glossaries/2024-09-20 Vocab list unit 2.docx
Downloads/ch5.docx                 ->  Documents/English 3/Notes/2024-11-01 ch5.docx
Downloads/AP Bio Lab 1.docx        ->  Documents/AP Biology/Lab Reports/2024-09-10 AP Bio Lab 1.docx
Downloads/chase_statement_feb.csv  ->  Documents/Spreadsheets/Chase/Statements/2025-02-01 chase_statement_feb.csv
Downloads/lease.pdf                ->  Documents/2023/2023-03/lease.pdf
Downloads/IMG_20230704_101500.jpg  ->  Pictures/Photos/2023/2023-07/IMG_20230704_101500.jpg
Downloads/Screenshot 2024-02-03…   ->  Pictures/Screenshots/2024/2024-02/…
Downloads/IMG_… (1).jpg            ->  Downloads/Duplicates/IMG_… (1).jpg   (byte-identical copy)
```

None of the "English 3" files above had "English 3" in their file names — it was
found in a Word **header**, an MLA heading line, or the document **title**
property. `ENGLISH III` in one header was recognised as the same course.

## Requirements

- Python 3.10+ (any OS)
- [uv](https://docs.astral.sh/uv/) recommended (or plain `pip`)

## Install

```bash
uv tool install git+https://github.com/anjavera/win-downloads-sorter
```

or `pip install git+https://github.com/anjavera/win-downloads-sorter`. For iPhone
HEIC photo dates add the extra: `uv tool install "file-organizer[heic] @ git+https://github.com/anjavera/win-downloads-sorter"`.

## Use

```bash
organize                      # PREVIEW what would happen to ~/Downloads (moves nothing)
organize --explain            # ...and say why each file goes where it goes
organize --apply              # do it
organize --undo               # put everything from the last run back
```

More options:

| Option | What it does |
| --- | --- |
| `organize ~/Desktop` | organize a different folder |
| `--dest ~/Sorted` | put everything under one folder instead of your Documents / Pictures / Videos / Music |
| `-r`, `--recursive` | include files in subfolders |
| `--min-group 3` | require 3 matching files before a pattern gets a folder (default 2) |
| `--no-date-prefix` | don't prefix grouped files with `YYYY-MM-DD` |
| `--json plan.json` | save the plan (moves, reasons, patterns) as JSON |

Without `--dest`, files go to your OS's standard folders (on Linux it honours
`~/.config/user-dirs.dirs`; on macOS videos go to `Movies`). Types without a
standard home (archives, installers, code, fonts, 3D models, duplicates) are
tidied into subfolders of the source folder.

## How it decides

1. **Type** — by extension into Documents, Spreadsheets, Presentations, Ebooks,
   Pictures, Videos, Audio, Archives, Installers, Code, Fonts, 3D Models.
   Unknown types, half-finished downloads (`.crdownload`, `.part`…) and files
   touched in the last 30 s are left alone.
2. **Date** — the date the *content* was made, not when it was downloaded:
   EXIF capture time → document creation date (DOCX/XLSX/PPTX/ODF/PDF) → date in
   the filename (`IMG_20240512_…`, `Screenshot 2024-05-12 at…`) → latest date in a
   CSV's rows → document modified date → filesystem timestamp.
3. **Patterns** — every document contributes weighted phrases from its header /
   footer (strongest), title / subject / keywords, opening lines, and file name.
   A phrase shared by enough files becomes a topic folder. Course-like phrases
   (`English 3`, `AP Biology`, `MATH 101`, `Chem II`) get a boost; the most
   specific phrase wins (`English 3` over `English`); phrases on nearly every
   file and the documents' author name are ignored.
4. **Document type inside a topic** — Essays, Glossaries, Notes, Study Guides,
   Quizzes & Tests, Worksheets, Lab Reports, Syllabus, Rubrics, Projects,
   Assignments, Invoices, Receipts, Statements, Resumes, Contracts… Files that
   match none are split again by any further recurring phrase (`Unit 2`,
   `Chapter 5`).
5. **Spreadsheets** with identical column headers (repeat exports) are grouped together.
6. **Pictures** — by kind (Photos with camera EXIF, Screenshots, RAW, GIFs,
   Graphics, other Images), then `YYYY/YYYY-MM`.
7. **Duplicates** — byte-identical copies (SHA-256) go to `Duplicates/`.

## Safety

- Preview is the default; nothing moves without `--apply`.
- Never overwrites: name clashes become `name (1).ext`.
- Every run writes an undo log (Windows `%LOCALAPPDATA%\file-organizer`, macOS
  `~/Library/Application Support/file-organizer`, Linux `~/.local/state/file-organizer`).
  `organize --undo` restores files and removes the folders it created.
- Office/ODF XML is parsed with `defusedxml`, since downloads are untrusted.

## Upgrading from v1 (Windows PowerShell version)

v1 installed a Desktop icon and a `Ctrl+Alt+O` hotkey. Remove them with the old
uninstaller (your sorted files are untouched), then install v2 as above:

```powershell
powershell -ExecutionPolicy Bypass -File legacy\Uninstall-v1.ps1
```

## Customize

Edit `src/file_organizer/classify.py` (`CATEGORIES`) to add file types, and
`src/file_organizer/grouping.py` (`DOC_TYPES`) to add document types.

## Develop

```bash
uv sync
uv run pytest
```

See [docs/PROCESS.md](docs/PROCESS.md) for how this version was built.

## License

[MIT](LICENSE)
