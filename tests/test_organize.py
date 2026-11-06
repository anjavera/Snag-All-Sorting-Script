from __future__ import annotations

from datetime import datetime
from pathlib import Path

from file_organizer import grouping
from file_organizer.apply import apply, undo
from file_organizer.classify import date_from_name
from file_organizer.cli import main
from file_organizer.planner import build_plan


def _rel(plan, out: Path) -> dict[str, str]:
    return {m.src.name: m.dst.relative_to(out).as_posix() for m in plan.moves}


def test_full_layout(downloads: Path, tmp_path: Path):
    out = tmp_path / "Organized"
    got = _rel(build_plan(downloads, dest=out), out)

    # recurring "English 3" (incl. "ENGLISH III" header) becomes a topic, split by doc type
    assert got["Gatsby final.docx"] == "Documents/English 3/2024-10-12 Gatsby final.docx"
    assert got["Persuasive essay.docx"] == "Documents/English 3/Essays/2024-12-01 Persuasive essay.docx"
    assert got["Vocab list unit 2.docx"] == "Documents/English 3/Glossaries/2024-09-20 Vocab list unit 2.docx"
    assert got["ch5.docx"] == "Documents/English 3/Notes/2024-11-01 ch5.docx"
    assert got["AP Bio Lab 1.docx"] == "Documents/AP Biology/Lab Reports/2024-09-10 AP Bio Lab 1.docx"
    assert got["cells.docx"] == "Documents/AP Biology/Notes/2024-09-15 cells.docx"

    # ungrouped docs are chronological by embedded creation date, not download date
    assert got["lease.pdf"] == "Documents/2023/2023-03/lease.pdf"

    # same-column CSV exports group together under Spreadsheets
    assert got["chase_statement_feb.csv"] == "Spreadsheets/Chase/Statements/2025-02-01 chase_statement_feb.csv"

    # pictures: kind from extension + metadata, then year/month from EXIF / filename
    assert got["IMG_20230704_101500.jpg"] == "Pictures/Photos/2023/2023-07/IMG_20230704_101500.jpg"
    assert got["Screenshot 2024-02-03 at 10.11.12.png"].startswith("Pictures/Screenshots/2024/2024-02/")
    assert got["funny.gif"] == "Pictures/GIFs/2025/2025-01/funny.gif"
    assert got["IMG_20230704_101500 (1).jpg"] == "Duplicates/IMG_20230704_101500 (1).jpg"
    assert got["setup.exe"].startswith("Installers/2025/")
    assert "mystery.xyz" not in got and "movie.mp4.crdownload" not in got


def test_author_name_is_not_a_topic(downloads: Path, tmp_path: Path):
    plan = build_plan(downloads, dest=tmp_path / "o")
    assert not any("Talavera" in t for t in plan.topics)


def test_preview_does_not_move(downloads: Path, tmp_path: Path, capsys):
    before = sorted(p.name for p in downloads.iterdir())
    assert main([str(downloads), "--dest", str(tmp_path / "o")]) == 0
    assert sorted(p.name for p in downloads.iterdir()) == before
    assert "Nothing has moved yet" in capsys.readouterr().out


def test_apply_then_undo_round_trip(downloads: Path, tmp_path: Path):
    before = sorted(p.name for p in downloads.iterdir())
    out = tmp_path / "o"
    plan = build_plan(downloads, dest=out)
    log, moved, errors = apply(plan, log_dir=tmp_path / "logs")
    assert moved == len(plan.moves) and not errors
    assert (out / "Documents" / "English 3" / "Notes" / "2024-11-01 ch5.docx").exists()

    restored, errors = undo(log)
    assert restored == moved and not errors
    assert sorted(p.name for p in downloads.iterdir()) == before
    assert not out.exists()  # created folders are cleaned up


def test_never_overwrites(downloads: Path, tmp_path: Path):
    out = tmp_path / "o"
    target = out / "Documents" / "2023" / "2023-03" / "lease.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"a different lease")
    got = _rel(build_plan(downloads, dest=out), out)
    assert got["lease.pdf"] == "Documents/2023/2023-03/lease (1).pdf"


def test_dates_in_filenames():
    assert date_from_name("IMG_20240512_143000") == datetime(2024, 5, 12, 14, 30)
    assert date_from_name("Screenshot 2024-05-12 at 14.30.05") == datetime(2024, 5, 12, 14, 30, 5)
    assert date_from_name("IMG-20240512-WA0001") == datetime(2024, 5, 12)
    assert date_from_name("invoice 4521") is None
    assert date_from_name("20991231") is None  # future dates are noise


def test_doc_types():
    assert grouping.doc_type(name="Hamlet rough draft essay") == "Essays"
    assert grouping.doc_type(name="ch5", lines=["Chapter 5 notes"]) == "Notes"
    assert grouping.doc_type(name="unit2", title=["Key terms"]) == "Glossaries"
    assert grouping.doc_type(name="photo") is None


def test_sequence_subgroups_for_leftovers():
    sigs = [grouping.signals_for(name=n, allow_sequence=True) for n in ("unit 2 a", "unit 2 b", "x")]
    g = grouping.discover(sigs)
    assert g.assignment == {0: "Unit 2", 1: "Unit 2"}


def test_page_number_field_is_not_part_of_header(tmp_path: Path):
    import zipfile

    from file_organizer.extract import extract

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    hdr = (f'<w:hdr {w}><w:p><w:r><w:t xml:space="preserve">Talavera </w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>PAGE</w:instrText></w:r>'
           '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
           '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:hdr>')
    p = tmp_path / "a.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f"<w:document {w}><w:body/></w:document>")
        z.writestr("word/header1.xml", hdr)
    assert extract(p).headers == ["Talavera"]


def test_odf_nanosecond_dates():
    from file_organizer.extract import _parse_iso

    assert _parse_iso("2024-10-12T15:00:00.123456789") == datetime(2024, 10, 12, 15, 0, 0, 123456)


def test_second_undo_does_not_reuse_undone_log(downloads: Path, tmp_path: Path):
    from file_organizer.apply import latest_log

    logs = tmp_path / "logs"
    log, _, _ = apply(build_plan(downloads, dest=tmp_path / "o"), log_dir=logs)
    undo(log)
    assert latest_log(logs) is None


def test_recursive_inside_an_output_root(tmp_path: Path):
    from conftest import make_pdf

    out = tmp_path / "o"
    (out / "Documents" / "inbox").mkdir(parents=True)
    make_pdf(out / "Documents" / "inbox" / "lease.pdf", created="D:20230303120000")
    settled = out / "Documents" / "2023" / "2023-03"
    settled.mkdir(parents=True)
    make_pdf(settled / "deed.pdf", created="D:20230305120000")

    got = _rel(build_plan(out / "Documents", dest=out, recursive=True), out)
    assert got == {"lease.pdf": "Documents/2023/2023-03/lease.pdf"}  # deed.pdf already in place


def test_screenshot_names():
    from file_organizer.classify import picture_kind
    from file_organizer.extract import Meta

    assert picture_kind(Path("Capture.PNG"), Meta()) == "Screenshots"
    assert picture_kind(Path("snippet_logo.png"), Meta()) == "Images"
    assert picture_kind(Path("Capture the Flag poster.png"), Meta()) == "Images"


def test_zip_bomb_part_is_not_inflated(tmp_path: Path, monkeypatch):
    import zipfile

    from file_organizer import extract as ex

    monkeypatch.setattr(ex, "MAX_XML_BYTES", 1000)
    p = tmp_path / "bomb.docx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<a>" + "A" * 50_000 + "</a>")
    assert ex.extract(p).source == "error"  # skipped, not read into memory


def test_topic_names_cannot_escape_destination():
    from file_organizer.planner import safe_name

    assert safe_name("..") == "Untitled"
    assert "/" not in safe_name("../../etc") and "\\\\" not in safe_name("..\\\\Windows")


def test_legacy_word_doc_metadata_and_text():
    from file_organizer.extract import extract

    m = extract(Path(__file__).parent / "fixtures" / "vocab.doc")  # made by LibreOffice, Word 97 format
    assert m.source == "ole" and m.lines[:2] == ["English 3", "Vocabulary list"]


def test_asks_before_moving_when_run_by_a_person(downloads: Path, tmp_path: Path, monkeypatch):
    import io

    from file_organizer import cli

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(cli.sys, "stdout", Tty())
    monkeypatch.setattr(cli.sys, "stdin", Tty("n\n"))
    assert main([str(downloads), "--dest", str(tmp_path / "o")]) == 0
    assert not (tmp_path / "o").exists()  # "n" -> nothing moved

    monkeypatch.setattr(cli.sys, "stdin", Tty("y\n"))
    assert main([str(downloads), "--dest", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "Documents" / "English 3").is_dir()
