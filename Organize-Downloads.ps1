<#
.SYNOPSIS
    Manually-triggered Downloads organizer.

.DESCRIPTION
    Sorts files from your Downloads folder into Documents / Pictures / Videos /
    Music, placing each file inside a month-year subfolder (MM-yyyy, e.g. 06-2026)
    based on the file's last-modified date.

    Run it yourself whenever you want to tidy up:
        powershell -ExecutionPolicy Bypass -File "$HOME\bin\Organize-Downloads.ps1"

    Preview without moving anything:
        ... -File "$HOME\bin\Organize-Downloads.ps1" -WhatIf
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    # Source folder to clean up.
    [string]$Source = "$HOME\Downloads",

    # Folder-name format for the month-year buckets. Default: 2026-06
    [string]$DateFormat = 'yyyy-MM'
)

# --- Category map: extension -> destination root --------------------------
# Add or change a line here to support more file types.
$categories = @{
    # Documents
    '.pdf'  = "$HOME\Documents"
    '.doc'  = "$HOME\Documents"
    '.docx' = "$HOME\Documents"
    '.txt'  = "$HOME\Documents"
    '.xlsx' = "$HOME\Documents"
    '.pptx' = "$HOME\Documents"

    # Pictures
    '.jpg'  = "$HOME\Pictures"
    '.jpeg' = "$HOME\Pictures"
    '.png'  = "$HOME\Pictures"
    '.gif'  = "$HOME\Pictures"
    '.heic' = "$HOME\Pictures"
    '.webp' = "$HOME\Pictures"

    # Videos
    '.mp4'  = "$HOME\Videos"
    '.mov'  = "$HOME\Videos"
    '.mkv'  = "$HOME\Videos"
    '.avi'  = "$HOME\Videos"

    # Music
    '.mp3'  = "$HOME\Music"
    '.wav'  = "$HOME\Music"
    '.flac' = "$HOME\Music"
}

if (-not (Test-Path -LiteralPath $Source)) {
    Write-Error "Source folder not found: $Source"
    return
}

$moved   = 0
$skipped = 0

# Only top-level files; don't recurse into your already-sorted folders.
Get-ChildItem -LiteralPath $Source -File | ForEach-Object {
    $file = $_
    $ext  = $file.Extension.ToLowerInvariant()

    $destRoot = $categories[$ext]
    if (-not $destRoot) {
        Write-Verbose "Skipping (unmapped type): $($file.Name)"
        $skipped++
        return
    }

    # Month-year bucket from the file's own date.
    $bucket  = $file.LastWriteTime.ToString($DateFormat)
    $destDir = Join-Path $destRoot $bucket

    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    # Avoid clobbering: if a same-named file exists, append a counter.
    $target = Join-Path $destDir $file.Name
    if (Test-Path -LiteralPath $target) {
        $base = [IO.Path]::GetFileNameWithoutExtension($file.Name)
        $n = 1
        do {
            $target = Join-Path $destDir ("{0} ({1}){2}" -f $base, $n, $file.Extension)
            $n++
        } while (Test-Path -LiteralPath $target)
    }

    if ($PSCmdlet.ShouldProcess($file.FullName, "Move to $target")) {
        Move-Item -LiteralPath $file.FullName -Destination $target
        Write-Host "Moved: $($file.Name)  ->  $target"
        $moved++
    }
}

Write-Host ""
Write-Host "Done. Moved $moved file(s); skipped $skipped unmapped file(s)." -ForegroundColor Green
