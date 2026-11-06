"""Static checks for files that may be malicious.

Nothing here opens, runs, or uploads a file: it reads bytes and names only.
This is a tripwire for common tricks (disguised executables, macro documents,
PDF auto-actions, password-protected archives), not an antivirus. Flagged
files are set aside in "Needs Review" instead of being filed with your things.
Use ``--av`` to also ask a locally installed scanner (Microsoft Defender, ClamAV).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

HIGH, MEDIUM = "high", "medium"

# Run code when double-clicked, with no installer UI in between.
RUNS_CODE = {".exe", ".scr", ".pif", ".com", ".cpl", ".msi", ".msix", ".bat", ".cmd", ".ps1", ".vbs",
             ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".lnk", ".jar", ".reg", ".appimage",
             ".app", ".command", ".sh", ".dll", ".url", ".scf", ".iqy", ".msc"}
# Types with no everyday use except running code on double-click: classic attachment malware.
# (.js/.ps1/.bat/.sh/.command are also ordinary code files, so they're only flagged when
# disguised, e.g. "invoice.pdf.js".)
SCRIPTY = RUNS_CODE - {".exe", ".msi", ".msix", ".appimage", ".app", ".sh", ".dll",
                       ".js", ".ps1", ".bat", ".cmd", ".command"}
# Extensions that legitimately hold native programs (installers, drivers, libraries).
NATIVE_OK = RUNS_CODE | {".run", ".bin", ".so", ".dylib", ".sys", ".efi", ".ocx", ".drv", ".ko",
                         ".py", ".rb", ".pl", ".sh", ""}
# "Container" files that bypass Windows' downloaded-file warnings for what's inside.
CONTAINERS = {".iso", ".img", ".vhd", ".vhdx", ".one"}
LOOKS_HARMLESS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".jpg",
                  ".jpeg", ".png", ".gif", ".mp3", ".mp4", ".mov", ".csv", ".zip", ".odt", ".heic"}

MAGIC = {
    b"MZ": "Windows program",
    b"\x7fELF": "Linux program",
    b"\xcf\xfa\xed\xfe": "macOS program",
    b"\xca\xfe\xba\xbe": "macOS program",
    b"#!": "script",
}
BIDI = re.compile("[\u202a-\u202e\u2066-\u2069\u200e\u200f]")  # right-to-left override tricks
SCAN_BYTES = 4_000_000
# Malware ISOs/IMGs are a few MB wrapped around a shortcut or program; OS images are GBs.
SMALL_CONTAINER = 100_000_000


@dataclass
class Finding:
    level: str
    reason: str


def _head(path: Path, n: int = 8) -> bytes:
    with path.open("rb") as fh:
        return fh.read(n)


def check_name(path: Path) -> list[Finding]:
    out = []
    name, ext = path.name, path.suffix.lower()
    if BIDI.search(name):
        out.append(Finding(HIGH, "name contains hidden right-to-left characters (disguises the real extension)"))
    inner = Path(path.stem).suffix.lower()
    if inner in LOOKS_HARMLESS and ext in RUNS_CODE:
        out.append(Finding(HIGH, f"double extension: looks like '{inner}' but is a '{ext}' that runs code"))
    if re.search(r"\s{5,}\.\w+$", name):
        out.append(Finding(MEDIUM, "long run of spaces before the extension (hides it in narrow windows)"))
    if ext in SCRIPTY:
        out.append(Finding(MEDIUM, f"'{ext}' files run code when opened"))
    if ext == ".one" or (ext in CONTAINERS and _size(path) < SMALL_CONTAINER):
        out.append(Finding(MEDIUM, f"small '{ext}' file: a common way to slip programs past download warnings"))
    return out


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def check_content(path: Path) -> list[Finding]:
    ext = path.suffix.lower()
    out: list[Finding] = []
    head = _head(path)
    kind = next((label for sig, label in MAGIC.items() if head.startswith(sig)), None)
    # Only a *program* wearing another extension matters. Other mismatches (a WebP saved
    # as .jpg, a .docx renamed .doc, text "exported to Excel") are everyday sloppiness.
    if kind and ext not in NATIVE_OK:
        out.append(Finding(MEDIUM if kind == "script" else HIGH, f"named '{ext}' but is actually a {kind}"))

    if zipfile.is_zipfile(path):
        out += _check_zip(path, ext)
    elif head.startswith(b"\xd0\xcf\x11\xe0"):
        out += _check_ole(path)
    if head.startswith(b"%PDF") or ext == ".pdf":
        out += _check_pdf(path)
    if ext in {".svg", ".html", ".htm", ".xhtml"}:
        with path.open("rb") as fh:
            blob = fh.read(SCAN_BYTES).lower()
        if ext == ".svg" and (b"<script" in blob or re.search(rb"\son\w+\s*=", blob)):
            out.append(Finding(MEDIUM, "image (SVG) contains script"))
        if b"type=\"password\"" in blob or b"type='password'" in blob:
            out.append(Finding(MEDIUM, "saved web page with a password form (common phishing attachment)"))
    return out


def _check_zip(path: Path, ext: str) -> list[Finding]:
    out = []
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = {i.filename for i in infos}
        if any(n.lower().endswith("vbaproject.bin") for n in names) or ext in {".docm", ".xlsm", ".pptm"}:
            out.append(Finding(MEDIUM, "Office document contains macros"))
        for rels in (n for n in names if n.endswith(".rels") and "settings" in n):
            data = z.open(rels).read(200_000)
            if b"attachedTemplate" in data and b'TargetMode="External"' in data:
                out.append(Finding(HIGH, "document loads a template from the internet when opened"))
        if ext in {".zip", ".7z", ".rar"} or not any(n.startswith(("word/", "xl/", "ppt/")) for n in names):
            encrypted = any(i.flag_bits & 0x1 for i in infos)
            runnable = [n for n in names if Path(n).suffix.lower() in RUNS_CODE | CONTAINERS]
            # Programs and .js inside a zip are normal (apps, web projects). What isn't: shortcut/
            # script-host types, disk images, and disguised names like "invoice.pdf.exe".
            risky = [n for n in names if Path(n).suffix.lower() in SCRIPTY | CONTAINERS
                     or any(f.level == HIGH for f in check_name(Path(n)))]
            if encrypted and runnable:
                out.append(Finding(HIGH, "password-protected archive containing programs/scripts"))
            elif encrypted:
                out.append(Finding(MEDIUM, "password-protected archive (hides contents from scanners)"))
            if risky:
                sample = ", ".join(sorted(risky)[:3])
                out.append(Finding(MEDIUM, f"archive contains disguised or script-host files: {sample}"))
    return out


def _check_ole(path: Path) -> list[Finding]:
    try:
        import olefile
    except ImportError:  # pragma: no cover
        return []
    with olefile.OleFileIO(str(path)) as ole:
        if ole.exists("Macros") or ole.exists("_VBA_PROJECT_CUR") or ole.exists("VBA"):
            return [Finding(MEDIUM, "Office document contains macros")]
    return []


def _check_pdf(path: Path) -> list[Finding]:
    # Fillable forms (tax, school) use JavaScript for calculations and e-invoices embed XML,
    # so those alone are normal. Flag what attacks rely on: launching programs, scripts that
    # run on open, and embedded programs.
    with path.open("rb") as fh:
        blob = fh.read(SCAN_BYTES)
    out = []
    if b"/Launch" in blob:
        out.append(Finding(HIGH, "PDF tries to launch a program"))
    has_js = b"/JavaScript" in blob or re.search(rb"/JS\s*[(<\[]|/JS \d", blob)
    if has_js and re.search(rb"/OpenAction|/AA\b", blob):
        out.append(Finding(MEDIUM, "PDF runs JavaScript automatically when opened"))
    if b"/EmbeddedFile" in blob:
        names = re.findall(rb"/U?F\s*\(([^)]{1,200})\)", blob)
        runnable = [n.decode("latin-1") for n in names
                    if Path(n.decode("latin-1")).suffix.lower() in RUNS_CODE | CONTAINERS]
        if runnable:
            out.append(Finding(HIGH, f"PDF has a program embedded inside: {runnable[0]}"))
    return out


def origin(path: Path) -> str:
    """Where the browser said the file came from (Mark-of-the-Web / quarantine / xdg origin)."""
    try:
        if os.name == "nt":
            ads = Path(f"{path}:Zone.Identifier")
            text = ads.read_text(errors="ignore") if ads.exists() else ""
            m = re.search(r"HostUrl=(\S+)", text)
            return m[1] if m else ""
        if hasattr(os, "getxattr"):  # Linux: Chrome/Firefox set this
            return os.getxattr(path, "user.xdg.origin.url").decode(errors="ignore")
        if sys.platform == "darwin" and shutil.which("mdls"):  # the xattr itself is a binary plist
            r = subprocess.run(["mdls", "-raw", "-name", "kMDItemWhereFroms", str(path)],
                               capture_output=True, text=True, timeout=5)
            m = re.search(r"https?://[^\s\"']+", r.stdout)
            return m[0] if m else ""
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def antivirus(paths: list[Path]) -> dict[Path, Finding]:
    """Ask a locally installed scanner about many files at once. Never uploads anything."""
    hits: dict[Path, Finding] = {}
    defender = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"
    try:
        if os.name == "nt" and defender.exists():
            for p in paths:  # MpCmdRun takes one file per call, but its engine is already loaded
                r = subprocess.run([str(defender), "-Scan", "-ScanType", "3", "-File", str(p),
                                    "-DisableRemediation"], capture_output=True, text=True, timeout=300)
                if r.returncode == 2:
                    hits[p] = Finding(HIGH, "Microsoft Defender detected a threat")
        elif shutil.which("clamscan") and paths:
            # one run: clamscan reloads its whole signature database on every start
            r = subprocess.run(["clamscan", "--no-summary", "--infected", *map(str, paths)],
                               capture_output=True, text=True, timeout=3600)
            by_name = {str(p): p for p in paths}
            for line in r.stdout.splitlines():
                name, _, sig = line.rpartition(": ")
                if sig.endswith("FOUND") and name in by_name:
                    hits[by_name[name]] = Finding(HIGH, f"ClamAV detected {sig[:-5].strip() or 'a threat'}")
    except (OSError, subprocess.SubprocessError):
        pass
    return hits


def antivirus_available() -> str:
    if os.name == "nt":
        return "Microsoft Defender"
    return "ClamAV" if shutil.which("clamscan") else ""


def inspect(path: Path) -> list[Finding]:
    findings = check_name(path)
    try:
        findings += check_content(path)
    except Exception:  # unreadable/corrupt: the content checks simply don't apply
        pass
    return findings


def defang(path: Path) -> int | None:
    """Remove execute permission (POSIX) so a flagged file can't be run by accident.

    Returns the original permission bits so undo can restore them."""
    if os.name == "nt":
        return None
    try:
        mode = path.stat().st_mode & 0o7777
        if mode & 0o111:
            path.chmod(mode & ~0o111)
            return mode
    except OSError:
        pass
    return None
