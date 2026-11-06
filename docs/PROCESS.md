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

---

# Phase 2 (v2.1): limits, privacy, safety, assistant mode

## Goals

1. Close the v2.0 known limits.
2. **Script first, assistant second**: for complicated folders, Claude runs the script,
   then sorts only what the script couldn't place.
3. **Privacy question up front**: the user decides what Claude may see and what is left
   alone (types, folders, Google Drive / OneDrive / Dropbox / iCloud).
4. **Malicious files**: decide what the script should detect and what an LLM should (or shouldn't) do.

## Design decision: who does what

| Job | Who | Why |
| --- | --- | --- |
| Dates, types, patterns, duplicates | Script | Deterministic, offline, fast, free |
| Privacy enforcement | **Script** | A rule the LLM *should* follow is weaker than one the CLI *can't break*: excluded files are never opened and are reported only as counts; sensitive files get no metadata in JSON; the cloud is refused without a flag |
| Malware tripwires | **Script** | Static byte/name checks need no LLM, work offline, and run *before* any parser touches the file |
| Explaining a flag, hash lookup, next steps | Assistant | Judgment and plain-language explanation; VirusTotal lookup by **hash only**, with consent |
| Executing a suspicious file "in a sandbox" | **Nobody here** | No local sandbox an assistant can drive is 99.99% safe, and detonation isn't an organizer's job. The skill sends the user to purpose-built services (VirusTotal / Hybrid Analysis, uploaded by the user after a privacy warning) or Windows Sandbox for experts |
| Leftovers (ambiguous names, unknown types, scans) | Assistant | Needs semantic judgment; proposes folders as JSON, which the CLI validates (known roots only, sanitized names, flagged files can't be overridden) and applies with the same preview/undo guarantees |

The assistant **never moves files itself**: every move goes through `organize`, so
"never overwrite" and `--undo` hold in assistant mode too.

## Packaging: plugin + skill (not an MCP connector)

- **Skill** (`skills/organize-files/SKILL.md`): the workflow is mostly *instructions*
  (ask privacy questions → preview → triage → leftovers → approve → apply). That's what
  skills are for, and it costs nothing until it's invoked.
- **Plugin** (`.claude-plugin/`): makes the skill installable in one line
  (`/plugin install file-organizer --marketplace anjavera/win-downloads-sorter`); the repo
  is its own marketplace. Validated with `claude plugin validate` (manifest, icon, README install line).
- **Not an MCP connector (yet)**: Claude Code already has a shell to run the CLI, so a
  server would add a process to run, with nothing gained. An MCP server becomes worth it
  for chat apps without a shell (Claude Desktop chat); it's listed below as a next step.
- **Not a Google Drive/OneDrive connector**: cloud folders are deliberately *off* by
  default. Organizing cloud storage remotely is a different product with different risks.

## What was built

| Area | Change |
| --- | --- |
| Known limits | Windows folder locations read from the registry (follows OneDrive redirection); legacy `.doc/.xls/.ppt` metadata via `olefile`, plus `.doc` body text (UTF-16 run extraction, tested on a LibreOffice-made Word 97 file); optional OCR extra (`pypdfium2` + Tesseract) for scanned PDFs; photo-burst days (5+ photos) get their own folder |
| Privacy | `--exclude`, `--skip-type`, cloud-sync detection (OneDrive/Google Drive/Dropbox/iCloud/Box/pCloud/MEGA/Nextcloud, macOS CloudStorage), `--include-cloud`, `--allow-cloud`, sensitive-file tagging (tax, IDs, bank, medical, keys), `--json-detail names\|metadata` |
| Safety (`safety.py`) | Disguised programs (magic bytes), double extensions, right-to-left name tricks, padded names, script-host/shortcut types, small ISO/IMG/VHD and OneNote files, Office macros (OOXML and OLE), remote-template injection, PDF launch actions / auto-run JavaScript / embedded programs, encrypted archives and lure archives, SVG scripts, phishing pages with password forms; download origin (Windows Mark-of-the-Web, macOS `mdls`, Linux xattr); SHA-256 for hash lookups; batched local AV (`--av`: Defender / ClamAV); flagged files go to `Needs Review` with execute permission removed (restored by undo) |
| Assistant hooks | `--json` now marks `leftover`, `sensitive`, `unsafe`, `sha256`, `origin`, `withheld` counts; `--overrides` applies approved placements through all the usual safeguards |

## How false alarms were tuned out

A security flag nobody trusts is worse than none, so every rule was tested against benign lookalikes:

1. **Code review** (`code-review` skill, high) found 10 issues, 7 of them false positives:
   fillable tax/school PDFs (calculation JavaScript), e-invoices (embedded XML), WebP saved
   as `.jpg`, `.js`/`.ps1` code files, Linux `.run`/`.bin` installers, a clamscan run per
   file, and others. All 10 fixed, with regression tests.
2. **Real-data dry run**: the preview on the real `~/Downloads` still flagged 4 harmless
   files (two web-code zips with `.js` inside, the Ubuntu and OPNsense ISOs). Rules were
   narrowed to what attacks actually look like: script-host/shortcut files or disguised
   names inside archives, and *small* disk images. Result: **0 false positives** on real data.
3. A `.xls` that was really tab-separated text (a website "export to Excel") showed that
   extension/content mismatches are usually sloppiness, so only a *program* in disguise is flagged.

## Verification

- 38 tests (pytest) on Python 3.10 and 3.14: malware heuristics *and* benign lookalikes,
  privacy (exclude, skip-type, cloud source/subfolder/destination, withheld counts,
  sensitive redaction), overrides validation, the full assistant round trip through the
  CLI (preview → JSON → overrides → apply → undo), permission restore on undo, legacy `.doc`.
- `claude plugin validate .`: passes.
- Not verified end-to-end here: OCR (Tesseract isn't installed on this machine;
  the code path is guarded and optional), Windows registry / Defender, macOS `mdls` (no
  Windows/macOS machine in this session).

## Capabilities used in phase 2

`gh` (push, PR #1), PR status tool, `uv` (multi-version testing), pytest, LibreOffice
(headless, to generate a real Word 97 fixture), `olefile`, `code-review` skill (high),
`claude plugin validate`, existing installed plugins as format references (instead of
recalling the manifest schema), session scratchpad for real-data previews (only counts
were read, no file names or contents).

## Remaining ideas

- MCP server wrapping the CLI for chat apps without a shell (Claude Desktop chat).
- A small GUI / tray button for non-terminal users.
- Photo events across midnight / by GPS place names (needs an offline geocoder to stay private).
- Real Word piece-table parsing for non-ASCII `.doc` text.
