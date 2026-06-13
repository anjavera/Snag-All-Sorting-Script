<#
.SYNOPSIS
    Installs win-downloads-sorter: copies the script into a per-user location and
    creates a clickable Desktop shortcut plus a Start Menu shortcut with a
    Ctrl+Alt+O hotkey.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Install.ps1 -InstallDir "D:\Tools\Organizer"
#>

[CmdletBinding()]
param(
    # Where the program files are installed. Per-user, no admin rights needed.
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\DownloadsOrganizer",

    # Global hotkey for the Start Menu shortcut.
    [string]$Hotkey = 'CTRL+ALT+O'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- 1. Copy program files into the install dir ---------------------------
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $InstallDir 'icons') -Force | Out-Null

Copy-Item (Join-Path $here 'Organize-Downloads.ps1') $InstallDir -Force
Copy-Item (Join-Path $here 'Organize-Downloads.bat') $InstallDir -Force
Copy-Item (Join-Path $here 'icons\organize.ico') (Join-Path $InstallDir 'icons') -Force

$bat = Join-Path $InstallDir 'Organize-Downloads.bat'
$ico = Join-Path $InstallDir 'icons\organize.ico'

# --- 2. Shortcuts ---------------------------------------------------------
$ws       = New-Object -ComObject WScript.Shell
$desktop  = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')

# Desktop: clickable, custom icon, no hotkey (avoids a duplicate-hotkey conflict).
$d = $ws.CreateShortcut((Join-Path $desktop 'Organize Downloads.lnk'))
$d.TargetPath       = $bat
$d.WorkingDirectory = $env:USERPROFILE
$d.Description      = 'Sort Downloads into Documents/Pictures/Videos by month'
$d.IconLocation     = "$ico,0"
$d.Save()

# Start Menu: same target/icon, plus the global hotkey.
$s = $ws.CreateShortcut((Join-Path $programs 'Organize Downloads.lnk'))
$s.TargetPath       = $bat
$s.WorkingDirectory = $env:USERPROFILE
$s.Description      = 'Sort Downloads into Documents/Pictures/Videos by month'
$s.IconLocation     = "$ico,0"
$s.Hotkey           = $Hotkey
$s.Save()

# --- 3. Done --------------------------------------------------------------
Write-Host ""
Write-Host "Installed to: $InstallDir" -ForegroundColor Green
Write-Host "Desktop shortcut: 'Organize Downloads' (double-click to run)"
Write-Host "Start Menu shortcut hotkey: $Hotkey"
Write-Host ""
Write-Host "Tip: run a dry run first with:  powershell -ExecutionPolicy Bypass -File `"$InstallDir\Organize-Downloads.ps1`" -WhatIf"
