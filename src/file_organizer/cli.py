"""Command line: preview by default, --apply to move, --undo to put everything back."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from . import __version__
from .apply import apply, latest_log, undo
from .planner import CloudSourceError, Move, Plan, Privacy, build_plan, default_source
from .safety import antivirus_available


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
    if plan.review:
        print(f"\n!! {len(plan.review)} file(s) look possibly unsafe -> set aside in 'Needs Review' (not opened):")
        for it in plan.review:
            print(f"    {it.path.name}")
            for f in it.findings:
                print(f"        [{f.level}] {f.reason}")
            if it.origin:
                print(f"        downloaded from: {it.origin}")
        print("    Don't open these until checked. To check without uploading the file, look its")
        print("    SHA-256 up on virustotal.com (organize --json shows it), or run with --av.")
    if plan.av_unscanned:
        print(f"\n!! The antivirus scan (--av) didn't complete for {len(plan.av_unscanned)} file(s):")
        for p in plan.av_unscanned[:10]:
            print(f"    {p.name}")
        print("    Nothing will be moved while that's unresolved. Fix the scanner, or re-run")
        print("    without --av to rely on the built-in checks only.")
    if plan.cloud_targets:
        where = ", ".join(f"{n} file(s) into {svc}" for svc, n in plan.cloud_targets.items())
        print(f"\nPrivacy: this would move {where}; they'd be uploaded to the cloud.")
        print("    Use --dest to keep them local, or --allow-cloud to accept.")
    listed, withheld = _split_withheld(plan.skipped)
    if listed or withheld:
        print(f"\nLeft in place ({len(listed) + sum(withheld.values())}):")
        for path, why in listed:
            print(f"    {path.name}  - {why}")
        for why, n in withheld.items():
            print(f"    {n} item(s): {why}")


def _move_json(m: Move, detail: str) -> dict:
    out: dict = {"src": str(m.src), "dst": str(m.dst), "why": m.why, "leftover": m.leftover}
    it = m.item
    if it is None:
        return out
    out.update(category=it.category, date=f"{it.date:%Y-%m-%d}")
    if it.kind:
        out["kind"] = it.kind
    if it.sensitive:
        out["sensitive"] = it.sensitive  # assistant must not open these, and gets no contents
    if it.findings:
        out["unsafe"] = [{"level": f.level, "reason": f.reason} for f in it.findings]
        out["sha256"] = it.sha256
        out["origin"] = it.origin
    elif detail == "metadata" and not it.sensitive:
        mm = it.meta
        meta = {"title": mm.title, "subject": mm.subject, "headers": mm.headers[:3],
                "first_lines": mm.lines[:3], "columns": mm.columns[:8], "camera": mm.camera}
        out["meta"] = {k: v for k, v in meta.items() if v}
    return out


_PRIVATE = ("excluded by you", "left alone by you", "synced to ")


def _split_withheld(skipped: list[tuple[Path, str]]) -> tuple[list[tuple[Path, str]], dict[str, int]]:
    """Files the user put off-limits are reported as counts, never by name."""
    listed, withheld = [], {}
    for p, why in skipped:
        if any(k in why for k in _PRIVATE):
            key = "cloud-synced folders" if "synced to" in why else why.split(" (")[0]
            withheld[key] = withheld.get(key, 0) + 1
        else:
            listed.append((p, why))
    return listed, withheld


def plan_json(plan: Plan, detail: str = "names") -> dict:
    from .planner import sensitive_reason

    listed, withheld = _split_withheld(plan.skipped)
    return {
        "moves": [_move_json(m, detail) for m in plan.moves],
        "skipped": [{"path": str(p), "why": w, **({"sensitive": r} if (r := sensitive_reason(p)) else {})}
                    for p, w in listed],
        "withheld": withheld,  # counts only: the user asked for these to be left alone
        "patterns": plan.topics,
        "cloud_targets": plan.cloud_targets,
        "detail": detail,
    }


CREDIT = "Created by Opus 5.5 and Anjavera."


def _confirm(n: int) -> bool:
    """Ask before moving when a person is at the keyboard (scripts/assistants use --apply)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        answer = input(f"\nMove these {n} file(s) now? Type y and press Enter (anything else cancels): ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        prog="organize",
        description="Snag-All Sorting Script: a file organizer. Sorts a folder by date, type, and "
                    "what's inside the files. Shows a preview first; nothing moves until you say yes.",
        epilog=CREDIT,
    )
    ap.add_argument("source", nargs="?", type=Path, help="folder to organize (default: your Downloads)")
    ap.add_argument("--home", action="store_true",
                    help="organize loose files in your home folder (add -r to include its subfolders; "
                         "code projects and app folders are always left as they are)")
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
    privacy = ap.add_argument_group("privacy")
    privacy.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                         help="never open or move matching files/folders (glob, repeatable), e.g. 'Taxes*'")
    privacy.add_argument("--skip-type", action="append", default=[], metavar="CATEGORY",
                         help="leave a whole category alone, e.g. Pictures (repeatable)")
    privacy.add_argument("--include-cloud", action="store_true",
                         help="also organize inside OneDrive / Google Drive / Dropbox / iCloud folders")
    privacy.add_argument("--allow-cloud", action="store_true",
                         help="allow moving files INTO a cloud-synced folder (they get uploaded)")
    privacy.add_argument("--json-detail", choices=["names", "metadata"], default="names",
                         help="what --json includes: names/dates only (default) or also titles, headers "
                              "and first lines (never for sensitive files)")
    ap.add_argument("--av", action="store_true",
                    help="also scan with a locally installed antivirus (Defender / ClamAV); nothing is uploaded")
    ap.add_argument("--event-min", type=int, default=5, metavar="N",
                    help="photos taken on one day before that day gets its own folder (default 5)")
    ap.add_argument("--overrides", type=Path, metavar="FILE",
                    help='JSON {"<file path>": "Documents/Some Folder"} of approved placements '
                         "(used by the assistant workflow; still preview-first, undoable)")
    ap.add_argument("--undo", nargs="?", const="latest", metavar="LOG",
                    help="put back the files moved by the last run (or by LOG)")
    ap.add_argument("--version", action="version", version=f"Snag-All Sorting Script {__version__}. {CREDIT}")
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

    if args.home and args.source:
        print("Use either --home or a folder, not both.", file=sys.stderr)
        return 1
    source = (Path.home() if args.home else args.source or default_source()).expanduser().resolve()
    if not source.is_dir():
        print(f"Folder not found: {source}", file=sys.stderr)
        return 1
    dest = args.dest.expanduser().resolve() if args.dest else None

    if args.av and not antivirus_available():
        print("No local antivirus found (Defender on Windows, or install ClamAV); continuing without --av.")
        args.av = False
    overrides = None
    if args.overrides:
        try:
            overrides = json.loads(args.overrides.read_text())
        except (OSError, ValueError) as exc:
            print(f"Can't read {args.overrides}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(overrides, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in overrides.items()):
            print('--overrides must be a JSON object: {"<file path>": "Documents/Folder", ...}', file=sys.stderr)
            return 1
    try:
        plan = build_plan(source, dest=dest, recursive=args.recursive,
                          min_files=max(2, args.min_group), date_prefix=not args.no_date_prefix,
                          privacy=Privacy(args.exclude, set(args.skip_type), args.include_cloud),
                          use_av=args.av, event_min=max(2, args.event_min), overrides=overrides)
    except CloudSourceError as exc:
        print(f"{source} is synced to {exc}. Organizing it would reorganize it on every device "
              "and in the cloud. Re-run with --include-cloud if that's what you want.", file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(plan_json(plan, args.json_detail), indent=2))
    if not plan.moves:
        print(f"Nothing to organize in {source}.")
        print_plan(plan, args.explain)
        return 0
    print_plan(plan, args.explain)

    if not args.apply and not _confirm(len(plan.moves)):
        print(f"\nNothing has moved yet. {len(plan.moves)} file(s) are ready to sort; "
              "run again and answer y (or add --apply) to move them.")
        return 0
    if plan.av_unscanned:
        print("\nNot moving anything: the antivirus scan you asked for didn't complete (see above).",
              file=sys.stderr)
        return 1
    if plan.cloud_targets and not args.allow_cloud:
        print("\nNot moving anything: some destinations sync to the cloud (see above). "
              "Use --dest or --allow-cloud.", file=sys.stderr)
        return 1
    log, moved, errors = apply(plan)
    print(f"\nDone: moved {moved} file(s). Changed your mind? Use the Undo launcher, or run:  organize --undo")
    for e in errors:
        print(f"  ! {e}")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
