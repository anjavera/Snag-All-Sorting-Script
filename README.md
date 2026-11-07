# Snag-All Sorting Script

<p align="center">
  <img src="icons/snag-all.png" alt="Snag-All Sorting Script icon" width="128">
</p>

<p align="center"><em>Created by Opus 5.5 and Anjavera</em></p>

**A file organizer.** It sorts a messy folder (usually Downloads) by date, by type, and by
what's inside the files. Your "English 3" essays, notes and vocab lists end up together,
and photos land in the month they were taken. Works on Windows, Mac and Linux.

```
Gatsby final.docx          ->  Documents/English 3/2024-10-12 Gatsby final.docx
Persuasive essay.docx      ->  Documents/English 3/Essays/2024-12-01 Persuasive essay.docx
Vocab list unit 2.docx     ->  Documents/English 3/Glossaries/2024-09-20 Vocab list unit 2.docx
AP Bio Lab 1.docx          ->  Documents/AP Biology/Lab Reports/2024-09-10 AP Bio Lab 1.docx
lease.pdf                  ->  Documents/2023/2023-03/lease.pdf
IMG_20230704_101500.jpg    ->  Pictures/Photos/2023/2023-07/IMG_20230704_101500.jpg
Screenshot 2024-02-03…     ->  Pictures/Screenshots/2024/2024-02/…
```

## Get started

1. **Download** the launcher for your computer (open the link, then click the download button ⤓):
   - Windows: [Snag-All (Windows).bat](launchers/Snag-All%20(Windows).bat)
   - Mac or Linux: [Snag-All (Mac or Linux).command](launchers/Snag-All%20(Mac%20or%20Linux).command)
2. **Double-click it.** The first run takes a minute to set itself up.
   - Windows may say "Windows protected your PC": click **More info → Run anyway**.
   - Mac may say it can't be opened: right-click the file → **Open** → **Open**.
3. **Look over the preview.** It lists where every file would go. Nothing has moved yet.
4. **Type `y` and press Enter** to sort them, or just close the window to cancel.

Changed your mind? Double-click the **Undo** launcher
([Windows](launchers/Undo%20Snag-All%20(Windows).bat) ·
[Mac or Linux](launchers/Undo%20Snag-All%20(Mac%20or%20Linux).command)) and everything goes back.

To sort a folder other than Downloads, on Windows drag that folder onto the launcher.

## Is it safe?

- **You see everything first.** Nothing moves until you say yes.
- **One step undoes it all**: the Undo launcher, or `organize --undo`.
- **Never deletes or overwrites a file.** If two files share a name, one becomes `name (1)`.
- **Stays on your computer.** It doesn't upload anything, and it leaves OneDrive,
  Google Drive, Dropbox and iCloud folders alone.
- **Sets aside suspicious downloads** in a `Needs Review` folder without opening them.
  This includes a "PDF" that's really a program, documents with macros, or a zip
  hiding a shortcut. It isn't a replacement for antivirus, but it catches the
  common tricks.

## Using it from a terminal

If you're comfortable with a terminal, install it once:

```bash
uv tool install git+https://github.com/anjavera/Snag-All-Sorting-Script
```

(No `uv` yet? [Get it here](https://docs.astral.sh/uv/getting-started/installation/); it sets up
Python for you. `pip install git+https://github.com/anjavera/Snag-All-Sorting-Script` also works.)

```bash
organize                 # preview your Downloads, then asks before moving anything
organize ~/Desktop       # a different folder
organize --home          # loose files in your home folder (add -r for its subfolders too)
organize --explain       # also say why each file goes where it goes
organize --apply         # move without asking (for scripts)
organize --undo          # put everything from the last run back
```

| Option | What it does |
| --- | --- |
| `--dest ~/Sorted` | put everything in one folder instead of your Documents / Pictures / Videos / Music |
| `-r` | include files inside subfolders. Code projects, installed programs, app and browser data, and virtual machines are always left exactly as they are |
| `--exclude "Taxes*"` | never open or move matching files or folders (use as many times as you like) |
| `--skip-type Pictures` | leave a whole kind of file alone |
| `--include-cloud` | also sort inside OneDrive / Google Drive / Dropbox / iCloud folders |
| `--allow-cloud` | allow moving files *into* a cloud folder (they'll be uploaded) |
| `--av` | also check files with your antivirus (Microsoft Defender or ClamAV) |
| `--min-group 3` | files needed before a pattern gets its own folder (default 2) |
| `--event-min 5` | photos from one day before that day gets its own folder (default 5) |
| `--no-date-prefix` | don't add the date to the front of grouped files' names |
| `--json plan.json` | save the plan as JSON |

Optional extras: `[heic]` reads iPhone photo dates; `[ocr]` reads scanned PDFs (also needs
[Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html)):
`uv tool install "snag-all[heic,ocr] @ git+https://github.com/anjavera/Snag-All-Sorting-Script"`.

## Let Claude sort the tricky leftovers (optional)

For a really tangled folder, the AI assistant Claude can run the script and then find homes
for the files it couldn't place. In [Claude Code](https://claude.com/claude-code):

```
/plugin install snag-all --marketplace anjavera/Snag-All-Sorting-Script
```

Then ask it to "organize my Downloads". Before it looks at anything, it asks:
- what it may see: just file names, document details, or opening unsorted files
- what to leave alone: cloud folders, whole kinds of files, specific folders
- how far to take malware checks

It shows you its suggestions and only moves files after you approve, using the same preview
and undo. Files that look private (taxes, IDs, bank, medical, passwords) are never shown to it.

## How it decides

1. **Safety first.** Every file is checked before it's read; anything suspicious goes
   to `Needs Review`.
2. **Type**: Documents, Spreadsheets, Presentations, Ebooks, Pictures, Videos, Audio,
   Archives, Installers, Code, Fonts, 3D Models. Unknown types and half-finished
   downloads are left alone.
3. **Date**: when the content was made, not when you downloaded it. It uses the photo's
   camera date, the document's creation date (Word, Excel, PowerPoint, LibreOffice, PDF,
   including old `.doc`/`.xls`/`.ppt`), a date in the file name, dates inside a CSV, or
   the file's own date, in that order.
4. **Patterns**: phrases that repeat across files, from page headers, titles, opening lines
   (like a school MLA heading) and names, become folders. `ENGLISH III` and `English 3`
   count as the same; your own name is ignored.
5. **Kinds of documents** inside a pattern: Essays, Notes, Glossaries, Study Guides,
   Quizzes & Tests, Worksheets, Lab Reports, Syllabus, Invoices, Receipts, Statements,
   Resumes and more. Anything else is split by things like `Unit 2` or `Chapter 5`.
6. **Spreadsheets** with the same columns (repeat exports, like bank statements) go together.
7. **Pictures**: Photos, Screenshots, RAW, GIFs, Graphics and other Images, then by year
   and month; a day with lots of photos gets its own folder.
8. **Duplicates**: exact copies go to `Duplicates`.

Sorting your whole home folder (`organize --home -r`) only touches your own files: folders that
belong to code projects (git repos, `package.json`, `.py` files…), installed programs (a `LICENSE`,
`bin`/`lib` folders, versioned names like `tool-1.2.3`), browser profiles, virtual machines, and app
folders like `snap` are left exactly as they are. Archives, installers and other types without a
usual home go into your Downloads folder instead of piling up in your home folder.

Where things go: your usual Documents / Pictures / Videos / Music folders (it follows
OneDrive on Windows and your folder settings on Linux). Archives, installers and other
types without a usual home get tidy subfolders inside the folder you sorted.

### What counts as suspicious

Programs disguised as documents (`invoice.pdf` that's really an `.exe`), fake double
extensions (`photo.jpg.exe`), hidden right-to-left characters in names; Office files with
macros or that load a template from the internet; PDFs that launch programs, run scripts
when opened, or hide programs inside; password-protected archives; archives with
shortcut/script files; small disk-image files (`.iso`, `.img`); `.vbs`, `.hta`, `.lnk`
and similar files that run when double-clicked; images with scripts; saved web pages with
password forms. The website a flagged file came from is shown when your browser recorded
it. On Mac and Linux, flagged files are made non-runnable (undo restores this).

Undo history is kept in `%LOCALAPPDATA%\snag-all` (Windows),
`~/Library/Application Support/snag-all` (Mac) or `~/.local/state/snag-all` (Linux).

## Upgrading from the old Windows version

The first version installed a Desktop icon and a `Ctrl+Alt+O` shortcut. To remove them
(your sorted files stay put), run:

```powershell
powershell -ExecutionPolicy Bypass -File legacy\Uninstall-v1.ps1
```

## For developers

```bash
uv sync
uv run pytest
```

Add file types in `src/file_organizer/classify.py` (`CATEGORIES`) and document kinds in
`src/file_organizer/grouping.py` (`DOC_TYPES`).

## License

[MIT](LICENSE)
