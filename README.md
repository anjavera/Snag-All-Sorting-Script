# win-downloads-sorter

<p align="center">
  <img src="icons/organize-cut.png" alt="win-downloads-sorter icon" width="128">
</p>

A tiny, **manually-triggered** Windows tool that tidies your **Downloads** folder. You run it when _you_ want — nothing watches your folders in the background. It sorts files by type into **Documents / Pictures / Videos / Music**, filing each into a `yyyy-MM` subfolder (e.g. `2026-06`) based on the file's modified date.

```
Downloads\report.pdf        ->  Documents\2026-06\report.pdf
Downloads\vacation.jpg      ->  Pictures\2026-06\vacation.jpg
Downloads\clip.mp4          ->  Videos\2026-06\clip.mp4
Downloads\song.mp3          ->  Music\2026-06\song.mp3
```

## Requirements

- Windows 10 or 11
- Windows PowerShell 5.1+ (built in) or PowerShell 7+

## Install

```powershell
git clone https://github.com/anjavera/win-downloads-sorter.git
cd win-downloads-sorter
powershell -ExecutionPolicy Bypass -File Install.ps1
```

This copies the program to `%LOCALAPPDATA%\Programs\DownloadsOrganizer`, adds an **"Organize Downloads"** icon to your Desktop, and registers a **`Ctrl+Alt+O`** hotkey via a Start Menu shortcut. No admin rights needed.

## Usage

- **Double-click** the _Organize Downloads_ icon on your Desktop, **or**
- Press **`Ctrl+Alt+O`** from anywhere.

A window opens, shows what it moved, and pauses so you can read the results.

**Preview first (moves nothing):**

```powershell
powershell -ExecutionPolicy Bypass -File "Organize-Downloads.ps1" -WhatIf
```

## How it works

- Looks at **top-level files in `Downloads` only** — it won't dig into folders you've already sorted.
- Maps each file extension to a destination (Documents / Pictures / Videos / Music).
- Creates a **`yyyy-MM`** subfolder from each file's last-modified date (year-first so Explorer sorts folders chronologically).
- **Never overwrites:** if a file with the same name exists, it appends ` (1)`, ` (2)`, …
- **Unknown file types are left alone** and reported as skipped.

## Customize

Open `Organize-Downloads.ps1`:

- **Add file types** — extend the `$categories` hashtable:
  ```powershell
  '.epub' = "$HOME\Documents"
  '.zip'  = "$HOME\Documents\Archives"
  ```
- **Change the folder-name format** — pass `-DateFormat`:
  ```powershell
  # 06-2026 instead of 2026-06
  .\Organize-Downloads.ps1 -DateFormat 'MM-yyyy'
  ```
- **Sort a different folder** — pass `-Source "D:\Incoming"`.

To change the hotkey, re-run the installer: `Install.ps1 -Hotkey "CTRL+ALT+D"`.

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File Uninstall.ps1
```

Removes the shortcuts and the installed program. **Your already-sorted files are left untouched.**

## License

[MIT](LICENSE)
