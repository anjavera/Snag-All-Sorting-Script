"""File categories (by extension) and the best-available date for each file."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from .extract import Meta

CATEGORIES: dict[str, tuple[str, ...]] = {
    "Documents": (".pdf", ".doc", ".docx", ".docm", ".dotx", ".odt", ".rtf", ".txt", ".md",
                  ".markdown", ".tex", ".pages", ".wpd"),
    "Spreadsheets": (".xls", ".xlsx", ".xlsm", ".ods", ".csv", ".tsv", ".numbers"),
    "Presentations": (".ppt", ".pptx", ".odp", ".key"),
    "Ebooks": (".epub", ".mobi", ".azw", ".azw3", ".djvu"),
    "Pictures": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tif",
                 ".tiff", ".avif", ".svg", ".ico", ".psd", ".xcf",
                 ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".srw"),
    "Videos": (".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".mpg", ".mpeg", ".3gp"),
    "Audio": (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".mid", ".midi"),
    "Archives": (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".iso"),
    "Installers": (".exe", ".msi", ".msix", ".dmg", ".pkg", ".deb", ".rpm", ".appimage", ".apk",
                   ".flatpakref", ".snap"),
    "Code": (".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yml", ".yaml", ".sh", ".ps1",
             ".bat", ".ipynb", ".c", ".cpp", ".h", ".java", ".go", ".rs", ".sql", ".toml"),
    "Fonts": (".ttf", ".otf", ".woff", ".woff2"),
    "3D Models": (".stl", ".obj", ".fbx", ".blend", ".glb", ".gltf", ".3mf"),
}
EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}

# Categories whose files are mined for recurring topics ("English 3", "Invoice", ...).
TEXTUAL = {"Documents", "Spreadsheets", "Presentations"}

# Picture sub-kinds: extension first, then metadata.
RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".srw"}
GRAPHIC_EXT = {".svg", ".ico", ".psd", ".xcf"}
SCREENSHOT_RE = re.compile(
    r"screen ?shot|screenshot|screen recording|^scrnli_|^snip(ping)?[ _-]?\d|^capture[ _-]?\d*$", re.I)
PHONE_NAME_RE = re.compile(r"^(IMG|PXL|DSC|DSCN|DCIM|MVIMG|VID|PHOTO)[-_]", re.I)
SCREENSHOT_APPS = re.compile(r"screenshot|snipping|spectacle|flameshot|greenshot|sharex|shutter", re.I)

# Files that are still downloading or are OS cruft.
IN_PROGRESS = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp", ".!ut"}
IGNORED_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


def category(path: Path) -> str | None:
    return EXT_TO_CATEGORY.get(path.suffix.lower())


def picture_kind(path: Path, meta: Meta) -> str:
    ext = path.suffix.lower()
    if ext in RAW_EXT:
        return "RAW"
    if ext in GRAPHIC_EXT:
        return "Graphics"
    if ext == ".gif":
        return "GIFs"
    if SCREENSHOT_RE.search(path.stem) or SCREENSHOT_APPS.search(meta.software):
        return "Screenshots"
    if meta.camera or meta.taken:
        return "Photos"
    if PHONE_NAME_RE.search(path.stem):
        return "Photos"
    return "Images"  # saved/downloaded images with no camera metadata

# --- dates -----------------------------------------------------------------

_FILENAME_DATES = [
    # 2024-05-12 / 2024_05_12 / 2024.05.12, optional time 14.30.00 / 14-30-00
    re.compile(r"(?<!\d)(?P<y>(19|20)\d\d)[-_.](?P<m>[01]\d)[-_.](?P<d>[0-3]\d)"
               r"(?:[ _T-]*(?:at )?(?P<H>[0-2]?\d)[.:-](?P<M>[0-5]\d)(?:[.:-](?P<S>[0-5]\d))?)?"),
    # 20240512 with optional _143000  (IMG_20240512_143000, PXL_20240512..., IMG-20240512-WA0001)
    re.compile(r"(?<!\d)(?P<y>(19|20)\d\d)(?P<m>[01]\d)(?P<d>[0-3]\d)"
               r"(?:[_-](?P<H>[0-2]\d)(?P<M>[0-5]\d)(?P<S>[0-5]\d))?(?!\d)"),
]


def date_from_name(name: str) -> datetime | None:
    for rx in _FILENAME_DATES:
        for m in rx.finditer(name):
            try:
                dt = datetime(int(m["y"]), int(m["m"]), int(m["d"]),
                              int(m["H"] or 0), int(m["M"] or 0), int(m["S"] or 0))
            except ValueError:
                continue
            if _plausible(dt):
                return dt
    return None


def _plausible(dt: datetime | None) -> bool:
    return dt is not None and datetime(1990, 1, 1) <= dt <= datetime.now()


def fs_date(path: Path) -> datetime:
    """Earliest timestamp the filesystem has (birth time where the OS records it)."""
    st = path.stat()
    stamps = [st.st_mtime]
    birth = getattr(st, "st_birthtime", None)  # macOS, Windows (3.12+), some Linux
    if birth:
        stamps.append(birth)
    elif os.name == "nt":
        stamps.append(st.st_ctime)  # creation time on older Windows Pythons
    return datetime.fromtimestamp(min(stamps))


def best_date(path: Path, meta: Meta) -> tuple[datetime, str]:
    """Pick the date that best reflects when the content was actually made.

    Download/copy resets a file's modified time, so embedded metadata wins:
    camera capture time > document creation date > date in the filename >
    latest date in the data > document modified date > filesystem timestamps.
    """
    for dt, why in (
        (meta.taken, "EXIF capture time"),
        (meta.created, f"{meta.source} creation date"),
        (date_from_name(path.stem), "date in filename"),
        (meta.content_date, "latest date inside the file"),
        (meta.modified, f"{meta.source} modified date"),
    ):
        if _plausible(dt):
            return dt, why
    return fs_date(path), "file timestamp"
