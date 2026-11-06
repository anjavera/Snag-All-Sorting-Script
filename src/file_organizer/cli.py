"""Command line: preview by default, --apply to move, --undo to put everything back."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from . import __version__
from .apply import apply, latest_log, undo
from .planner import Plan, build_plan, default_source


def _short(path: Path) -> str:
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def print_plan(plan: Plan, explain: bool) -> None:
    by_dir: dict[Path, list] = defaultdict(list)
    for mv in plan.moves:
        by_dir[mv.dst.parent].append(mv)
    for folder in sorted(by_dir, key=lambda p: str(p).lower()):
        moves = sorted(by_dir[folder], key=lambda m: m.dst.name.lower())
        print(f"\n{_short(folder)}/  ({len(moves)})")
        for mv in moves:
            print(f"    {mv.dst.name}")
            if explain:
                print(f"        <- {mv.src.name}: {mv.why}")
    if plan.topics:
        print("\nPatterns found:")
        for name, n in sorted(plan.topics.items(), key=lambda kv: -kv[1]):
            print(f"    {name}  ({n} files)")
    if plan.skipped:
        print(f"\nLeft in place ({len(plan.skipped)}):")
        for path, why in plan.skipped:
            print(f"    {path.name}  - {why}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        prog="organize",
        description="Organize a folder by date, file type, metadata and recurring patterns. "
                    "Shows a preview unless --apply is given.",
    )
    ap.add_argument("source", nargs="?", type=Path, help="folder to organize (default: your Downloads)")
    ap.add_argument("--dest", type=Path, help="put everything under this folder instead of your "
                                             "Documents/Pictures/Videos/Music folders")
    ap.add_argument("--apply", action="store_true", help="actually move the files")
    ap.add_argument("-r", "--recursive", action="store_true", help="include files in subfolders")
    ap.add_argument("--min-group", type=int, default=2, metavar="N",
                    help="files needed before a recurring pattern gets its own folder (default 2)")
    ap.add_argument("--no-date-prefix", action="store_true",
                    help="don't prefix grouped files with YYYY-MM-DD")
    ap.add_argument("--explain", action="store_true", help="show why each file goes where it goes")
    ap.add_argument("--json", type=Path, metavar="FILE", help="also write the plan as JSON")
    ap.add_argument("--undo", nargs="?", const="latest", metavar="LOG",
                    help="put back the files moved by the last run (or by LOG)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    if args.undo:
        log = latest_log() if args.undo == "latest" else Path(args.undo)
        if not log or not log.exists():
            print("Nothing to undo.")
            return 1
        restored, errors = undo(log)
        print(f"Restored {restored} file(s).")
        for e in errors:
            print(f"  ! {e}")
        return 0 if not errors else 2

    source = (args.source or default_source()).expanduser().resolve()
    if not source.is_dir():
        print(f"Folder not found: {source}", file=sys.stderr)
        return 1
    dest = args.dest.expanduser().resolve() if args.dest else None

    plan = build_plan(source, dest=dest, recursive=args.recursive,
                      min_files=max(2, args.min_group), date_prefix=not args.no_date_prefix)
    if not plan.moves:
        print(f"Nothing to organize in {source}.")
        print_plan(plan, args.explain)
        return 0
    print_plan(plan, args.explain)

    if args.json:
        args.json.write_text(json.dumps({
            "moves": [{"src": str(m.src), "dst": str(m.dst), "why": m.why} for m in plan.moves],
            "skipped": [{"path": str(p), "why": w} for p, w in plan.skipped],
            "patterns": plan.topics,
        }, indent=2))

    if not args.apply:
        print(f"\nPreview only: {len(plan.moves)} file(s) would move. Re-run with --apply to do it.")
        return 0
    log, moved, errors = apply(plan)
    print(f"\nMoved {moved} file(s). Undo with:  organize --undo")
    for e in errors:
        print(f"  ! {e}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
