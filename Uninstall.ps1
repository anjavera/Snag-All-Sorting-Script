<#
.SYNOPSIS
    Removes win-downloads-sorter: deletes the Desktop and Start Menu shortcuts
    and the installed program folder. Does NOT touch any files you've already
    organized.
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\DownloadsOrganizer"
)

$desktop  = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')

foreach ($lnk in @(
    (Join-Path $desktop  'Organize Downloads.lnk'),
    (Join-Path $programs 'Organize Downloads.lnk')
)) {
    if (Test-Path -LiteralPath $lnk) {
        Remove-Item -LiteralPath $lnk -Force
        Write-Host "Removed shortcut: $lnk"
    }
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
    Write-Host "Removed install dir: $InstallDir"
}

Write-Host "Uninstalled. Your sorted files were left untouched." -ForegroundColor Green
