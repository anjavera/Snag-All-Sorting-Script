---
name: organize-files
description: Organize a messy folder (usually Downloads) with the `organize` CLI, then sort what it couldn't place, with the user's privacy choices respected and possibly-malicious files set aside. Use when the user asks to organize, tidy, sort or clean up files or folders, or says their folders are too complicated for the plain script.
---

# Organize files (script first, assistant for the leftovers)

The `organize` CLI does the heavy lifting: dates, types, metadata, recurring
patterns, duplicates, malware heuristics, preview, undo. **You handle only
what it leaves behind, and only within what the user allows.** You never move
files yourself: every move goes through the CLI so it stays previewable,
non-overwriting and undoable.

## 0. Get the tool

Run `organize --version`. If it's missing, use it without installing:

```bash
uvx --from git+https://github.com/anjavera/Snag-All-Sorting-Script organize --version
```

(Use that `uvx --from …` prefix wherever this skill says `organize`. If there's
no `uv`, `pip install git+https://github.com/anjavera/Snag-All-Sorting-Script`.)
Keep plan files in a temp/scratch directory, never inside the folder being organized.

## 1. Ask the privacy questions FIRST, before reading anything

Ask in one round (AskUserQuestion). Default to the most private answer.

1. **What may I see?**
   - *Names only* (default): file names, types, dates → `--json-detail names`
   - *Document details*: also titles, headers, first lines → `--json-detail metadata`
   - *Open unsorted files*: may also open leftovers one at a time to read or look at them
2. **Leave alone** (multi-select; each one is enforced by the CLI, not just by you):
   - Cloud folders: OneDrive, Google Drive, Dropbox, iCloud. Already skipped by default; only add
     `--include-cloud` / `--allow-cloud` if they explicitly choose to include them.
   - A whole type → `--skip-type Pictures` (repeatable)
   - Specific files/folders → `--exclude "Taxes*" --exclude "Medical/*"` (ask for the patterns)
   - *Sensitive-looking files* (tax, IDs, bank, medical, passwords, key files) are always off-limits
     to you: the CLI marks them `"sensitive"` and gives you no contents. Never open them, even if
     they also chose "Open unsorted files".
3. **Where should things go?** Their standard Documents/Pictures/… folders (default), or one folder (`--dest PATH`).
4. **Malware checks:** built-in checks only (default) / also the local antivirus (`--av`) /
   also look flagged files up on VirusTotal **by hash only** (see step 3).

Remember their answers for the whole session and repeat them back in one line.

## 2. Preview with the script

```bash
organize "<folder>" --json "<scratch>/plan.json" --json-detail <names|metadata> [privacy flags] [--av]
```

Summarize for the user: how many files go where (counts per top-level folder), the
patterns found, anything in **Needs Review**, any cloud warning, and what was left
in place. Don't paste the whole list unless they ask.

If the CLI says the folder itself is synced to the cloud, stop and ask; don't add
`--include-cloud` on your own.

## 3. Possibly-unsafe files ("Needs Review")

The script flags these statically (disguised executables, double extensions,
right-to-left name tricks, macro documents, remote-template documents, PDF
JavaScript/launch actions, password-protected archives with programs inside,
script/shortcut files, SVG with scripts). Each entry in `plan.json` has
`unsafe`, `sha256` and `origin` (the URL it was downloaded from, when known).

- **Never** open, preview, extract, run, convert or upload a flagged file, and
  never run one "in a sandbox" yourself. No local sandbox is 99.99% safe, and
  detonating malware isn't your job.
- Explain each finding in plain words, with the origin URL, and say whether the
  user was likely expecting that file.
- If they allowed hash lookups: open `https://www.virustotal.com/gui/file/<sha256>`
  in the browser and report the detection count. Only the hash leaves the computer;
  a hash reveals nothing about a file VirusTotal hasn't already seen.
- If the hash is unknown and they want a verdict, recommend **they** upload it to
  VirusTotal or Hybrid Analysis (purpose-built, isolated detonation). Warn that
  uploading shares the file with security vendors, so it's not for private documents.
  On Windows, Windows Sandbox is a reasonable local option for an expert user.
- Flagged files stay in `Needs Review` unless the user explicitly says one is safe.
  You can't override them; the CLI refuses.

## 4. Sort the leftovers

Leftovers = moves with `"leftover": true` (documents that only got a date folder,
images with no camera or screenshot clues) plus `skipped` entries whose reason is
`unknown type`. Skip anything `sensitive`, `unsafe`, excluded or in the cloud.

Work from what they allowed you to see. Open files only with consent level 3,
one at a time, and only non-sensitive leftovers; images can be viewed directly.
Scanned PDFs (no text layer) are a good use of this.

Ideas that work well:
- Join an existing pattern folder from `patterns` (e.g. a stray essay → `Documents/English 3`).
- School: course → type (Essays, Notes, Glossaries, Study Guides…).
- Money: `Documents/Receipts/<Vendor>`, `Documents/Invoices/<Client>`, `Documents/Bills/<Utility>`.
- Work/projects: one folder per project or client name seen in titles or headers.
- Images: memes/reaction images, wallpapers, logos/brand assets, diagrams, scanned documents → Documents.
- Installers already used → `Installers/Old installers` (suggest the user may delete them; never delete).
- Unknown types: map to the closest root (`Code`, `3D Models`, `Fonts`, `Archives`…).

Rules: allowed roots are `Documents, Spreadsheets, Presentations, Ebooks, Pictures,
Videos, Audio, Archives, Installers, Code, Fonts, 3D Models`. Use short Title Case
folder names at most 4 levels deep. Prefer folders that already exist or hold 2+
files. Don't rename files. When unsure, leave a file where the script put it.

Write the proposal as JSON mapping each file path to a folder, show it to the user
as a short table, and ask for approval:

```json
{"/home/sam/Downloads/scan0042.pdf": "Documents/Receipts/Costco"}
```

## 5. Apply

```bash
organize "<folder>" --overrides "<scratch>/overrides.json" [same flags]          # preview again
organize "<folder>" --overrides "<scratch>/overrides.json" [same flags] --apply  # after a clear yes
```

Report what moved and remind them: **`organize --undo` puts everything back.**

## Never

- Move, rename, delete or upload files yourself, or overwrite anything.
- Add `--include-cloud`, `--allow-cloud`, `--json-detail metadata` or open files beyond what the user chose.
- Open sensitive or flagged files, or send any file's contents anywhere.
