from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
from conftest import make_jpeg, touch

from file_organizer.apply import apply
from file_organizer.cli import main, plan_json
from file_organizer.planner import CloudSourceError, Privacy, build_plan, cloud_service
from file_organizer.safety import HIGH, inspect


def _dst(plan, name: str, out: Path) -> str | None:
    return next((m.dst.relative_to(out).as_posix() for m in plan.moves if m.src.name == name), None)


# --- malicious-file heuristics -------------------------------------------------

def test_disguised_executable(tmp_path: Path):
    f = touch(tmp_path / "invoice.pdf", b"MZ\x90\x00" + b"\x00" * 100)
    assert any(x.level == HIGH and "Windows program" in x.reason for x in inspect(f))


def test_double_extension_and_rtlo(tmp_path: Path):
    assert inspect(touch(tmp_path / "photo.jpg.exe", b"MZ"))[0].level == HIGH
    assert any("right-to-left" in x.reason for x in inspect(touch(tmp_path / "inv‮exe.pdf", b"%PDF-1.7")))


def test_macro_document(tmp_path: Path):
    f = tmp_path / "report.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", "<w/>")
        z.writestr("word/vbaProject.bin", b"\x00")
    assert any("macros" in x.reason for x in inspect(f))


def test_remote_template_injection(tmp_path: Path):
    f = tmp_path / "cv.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", "<w/>")
        z.writestr("word/_rels/settings.xml.rels",
                   '<Relationship Type=".../attachedTemplate" Target="http://evil/t.dotm" TargetMode="External"/>')
    assert any(x.level == HIGH and "template" in x.reason for x in inspect(f))


def test_pdf_auto_javascript(tmp_path: Path):
    f = touch(tmp_path / "form.pdf", b"%PDF-1.4\n1 0 obj << /OpenAction 2 0 R >>\n2 0 obj << /S /JavaScript /JS (app.alert(1)) >>")
    assert [x.reason for x in inspect(f)] == ["PDF runs JavaScript automatically when opened"]


def test_encrypted_archive_with_program(tmp_path: Path):
    f = tmp_path / "docs.zip"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("scan.exe", b"x")
    data = bytearray(f.read_bytes())  # zipfile can't write encrypted entries; set the flag bit by hand
    data[6] |= 0x1                                   # local file header
    data[data.index(b"PK\x01\x02") + 8] |= 0x1     # central directory
    f.write_bytes(bytes(data))
    assert any(x.level == HIGH and "password-protected" in x.reason for x in inspect(f))


def test_clean_files_are_not_flagged(downloads: Path):
    flagged = [p.name for p in downloads.iterdir() if p.is_file() and inspect(p)]
    assert flagged == []  # incl. setup.exe: a normal installer is not "suspicious"


def test_flagged_files_set_aside_and_defanged(downloads: Path, tmp_path: Path):
    bad = touch(downloads / "homework.docx.js", b"var x = 1;")
    os.chmod(bad, 0o755)
    out = tmp_path / "o"
    plan = build_plan(downloads, dest=out)
    assert _dst(plan, "homework.docx.js", out) == "Needs Review/homework.docx.js"
    assert [it.path.name for it in plan.review] == ["homework.docx.js"]
    apply(plan, log_dir=tmp_path / "logs")
    if os.name != "nt":
        assert not (out / "Needs Review" / "homework.docx.js").stat().st_mode & stat.S_IXUSR
    entry = next(m for m in plan_json(plan)["moves"] if m["src"].endswith("homework.docx.js"))
    assert len(entry["sha256"]) == 64 and entry["unsafe"]


# --- privacy -------------------------------------------------------------------

def test_exclude_and_skip_type(downloads: Path, tmp_path: Path):
    out = tmp_path / "o"
    plan = build_plan(downloads, dest=out, privacy=Privacy(exclude=["lease*"], skip_types={"pictures"}))
    moved = {m.src.name for m in plan.moves}
    assert "lease.pdf" not in moved
    assert not any(n.endswith((".jpg", ".png", ".gif")) for n in moved)
    reasons = {p.name: r for p, r in plan.skipped}
    assert "not opened" in reasons["lease.pdf"] and "not opened" in reasons["funny.gif"]


def test_cloud_source_refused_and_subfolders_skipped(tmp_path: Path):
    box = tmp_path / "Dropbox"
    box.mkdir()
    with pytest.raises(CloudSourceError):
        build_plan(box, dest=tmp_path / "o")

    src = tmp_path / "Downloads"
    (src / "OneDrive - School").mkdir(parents=True)
    touch(src / "OneDrive - School" / "notes.txt")
    plan = build_plan(src, dest=tmp_path / "o", recursive=True)
    assert not plan.moves and "synced to OneDrive" in plan.skipped[0][1]


def test_moving_into_cloud_needs_consent(downloads: Path, tmp_path: Path, capsys):
    cloud = tmp_path / "Google Drive"
    assert cloud_service(cloud / "Documents") == "Google Drive"
    assert main([str(downloads), "--dest", str(cloud), "--apply"]) == 1
    assert "uploaded to the cloud" in capsys.readouterr().out
    assert not cloud.exists()


def test_sensitive_files_get_no_metadata_in_json(downloads: Path, tmp_path: Path):
    from conftest import make_docx

    make_docx(downloads / "2024 taxes.docx", title="Form 1040", body=["SSN 000-00-0000"])
    data = plan_json(build_plan(downloads, dest=tmp_path / "o"), detail="metadata")
    tax = next(m for m in data["moves"] if m["src"].endswith("2024 taxes.docx"))
    assert tax["sensitive"] and "meta" not in tax
    gatsby = next(m for m in data["moves"] if m["src"].endswith("Gatsby final.docx"))
    assert "English 3" in json.dumps(gatsby["meta"])


# --- assistant overrides, photo events -------------------------------------------

def test_overrides_are_validated(downloads: Path, tmp_path: Path):
    out = tmp_path / "o"
    touch(downloads / "evil.pdf.exe", b"MZ")
    overrides = {
        str(downloads / "mystery.xyz"): "Documents/Mystery Stuff",
        str(downloads / "lease.pdf"): "../../etc",            # not a known root -> ignored
        str(downloads / "evil.pdf.exe"): "Documents/Safe",    # flagged files can't be overridden
    }
    plan = build_plan(downloads, dest=out, overrides=overrides)
    assert _dst(plan, "mystery.xyz", out) == "Documents/Mystery Stuff/mystery.xyz"
    assert _dst(plan, "lease.pdf", out) == "Documents/2023/2023-03/lease.pdf"
    assert _dst(plan, "evil.pdf.exe", out) == "Needs Review/evil.pdf.exe"


def test_photo_burst_gets_a_day_folder(tmp_path: Path):
    src = tmp_path / "in"
    src.mkdir()
    for i in range(5):
        make_jpeg(src / f"IMG_{i}.jpg", taken=f"2024:07:04 1{i}:00:00", camera="Pixel 8")
    make_jpeg(src / "IMG_x.jpg", taken="2024:07:09 10:00:00", camera="Pixel 8")
    out = tmp_path / "o"
    plan = build_plan(src, dest=out)
    assert _dst(plan, "IMG_0.jpg", out) == "Pictures/Photos/2024/2024-07/2024-07-04/IMG_0.jpg"
    assert _dst(plan, "IMG_x.jpg", out) == "Pictures/Photos/2024/2024-07/IMG_x.jpg"


def test_assistant_round_trip_through_cli(downloads: Path, tmp_path: Path, monkeypatch, capsys):
    """The skill's flow: preview -> JSON -> overrides -> apply -> undo, all via the CLI."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    out, plan_file, ov = tmp_path / "o", tmp_path / "plan.json", tmp_path / "ov.json"
    assert main([str(downloads), "--dest", str(out), "--json", str(plan_file)]) == 0
    plan = json.loads(plan_file.read_text())
    unknown = [s["path"] for s in plan["skipped"] if s["why"].startswith("unknown type")]
    ov.write_text(json.dumps({unknown[0]: "Code/Misc"}))
    assert main([str(downloads), "--dest", str(out), "--overrides", str(ov), "--apply"]) == 0
    assert (out / "Code" / "Misc" / "mystery.xyz").exists()
    assert main(["--undo"]) == 0
    assert (downloads / "mystery.xyz").exists() and not out.exists()


# --- review regressions: no false alarms on everyday files ------------------------

def test_benign_lookalikes_are_not_flagged(tmp_path: Path):
    form = touch(tmp_path / "f1040.pdf", b"%PDF-1.7\n<< /AcroForm << /JS (calc()) >> /JavaScript 3 0 R >>")
    einvoice = touch(tmp_path / "invoice.pdf", b"%PDF-1.7\n<< /EmbeddedFile 5 0 R /F (factur-x.xml) >>")
    webp_as_jpg = touch(tmp_path / "cat.jpg", b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    installer = touch(tmp_path / "NVIDIA-Linux.run", b"#!/bin/sh\n")
    code = touch(tmp_path / "utils.js", b"export const x = 1;")
    for f in (form, einvoice, webp_as_jpg, installer, code):
        assert inspect(f) == [], f.name


def test_pdf_with_embedded_program(tmp_path: Path):
    f = touch(tmp_path / "doc.pdf", b"%PDF-1.7\n<< /EmbeddedFile 5 0 R /F (update.exe) >>")
    assert inspect(f)[0].level == HIGH


def test_withheld_files_are_counts_not_names(downloads: Path, tmp_path: Path):
    plan = build_plan(downloads, dest=tmp_path / "o", privacy=Privacy(exclude=["lease*"], skip_types={"Pictures"}))
    data = plan_json(plan)
    text = json.dumps(data)
    assert "lease.pdf" not in text and "funny.gif" not in text
    assert sum(data["withheld"].values()) >= 2


def test_rejected_override_is_reported(downloads: Path, tmp_path: Path):
    plan = build_plan(downloads, dest=tmp_path / "o", overrides={str(downloads / "lease.pdf"): "docs/Taxes"})
    assert any("isn't allowed" in why for p, why in plan.skipped if p.name == "lease.pdf")


def test_malformed_overrides_rejected(downloads: Path, tmp_path: Path):
    bad = tmp_path / "ov.json"
    bad.write_text('["not", "a", "mapping"]')
    assert main([str(downloads), "--dest", str(tmp_path / "o"), "--overrides", str(bad)]) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_undo_restores_execute_permission(downloads: Path, tmp_path: Path):
    from file_organizer.apply import undo

    bad = touch(downloads / "notes.pdf.sh", b"#!/bin/sh\n")
    os.chmod(bad, 0o755)
    log, _, _ = apply(build_plan(downloads, dest=tmp_path / "o"), log_dir=tmp_path / "logs")
    undo(log)
    assert bad.stat().st_mode & 0o777 == 0o755


def test_archives_and_disk_images(tmp_path: Path):
    webapp = tmp_path / "app.zip"
    with zipfile.ZipFile(webapp, "w") as z:
        z.writestr("index.js", "x")
        z.writestr("setup.exe", "MZ")
    lure = tmp_path / "Invoice.zip"
    with zipfile.ZipFile(lure, "w") as z:
        z.writestr("Invoice_0423.pdf.lnk", "x")
    distro = tmp_path / "ubuntu.iso"
    with distro.open("wb") as fh:
        fh.truncate(200_000_000)  # sparse: big like a real OS image
    small_iso = touch(tmp_path / "Payment.iso", b"\x00" * 1000)
    assert inspect(webapp) == [] and inspect(distro) == []
    assert inspect(lure) and inspect(small_iso)


def test_antivirus_fails_closed(downloads: Path, tmp_path: Path, monkeypatch, capsys):
    from file_organizer import safety

    monkeypatch.setattr("file_organizer.cli.antivirus_available", lambda: "ClamAV")  # installed...
    monkeypatch.setattr(safety, "antivirus", lambda paths: ({}, list(paths)))  # ...but it errored
    before = sorted(p.name for p in downloads.iterdir())
    assert main([str(downloads), "--dest", str(tmp_path / "o"), "--av", "--apply"]) == 1
    assert "didn't complete" in capsys.readouterr().out
    assert sorted(p.name for p in downloads.iterdir()) == before
