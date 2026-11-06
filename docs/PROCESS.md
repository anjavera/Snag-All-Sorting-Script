# How v2 was built

This documents the rewrite of `win-downloads-sorter` (a 104-line Windows-only
PowerShell script) into a cross-platform, metadata-aware organizer: the process,
the capabilities used, and the workflow, including what was deliberately *not*
used to keep cost down.

## Goal

1. **OS agnostic**: Windows, macOS and Linux from one codebase.
2. **Chronological**: file things by when the content was *made*, using metadata, not download time.
3. **Differentiate by type**: extension first, refined by metadata (photo vs screenshot vs RAW vs GIF).
4. **Pattern grouping**: spot recurring details ("English 3" in headers) and create
   topic folders, split into sub-types (Essays, Glossaries, Notes…).

## Workflow

```
locate ──► read ──► design ──► build ──► test ──► real-data dry run ──► review ──► fix ──► document
 (gh)     (v1)    (inline)   (modules)  (pytest,     (read-only,          (code-review  (regression
                                         py3.10+3.14)  scratchpad JSON)     skill, high)  tests)
```

1. **Locate**: `gh repo list` found `anjavera/win-downloads-sorter`, cloned next
   to the site repo. The site's description ("Needs Python") set the language choice.
2. **Read v1**: the whole script (extension map → `~/Documents|Pictures|…/yyyy-MM`,
   never-overwrite, `-WhatIf` preview). Those behaviors were carried forward, and
   the preview became the default.
3. **Design inline**: the request was specific enough that no separate planning
   agent or brainstorming round was needed. Key decisions:
   - **Python + stdlib-first.** DOCX/XLSX/PPTX/ODT are ZIPs of XML, so they're read
     directly (no python-docx). Only `pypdf` (PDF metadata/text), `Pillow` (EXIF)
     and `defusedxml` (safe XML) are dependencies; HEIC is an optional extra.
   - **Explainable heuristics over ML.** Weighted phrase signals plus thresholds,
     with every move carrying a human-readable reason (`--explain`). No model
     downloads, no network, runs in about 1.5s on a real Downloads folder.
   - **Safety first.** Preview by default, never overwrite, undo log for every run.
4. **Build**: six small modules, each with one job (table below).
5. **Test**: pytest fixtures generate *realistic* files: Word docs with MLA heading
   lines and running headers, `ENGLISH III` vs `English 3`, EXIF photos, PDFs with
   creation dates, byte-identical duplicates, bank-style CSVs. The suite runs on
   Python 3.10 (minimum) and 3.14.
6. **Real-data dry run**: a read-only preview against the actual `~/Downloads`,
   with the plan written as JSON to the session scratchpad. Only summary counts
   were inspected, to avoid dumping personal file names and to save tokens.
7. **Review**: the `code-review` skill at high effort found 10 issues. The most
   important: Word **page-number fields** made the MLA header "Talavera 1" look
   like a course and swallow every class. All 10 were fixed, each with a
   regression test where testable (13 tests total).
8. **Document**: README (users) and this file (process).

## Architecture

| Module | Job |
| --- | --- |
| `extract.py` | Per-format metadata and text: OOXML core props, headers/footers (field codes stripped), first body lines, slide text, sheet names and first row; ODF meta/content/styles; PDF info dict, first-page lines, running headers (lines repeated across pages); image EXIF capture time, camera, software; CSV columns and dates in rows. |
| `classify.py` | Extension → category; picture kind; **date resolution** (EXIF → doc created → filename date → CSV row dates → doc modified → filesystem birth/mtime). |
| `grouping.py` | Tokenize (camelCase, `English3` → `English 3`, roman numerals), build weighted phrase signals per file, discover recurring phrases (most specific wins, near-universal phrases and author names ignored, groups below threshold dissolve and re-assign), keyword doc-type rules, and a second pass for leftovers (`Unit 2`). |
| `planner.py` | Scan (skips in-progress downloads, hidden files, unreadable entries), SHA-256 duplicate detection, OS-standard folders (Windows / macOS `Movies` / Linux XDG `user-dirs.dirs`), destinations, collision-free names. Pure: touches nothing. |
| `apply.py` | Moves with `shutil.move` (cross-drive safe, keeps timestamps), writes an undo log after *every* move, undo restores files and removes created folders. |
| `cli.py` | `organize [SOURCE] [--dest] [--apply] [-r] [--min-group] [--explain] [--json] [--undo]`. |

### Signal weights (pattern detection)

| Where a phrase is found | Weight |
| --- | --- |
| Page header / footer, PDF running header | 3.0 |
| Title / subject / keywords metadata | 2.5 |
| Opening lines (MLA heading lives here) | 2.0 |
| File name | 1.5 |
| Course-like (`English 3`, `AP Biology`, `MATH 101`, `Chem II`) | +2.0 bonus |
| Multi-word phrase | ×(1 + 0.3 per extra word) |

## Capabilities used

| Capability | Used for |
| --- | --- |
| `gh` CLI (authenticated) | Finding and cloning the repo |
| Bash / Read / Write / Edit | All code and docs; scripted multi-edits to save round trips |
| `uv` | Env + lockfile, `organize` entry point, isolated Python 3.10 compatibility run |
| pytest | 13 tests with generated real-format fixtures |
| `code-review` skill (high) | Bug hunt before commit (10 found, 10 fixed) |
| `security-guidance` plugin hook | Flagged stdlib XML on untrusted input → switched to `defusedxml` |
| Session scratchpad | Real-data dry-run output kept out of the repo |
| Superpowers workflow (explore → plan → implement → review) | Followed inline instead of through subagents |

### Deliberately not used (overhead control)

- **Subagents / parallel sessions**: the codebase was a single small script.
  Spawning explorers or planners would have re-read the same context several times.
- **Context7 docs lookups**: the only third-party APIs (pypdf metadata, Pillow
  EXIF) are stable, and the tests exercise both, so a wrong call would have failed there.
- **Playwright / browser**: there's no web UI; this is a CLI.
- **Connectors (Google Drive, etc.)**: not needed to organize local files. A possible
  future input source (see below).
- **ML / embeddings**: would add large downloads and make decisions hard to explain;
  weighted phrase signals cover the stated use case and are inspectable.

## Known limits / next ideas

- Windows: folders redirected to OneDrive are not detected (uses `%USERPROFILE%\Documents`).
- Legacy `.doc` / `.xls` / `.ppt` (binary Office) are sorted by type and date, but their contents aren't read.
- Scanned PDFs without a text layer contribute only metadata and file name (no OCR).
- Ideas: pictures grouped into events by time gaps / GPS; a GUI or tray button;
  reading from Google Drive via its connector.
