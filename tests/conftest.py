from __future__ import annotations

import os
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

OLD = datetime(2025, 1, 15, 9, 0).timestamp()  # past the "still downloading" window

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _paras(lines: list[str]) -> str:
    return "".join(f"<w:p><w:r><w:t>{escape(l)}</w:t></w:r></w:p>" for l in lines)


def make_docx(path: Path, *, body: list[str], header: list[str] = (), title: str = "",
              author: str = "", created: str = "") -> Path:
    core = (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
        f"<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>"
        + (f"<dcterms:created>{created}</dcterms:created>" if created else "")
        + "</cp:coreProperties>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("docProps/core.xml", core)
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{_paras(body)}</w:body></w:document>")
        if header:
            z.writestr("word/header1.xml", f"<w:hdr {W}>{_paras(list(header))}</w:hdr>")
    os.utime(path, (OLD, OLD))
    return path


def touch(path: Path, data: bytes = b"x") -> Path:
    path.write_bytes(data)
    os.utime(path, (OLD, OLD))
    return path


def make_jpeg(path: Path, *, taken: str | None = None, camera: str = "") -> Path:
    from PIL import Image

    img = Image.new("RGB", (8, 8), (200, 30, 30))
    exif = Image.Exif()
    if camera:
        exif[271] = camera
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    img.save(path, exif=exif)
    os.utime(path, (OLD, OLD))
    return path


def make_pdf(path: Path, *, title: str = "", created: str = "") -> Path:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_metadata({"/Title": title, "/CreationDate": created})
    with path.open("wb") as fh:
        w.write(fh)
    os.utime(path, (OLD, OLD))
    return path


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    d = tmp_path / "Downloads"
    d.mkdir()
    me = "Anthony Talavera"
    mla = lambda course, date, title: [me, "Mr. Smith", course, date, title]  # noqa: E731

    make_docx(d / "Gatsby final.docx", author=me, created="2024-10-12T15:00:00Z",
              body=mla("English 3", "12 October 2024", "The American Dream in The Great Gatsby"),
              header=[f"{me} English 3"])
    make_docx(d / "Persuasive essay.docx", author=me, created="2024-12-01T15:00:00Z",
              body=mla("ENGLISH III", "1 December 2024", "Why School Should Start Later"),
              header=["ENGLISH III - Period 4"])
    make_docx(d / "Vocab list unit 2.docx", author=me, created="2024-09-20T15:00:00Z",
              title="English 3 Vocabulary", body=["Glossary", "allusion - a reference"])
    make_docx(d / "ch5.docx", author=me, created="2024-11-01T15:00:00Z",
              body=["Chapter 5 notes", "Nick narrates the reunion"], header=["English 3"])
    make_docx(d / "AP Bio Lab 1.docx", author=me, created="2024-09-10T15:00:00Z",
              title="AP Biology Lab 1: Enzymes", body=["AP Biology", "Lab Report", "Enzyme rates"])
    make_docx(d / "cells.docx", author=me, created="2024-09-15T15:00:00Z",
              body=["AP Biology", "Cell structure notes"], header=["AP Biology - Unit 1"])

    make_pdf(d / "lease.pdf", title="Apartment Lease", created="D:20230303120000")

    for n, month in enumerate(("jan", "feb"), 1):
        touch(d / f"chase_statement_{month}.csv", f"Date,Description,Amount,Balance\n2025-0{n}-01,x,{n},2\n".encode())

    make_jpeg(d / "IMG_20230704_101500.jpg", taken="2023:07:04 10:15:00", camera="Apple iPhone 15")
    (d / "IMG_20230704_101500 (1).jpg").write_bytes((d / "IMG_20230704_101500.jpg").read_bytes())
    os.utime(d / "IMG_20230704_101500 (1).jpg", (OLD, OLD))
    make_jpeg(d / "Screenshot 2024-02-03 at 10.11.12.png")
    touch(d / "funny.gif", b"GIF89a")
    touch(d / "setup.exe", b"MZ")
    touch(d / "mystery.xyz")
    touch(d / "movie.mp4.crdownload")
    return d
