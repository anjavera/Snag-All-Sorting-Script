"""Turn a folder of files into a list of planned moves (nothing touches disk here)."""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import grouping
from .classify import IGNORED_NAMES, IN_PROGRESS, TEXTUAL, best_date, category, picture_kind
from .extract import Meta, extract

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
    why: list[str] = field(default_factory=list)


@dataclass
class Move:
    src: Path
    dst: Path
    why: str


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    topics: dict[str, int] = field(default_factory=dict)


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


def user_dirs() -> dict[str, Path]:
    """The OS's standard per-user folders (Windows, macOS, Linux/XDG)."""
    home = Path.home()
    dirs = {
        "DOWNLOAD": home / "Downloads",
        "DOCUMENTS": home / "Documents",
        "PICTURES": home / "Pictures",
        "VIDEOS": home / ("Movies" if sys.platform == "darwin" else "Videos"),
        "MUSIC": home / "Music",
    }
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        dirs.update({k: v for k, v in _xdg_dirs().items() if k in dirs})
    return dirs


def category_roots(source: Path, dest: Path | None) -> dict[str, Path]:
    from .classify import CATEGORIES

    if dest is not None:
        return {c: dest / c for c in [*CATEGORIES, "Duplicates"]}
    u = user_dirs()
    roots = {c: source / c for c in [*CATEGORIES, "Duplicates"]}  # misc types tidy in place
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

def scan(source: Path, *, recursive: bool, exclude: list[Path]) -> tuple[list[Item], list[tuple[Path, str]]]:
    items: list[Item] = []
    skipped: list[tuple[Path, str]] = []
    now = time.time()
    source = source.resolve()
    # Don't descend into output folders -- unless the source *is* one (organize ~/Documents -r).
    excluded = [e for e in (p.resolve() for p in exclude) if e != source and e not in source.parents]

    def walk(folder: Path):
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            skipped.append((folder, f"can't read folder ({exc.strerror or exc})"))
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                r = entry.resolve()
                if recursive and not entry.is_symlink() and not any(r == e or e in r.parents for e in excluded):
                    yield from walk(entry)
            elif entry.is_file() and not entry.is_symlink():
                yield entry

    for path in walk(source):
        ext = path.suffix.lower()
        if path.name.lower() in IGNORED_NAMES:
            continue
        if ext in IN_PROGRESS:
            skipped.append((path, "still downloading"))
            continue
        cat = category(path)
        if cat is None:
            skipped.append((path, f"unknown type '{ext or 'no extension'}'"))
            continue
        try:
            st = path.stat()
        except OSError as exc:
            skipped.append((path, f"can't read ({exc.strerror or exc})"))
            continue
        if now - st.st_mtime < SETTLE_SECONDS:
            skipped.append((path, "modified in the last 30s (in use?)"))
            continue
        meta = extract(path)
        date, why = best_date(path, meta)
        items.append(Item(path, cat, meta, date, why, st.st_size))
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

def destination(it: Item, roots: dict[str, Path], date_prefix: bool) -> Path:
    ym, y = it.date.strftime("%Y-%m"), it.date.strftime("%Y")
    name = it.path.name
    if it.topic:
        folder = roots[it.group_root] / safe_name(it.topic)
        if it.subgroup:
            folder /= safe_name(it.subgroup)
        if date_prefix and not _LEADING_DATE.match(name):
            name = f"{it.date:%Y-%m-%d} {name}"
        return folder / name
    if it.category == "Pictures":
        return roots["Pictures"] / picture_kind(it.path, it.meta) / y / ym / name
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


def build_plan(source: Path, *, dest: Path | None = None, recursive: bool = False,
               min_files: int = 2, date_prefix: bool = True) -> Plan:
    roots = category_roots(source, dest)
    items, skipped = scan(source, recursive=recursive, exclude=list(roots.values()) + ([dest] if dest else []))
    plan = Plan(skipped=skipped)
    dupes = find_duplicates(items)
    unique = [it for i, it in enumerate(items) if i not in dupes]
    plan.topics = assign_groups(unique, min_files)

    taken: set[Path] = set()
    for i, it in enumerate(items):
        if i in dupes:
            target = roots["Duplicates"] / it.path.name
        else:
            target = destination(it, roots, date_prefix)
        if target == it.path:  # already where it belongs (recursive re-runs)
            continue
        if target.exists() and target.is_file() and target.stat().st_size == it.size \
                and _digest(target) is not None and _digest(target) == _digest(it.path):
            target = roots["Duplicates"] / it.path.name
            it.why.append(f"already exists at {target.parent}")
        target = _free(target, taken)
        taken.add(target)
        why = "; ".join([f"date {it.date:%Y-%m-%d} from {it.date_why}", *it.why])
        plan.moves.append(Move(it.path, target, why))
    return plan
