"""Carry out a plan, and undo it later from the log it leaves behind."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import safety
from .planner import Plan


def state_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "snag-all"


def apply(plan: Plan, log_dir: Path | None = None) -> tuple[Path, int, list[str]]:
    log_dir = log_dir or state_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"undo-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    done: list[dict[str, str]] = []
    created: list[str] = []
    errors: list[str] = []

    def save() -> None:  # written after every move so a crash still leaves a usable log
        log.write_text(json.dumps({"moves": done, "created_dirs": created}, indent=1))

    for mv in plan.moves:
        try:
            missing = [p for p in [mv.dst.parent, *mv.dst.parent.parents] if not p.exists()]
            mv.dst.parent.mkdir(parents=True, exist_ok=True)
            created += [str(p) for p in reversed(missing)]
            if mv.dst.exists():  # appeared since planning; never overwrite
                raise FileExistsError(mv.dst)
            shutil.move(str(mv.src), str(mv.dst))  # keeps timestamps; works across drives
            entry = {"src": str(mv.src), "dst": str(mv.dst)}
            if mv.item is not None and mv.item.findings:
                mode = safety.defang(mv.dst)
                if mode is not None:
                    entry["mode"] = mode  # restored on undo
            done.append(entry)
            save()
        except OSError as exc:
            errors.append(f"{mv.src.name}: {exc}")
    save()
    return log, len(done), errors


def latest_log(log_dir: Path | None = None) -> Path | None:
    logs = sorted(p for p in (log_dir or state_dir()).glob("undo-*.json") if not p.name.endswith(".undone.json"))
    return logs[-1] if logs else None


def undo(log: Path) -> tuple[int, list[str]]:
    data = json.loads(log.read_text())
    restored, errors, remaining = 0, [], []
    for mv in reversed(data["moves"]):
        src, dst = Path(mv["src"]), Path(mv["dst"])
        if not dst.exists():
            errors.append(f"missing, can't restore: {dst}")
            continue
        if src.exists():
            errors.append(f"original location is occupied: {src}")
            remaining.insert(0, mv)  # keep it so a later --undo can retry
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        if "mode" in mv:
            src.chmod(mv["mode"])
        restored += 1
    for d in sorted(data.get("created_dirs", []), key=len, reverse=True):
        try:
            Path(d).rmdir()  # only succeeds if empty
        except OSError:
            pass
    if remaining:
        log.write_text(json.dumps({"moves": remaining, "created_dirs": data.get("created_dirs", [])}, indent=1))
    else:
        log.rename(log.with_suffix(".undone.json"))
    return restored, errors
