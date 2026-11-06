"""Turn a folder of files into a list of planned moves (nothing touches disk here)."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import grouping, safety
from .classify import IGNORED_NAMES, IN_PROGRESS, TEXTUAL, best_date, category, picture_kind
from .extract import Meta, extract

REVIEW = "Needs Review"  # where possibly-unsafe files are set aside
SETTLE_SECONDS = 30  # skip files touched this recently: probably still downloading
_LEADING_DATE = re.compile(r"^\d{4}[-_.]\d{2}[-_.]\d{2}")
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


@dataclass
class Item:
    path: Path
    category: str
    meta: Meta
    date: datetime
    date_why: str
    size: int
    topic: str | None = None
    subgroup: str | None = None
    group_root: str = "Documents"  # which category root a topic folder lives under
    kind: str = ""                 # picture kind (Photos, Screenshots, ...)
    findings: list[safety.Finding] = field(default_factory=list)
    origin: str = ""               # download URL recorded by the browser, if any
    sensitive: str = ""            # why this looks private (tax, passport, key file...)
    sha256: str = ""               # for flagged files: look up by hash without uploading the file
    why: list[str] = field(default_factory=list)


@dataclass
class Move:
    src: Path
    dst: Path
    why: str
    item: Item | None = None
    leftover: bool = False  # only got a generic date folder: a candidate for a closer look


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    topics: dict[str, int] = field(default_factory=dict)
    review: list[Item] = field(default_factory=list)       # flagged as possibly unsafe
    cloud_targets: dict[str, int] = field(default_factory=dict)  # sync service -> files moving into it


class CloudSourceError(Exception):
    """The folder to organize is inside a cloud-synced folder and --include-cloud wasn't given."""


# --- privacy -----------------------------------------------------------------

_CLOUD_DIRS = [
    ("OneDrive", re.compile(r"^OneDrive( - .+)?$", re.I)),
    ("Google Drive", re.compile(r"^(Google ?Drive.*|My Drive|Shared drives)$", re.I)),
    ("Dropbox", re.compile(r"^Dropbox( \(.+\))?$", re.I)),
    ("iCloud Drive", re.compile(r"^(iCloud ?Drive.*|Mobile Documents)$", re.I)),
    ("Box", re.compile(r"^Box( Sync)?$", re.I)),
    ("pCloud", re.compile(r"^pCloud ?Drive$", re.I)),
    ("MEGA", re.compile(r"^MEGA$")),
    ("Nextcloud", re.compile(r"^Nextcloud$", re.I)),
]


def cloud_service(path: Path) -> str:
    """Name of the sync service that uploads this path, or '' if it stays on this computer."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(var)
        if root and (path == Path(root) or Path(root) in path.parents):
            return "OneDrive"
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "CloudStorage" and i + 1 < len(parts):  # macOS ~/Library/CloudStorage/<Provider>-<account>
            return parts[i + 1].split("-")[0]
        for name, rx in _CLOUD_DIRS:
            if rx.match(part):
                return name
    return ""


SENSITIVE_RE = re.compile(
    r"\b(tax(es)?|w-?2|1099|1040|ssn|social security|passports?|driver'?s? licen[cs]e|bank|statements?|"
    r"routing|account (number|no)|medical|health|insurance|diagnos\w*|prescriptions?|lab results|"
    r"passwords?|passcodes?|recovery (codes?|key)|seed phrase|private key|payslips?|pay ?stubs?|salary|"
    r"id card|birth certificate|visa|i-?9|immigration|loan|mortgage|credit report)\b", re.I)
SENSITIVE_EXT = {".kdbx", ".kdb", ".pem", ".ppk", ".p12", ".pfx", ".gpg", ".asc", ".ovpn", ".1pux", ".wallet"}


def sensitive_reason(path: Path, meta: Meta | None = None) -> str:
    if path.suffix.lower() in SENSITIVE_EXT:
        return f"'{path.suffix.lower()}' key/credential file"
    texts = [" ".join(grouping.tokenize(path.stem))]
    if meta:
        texts += [meta.title, meta.subject, *meta.headers[:3], *meta.lines[:4]]
    m = next((SENSITIVE_RE.search(t) for t in texts if t and SENSITIVE_RE.search(t)), None)
    return f"mentions '{m[0]}'" if m else ""


# --- where things go ---------------------------------------------------------

def _xdg_dirs() -> dict[str, Path]:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "user-dirs.dirs"
    out: dict[str, Path] = {}
    if cfg.is_file():
        for line in cfg.read_text(errors="ignore").splitlines():
            m = re.match(r'XDG_(\w+)_DIR="(.+)"', line.strip())
            if m:
                out[m[1]] = Path(m[2].replace("$HOME", str(Path.home())))
    return out


def _windows_dirs() -> dict[str, Path]:
    """Real locations from the registry -- these move when OneDrive "backs up" Documents/Pictures."""
    try:
        import winreg
    except ImportError:
        return {}
    values = {"DOCUMENTS": "Personal", "PICTURES": "My Pictures", "VIDEOS": "My Video",
              "MUSIC": "My Music", "DOWNLOAD": "{374DE290-123F-4565-9164-39C4925E467B}"}
    out: dict[str, Path] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            for k, v in values.items():
                try:
                    out[k] = Path(os.path.expandvars(winreg.QueryValueEx(key, v)[0]))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def user_dirs() -> dict[str, Path]:
    """The OS's standard per-user folders (Windows incl. OneDrive redirection, macOS, Linux/XDG)."""
    home = Path.home()
    dirs = {
        "DOWNLOAD": home / "Downloads",
        "DOCUMENTS": home / "Documents",
        "PICTURES": home / "Pictures",
        "VIDEOS": home / ("Movies" if sys.platform == "darwin" else "Videos"),
        "MUSIC": home / "Music",
    }
    if sys.platform == "win32":
        dirs.update(_windows_dirs())
    elif sys.platform.startswith("linux") or "bsd" in sys.platform:
        dirs.update({k: v for k, v in _xdg_dirs().items() if k in dirs})
    return dirs


def category_roots(source: Path, dest: Path | None) -> dict[str, Path]:
    from .classify import CATEGORIES

    extra = ["Duplicates", REVIEW]
    if dest is not None:
        return {c: dest / c for c in [*CATEGORIES, *extra]}
    u = user_dirs()
    roots = {c: source / c for c in [*CATEGORIES, *extra]}  # misc types tidy in place
    roots.update({
        "Documents": u["DOCUMENTS"],
        "Spreadsheets": u["DOCUMENTS"] / "Spreadsheets",
        "Presentations": u["DOCUMENTS"] / "Presentations",
        "Ebooks": u["DOCUMENTS"] / "Ebooks",
        "Pictures": u["PICTURES"],
        "Videos": u["VIDEOS"],
        "Audio": u["MUSIC"],
    })
    return roots


def default_source() -> Path:
    return user_dirs()["DOWNLOAD"]


def safe_name(name: str) -> str:
    name = _BAD_CHARS.sub(" ", name).strip().rstrip(". ")
    name = re.sub(r"\s+", " ", name)[:80] or "Untitled"
    return f"{name}_" if name.lower() in _WIN_RESERVED else name


# --- scanning ----------------------------------------------------------------

@dataclass
class Privacy:
    exclude: list[str] = field(default_factory=list)   # glob patterns: never opened, never moved
    skip_types: set[str] = field(default_factory=set)  # categories left alone, e.g. {"Pictures"}
    include_cloud: bool = False                        # also touch cloud-synced folders

    def excluded(self, path: Path, source: Path) -> bool:
        rel = path.relative_to(source).as_posix().lower() if source in path.parents else path.name.lower()
        return any(fnmatch.fnmatch(rel, p.lower()) or fnmatch.fnmatch(path.name.lower(), p.lower())
                   for p in self.exclude)


def scan(source: Path, *, recursive: bool, exclude: list[Path], privacy: Privacy | None = None,
         use_av: bool = False) -> tuple[list[Item], list[tuple[Path, str]]]:
    privacy = privacy or Privacy()
    items: list[Item] = []
    skipped: list[tuple[Path, str]] = []
    now = time.time()
    source = source.resolve()
    if not privacy.include_cloud and cloud_service(source):
        raise CloudSourceError(cloud_service(source))
    # Don't descend into output folders -- unless the source *is* one (organize ~/Documents -r).
    excluded = [e for e in (p.resolve() for p in exclude) if e != source and e not in source.parents]
    skip_types = {t.lower() for t in privacy.skip_types}

    def walk(folder: Path):
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            skipped.append((folder, f"can't read folder ({exc.strerror or exc})"))
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if privacy.excluded(entry, source):
                skipped.append((entry, "excluded by you (not opened)"))
                continue
            if entry.is_dir():
                r = entry.resolve()
                if not recursive or entry.is_symlink() or any(r == e or e in r.parents for e in excluded):
                    continue
                service = cloud_service(r)
                if service and not privacy.include_cloud:
                    skipped.append((entry, f"synced to {service}: left alone (--include-cloud to allow)"))
                    continue
                yield from walk(entry)
            elif entry.is_file() and not entry.is_symlink():
                yield entry

    candidates: list[tuple[Path, str | None, os.stat_result]] = []
    for path in walk(source):
        ext = path.suffix.lower()
        if path.name.lower() in IGNORED_NAMES:
            continue
        if ext in IN_PROGRESS:
            skipped.append((path, "still downloading"))
            continue
        cat = category(path)
        if cat and cat.lower() in skip_types:
            skipped.append((path, f"{cat} left alone by you (not opened)"))
            continue
        try:
            st = path.stat()
        except OSError as exc:
            skipped.append((path, f"can't read ({exc.strerror or exc})"))
            continue
        if now - st.st_mtime < SETTLE_SECONDS:
            skipped.append((path, "modified in the last 30s (in use?)"))
            continue
        candidates.append((path, cat, st))

    av_hits = safety.antivirus([p for p, _, _ in candidates]) if use_av else {}
    for path, cat, st in candidates:
        ext = path.suffix.lower()
        findings = safety.inspect(path)
        if path in av_hits:
            findings.append(av_hits[path])
        if findings:  # set aside before parsing it any further
            date = datetime.fromtimestamp(st.st_mtime)
            items.append(Item(path, REVIEW, Meta(), date, "file timestamp", st.st_size,
                              findings=findings, origin=safety.origin(path), sha256=_digest(path) or ""))
            continue
        if cat is None:
            skipped.append((path, f"unknown type '{ext or 'no extension'}'"))
            continue
        meta = extract(path)
        date, why = best_date(path, meta)
        it = Item(path, cat, meta, date, why, st.st_size, sensitive=sensitive_reason(path, meta))
        if cat == "Pictures":
            it.kind = picture_kind(path, meta)
        items.append(it)
    return items, skipped


# --- grouping ----------------------------------------------------------------

def _author_keys(items: list[Item]) -> set[str]:
    # Whole names only: excluding single words would let a creator like
    # "English Department" knock out the real topic "English 3".
    return {grouping._key(grouping.tokenize(it.meta.author)) for it in items if it.meta.author}


def _signals(it: Item, allow_sequence: bool = False) -> dict[str, grouping.Signal]:
    m = it.meta
    return grouping.signals_for(
        name=it.path.stem,
        title=[t for t in (m.title, m.subject, *m.keywords) if t],
        headers=m.headers,
        lines=m.lines,
        allow_sequence=allow_sequence,
    )


def assign_groups(items: list[Item], min_files: int) -> dict[str, int]:
    docs = [it for it in items if it.category in TEXTUAL]
    exclude = _author_keys(docs)
    topics = grouping.discover([_signals(d) for d in docs], min_files=min_files, exclude=exclude)
    for i, name in topics.assignment.items():
        docs[i].topic = name
        docs[i].why.append(f"topic {topics.evidence[i]}")

    by_topic: dict[str, list[Item]] = defaultdict(list)
    for d in docs:
        if d.topic:
            by_topic[d.topic].append(d)

    for topic, members in by_topic.items():
        if all(d.category == "Spreadsheets" for d in members):
            for d in members:
                d.group_root = "Spreadsheets"
        leftovers = []
        for d in members:
            t = grouping.doc_type(name=d.path.stem, title=[d.meta.title, d.meta.subject], lines=d.meta.lines)
            if t is None and d.category == "Presentations":
                t = "Presentations"
            if t:
                d.subgroup = t
                d.why.append(f"type '{t}'")
            else:
                leftovers.append(d)
        # second pass: recurring phrases among what's left ("Unit 2", "Chapter 5")
        if len(leftovers) >= min_files:
            topic_key = {grouping._key(grouping.tokenize(topic))}
            sub = grouping.discover([_signals(d, allow_sequence=True) for d in leftovers],
                                    min_files=min_files, max_share=1.0, exclude=exclude | topic_key)
            for i, name in sub.assignment.items():
                leftovers[i].subgroup = name
                leftovers[i].why.append(f"subgroup {sub.evidence[i]}")

    # Tabular files with the same columns are the same kind of export (bank CSVs, gradebooks...).
    tables: dict[frozenset[str], list[Item]] = defaultdict(list)
    for d in docs:
        if not d.topic and len(d.meta.columns) >= 2:
            tables[frozenset(c.lower() for c in d.meta.columns)].append(d)
    for cols, members in tables.items():
        if len(members) < min_files:
            continue
        name = grouping.common_prefix_name([m.path.stem for m in members])
        if not name:
            name = "Data - " + ", ".join(members[0].meta.columns[:3])
        for m in members:
            m.topic, m.group_root = name, "Spreadsheets"
            m.why.append(f"same {len(cols)} columns as {len(members) - 1} other file(s)")

    return {t: len(m) for t, m in by_topic.items()} | {
        m[0].topic: len(m) for m in tables.values() if len(m) >= min_files and m[0].topic}


# --- duplicates --------------------------------------------------------------

def _digest(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:  # locked / unreadable: never call it a duplicate
        return None
    return h.hexdigest()


def find_duplicates(items: list[Item]) -> set[int]:
    """Indexes of items that are byte-identical copies of an earlier item."""
    by_size: dict[int, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        if it.size:
            by_size[it.size].append(i)
    dupes: set[int] = set()
    for idxs in by_size.values():
        if len(idxs) < 2:
            continue
        seen: dict[str, int] = {}
        # keep the copy with the shortest name ("report.pdf" over "report (1).pdf")
        for i in sorted(idxs, key=lambda i: (len(items[i].path.name), items[i].path.name)):
            d = _digest(items[i].path)
            if d is None:
                continue
            if d in seen:
                dupes.add(i)
                items[i].why.append(f"identical to {items[seen[d]].path.name}")
            else:
                seen[d] = i
    return dupes


# --- destinations ------------------------------------------------------------

def destination(it: Item, roots: dict[str, Path], date_prefix: bool, events: set[str] = frozenset()) -> Path:
    ym, y = it.date.strftime("%Y-%m"), it.date.strftime("%Y")
    name = it.path.name
    if it.category == REVIEW:
        return roots[REVIEW] / name
    if it.topic:
        folder = roots[it.group_root] / safe_name(it.topic)
        if it.subgroup:
            folder /= safe_name(it.subgroup)
        if date_prefix and not _LEADING_DATE.match(name):
            name = f"{it.date:%Y-%m-%d} {name}"
        return folder / name
    if it.category == "Pictures":
        folder = roots["Pictures"] / it.kind / y / ym
        day = f"{it.date:%Y-%m-%d}"
        return (folder / day if it.kind == "Photos" and day in events else folder) / name
    return roots[it.category] / y / ym / name


def _free(target: Path, taken: set[Path]) -> Path:
    if target not in taken and not target.exists():
        return target
    n = 1
    while True:
        cand = target.with_name(f"{target.stem} ({n}){target.suffix}")
        if cand not in taken and not cand.exists():
            return cand
        n += 1


def photo_events(items: list[Item], min_photos: int) -> set[str]:
    """Days with a burst of photos (a trip, a party) get their own folder."""
    per_day: dict[str, int] = defaultdict(int)
    for it in items:
        if it.kind == "Photos":
            per_day[f"{it.date:%Y-%m-%d}"] += 1
    return {d for d, n in per_day.items() if n >= min_photos}


def override_folder(folder: str, roots: dict[str, Path]) -> Path | None:
    """'Documents/Taxes/2024' -> <Documents root>/Taxes/2024. Only known roots; names sanitized."""
    parts = [p for p in re.split(r"[\\/]+", folder.strip()) if p.strip()]
    if not parts or parts[0] not in roots or parts[0] in (REVIEW, "Duplicates") or len(parts) > 5:
        return None
    out = roots[parts[0]]
    for p in parts[1:]:
        out /= safe_name(p)
    return out


def build_plan(source: Path, *, dest: Path | None = None, recursive: bool = False,
               min_files: int = 2, date_prefix: bool = True, privacy: Privacy | None = None,
               use_av: bool = False, event_min: int = 5,
               overrides: dict[str, str] | None = None) -> Plan:
    """``overrides`` maps a source file path to a folder like 'Documents/Taxes' (from an assistant)."""
    source = source.resolve()
    roots = category_roots(source, dest)
    items, skipped = scan(source, recursive=recursive, privacy=privacy, use_av=use_av,
                          exclude=list(roots.values()) + ([dest] if dest else []))
    plan = Plan()
    plan.review = [it for it in items if it.category == REVIEW]
    dupes = find_duplicates([it if it.category != REVIEW else _NoHash(it) for it in items])
    unique = [it for i, it in enumerate(items) if i not in dupes]
    plan.topics = assign_groups(unique, min_files)
    events = photo_events(unique, event_min)
    chosen = {str(Path(k).resolve()): v for k, v in (overrides or {}).items()}

    def resolve_override(path: Path) -> Path | None:
        folder = chosen.get(str(path))
        if folder is None:
            return None
        target = override_folder(folder, roots)
        if target is None:
            skipped.append((path, f"suggested folder '{folder}' isn't allowed; left as planned"))
        return target

    taken: set[Path] = set()

    def add(src: Path, target: Path, why: str, item: Item | None, leftover: bool) -> None:
        if target.exists() and target.is_file() and target.stat().st_size == src.stat().st_size \
                and _digest(target) is not None and _digest(target) == _digest(src):
            target = roots["Duplicates"] / src.name
            why += f"; already exists at {target.parent}"
        target = _free(target, taken)
        taken.add(target)
        plan.moves.append(Move(src, target, why, item, leftover))

    for i, it in enumerate(items):
        override = resolve_override(it.path) if it.category != REVIEW else None
        if it.category == REVIEW:
            target = destination(it, roots, date_prefix)
            it.why.append("possibly unsafe: " + "; ".join(f.reason for f in it.findings))
        elif i in dupes:
            target = roots["Duplicates"] / it.path.name
        elif override is not None:
            target = override / it.path.name
            it.why.append("placed by assistant (approved plan)")
        else:
            target = destination(it, roots, date_prefix, events)
        if target == it.path:  # already where it belongs (recursive re-runs)
            continue
        leftover = override is None and i not in dupes and it.category != REVIEW and not it.topic and (
            it.category in TEXTUAL | {"Ebooks"} or it.kind == "Images")
        why = "; ".join([f"date {it.date:%Y-%m-%d} from {it.date_why}", *it.why])
        add(it.path, target, why, it, leftover)

    # Unknown types the assistant found a home for.
    for path, reason in skipped:
        if reason.startswith("unknown type") and (target := resolve_override(path)) is not None:
            add(path, target / path.name, "placed by assistant (approved plan)", None, False)
    placed = {m.src for m in plan.moves}
    plan.skipped = [(p, r) for p, r in skipped if not (p in placed and r.startswith("unknown type"))]

    for m in plan.moves:
        service = cloud_service(m.dst)
        if service and not cloud_service(m.src):
            plan.cloud_targets[service] = plan.cloud_targets.get(service, 0) + 1
    return plan


class _NoHash:
    """Keeps flagged files out of duplicate detection (they're set aside regardless)."""

    def __init__(self, it: Item):
        self.path, self.size, self.why = it.path, 0, []
