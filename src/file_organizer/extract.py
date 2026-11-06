"""Read metadata and a little text from files, without opening any app.

Every extractor is best-effort: a corrupt or unexpected file yields an empty
``Meta`` instead of an exception, so one bad download never stops a run.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from defusedxml import ElementTree as ET  # downloads are untrusted: block XXE / entity bombs

try:  # optional at import time so the tool still runs with only the stdlib
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:  # HEIC/HEIF support if the extra is installed
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

MAX_LINES = 12          # body lines kept per document
MAX_TEXT_BYTES = 64_000  # cap on plain-text reads
MAX_XML_BYTES = 8_000_000  # cap on any one XML part inside an Office/ODF zip (zip-bomb guard)


def _member(z: zipfile.ZipFile, name: str) -> bytes:
    """Read a zip member, refusing to inflate more than MAX_XML_BYTES.

    The declared size can be forged, so the limit is enforced on bytes actually read.
    """
    with z.open(name) as fh:
        data = fh.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise ValueError(f"{name} too large")
    return data


@dataclass
class Meta:
    title: str = ""
    subject: str = ""
    keywords: list[str] = field(default_factory=list)
    author: str = ""
    created: datetime | None = None
    modified: datetime | None = None
    taken: datetime | None = None        # EXIF capture time (photos)
    content_date: datetime | None = None  # latest date written inside the data (CSV rows)
    camera: str = ""                     # EXIF make + model
    software: str = ""                   # producing app (screenshots, editors)
    headers: list[str] = field(default_factory=list)  # header/footer lines
    lines: list[str] = field(default_factory=list)    # first body lines
    columns: list[str] = field(default_factory=list)  # tabular header row
    source: str = ""                     # which extractor produced this


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().replace("Z", "+00:00")
    # LibreOffice writes nanoseconds; Python 3.10 only parses 3 or 6 fractional digits
    value = re.sub(r"\.(\d+)", lambda m: "." + m[1][:6].ljust(6, "0"), value, count=1)
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


# Field codes and their computed results (page numbers, page counts) aren't content:
# an MLA header "Talavera 1" must read as "Talavera", or it looks like a course name.
_FIELD_TAGS = {"fldSimple", "instrText", "page-number", "page-count"}


def _para_text(para) -> str:
    parts: list[str] = []
    in_result = False  # between a complex field's "separate" and "end" markers

    def walk(el) -> None:
        nonlocal in_result
        tag = _local(el.tag)
        if tag in _FIELD_TAGS:
            return
        if tag == "fldChar":
            kind = next((v for k, v in el.attrib.items() if k.endswith("fldCharType")), "")
            in_result = kind == "separate" or (in_result and kind != "end")
        elif el.text and not in_result:
            parts.append(el.text)
        for child in el:
            walk(child)
            if child.tail and not in_result:
                parts.append(child.tail)

    walk(para)
    return _clean("".join(parts))


def _paragraphs(xml_bytes: bytes) -> list[str]:
    """Text of each paragraph element (w:p, a:p, text:p, text:h) in order."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    texts = (_para_text(el) for el in root.iter() if _local(el.tag) in ("p", "h"))
    return [t for t in texts if t]


# --- Office Open XML (docx / xlsx / pptx) ---------------------------------

def _ooxml(path: Path) -> Meta:
    meta = Meta(source="ooxml")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "docProps/core.xml" in names:
            root = ET.fromstring(_member(z, "docProps/core.xml"))
            for el in root:
                tag, text = _local(el.tag), _clean(el.text or "")
                if tag == "title":
                    meta.title = text
                elif tag == "subject":
                    meta.subject = text
                elif tag == "creator":
                    meta.author = text
                elif tag == "keywords":
                    meta.keywords = [k.strip() for k in re.split(r"[;,]", text) if k.strip()]
                elif tag == "created":
                    meta.created = _parse_iso(text)
                elif tag == "modified":
                    meta.modified = _parse_iso(text)
        if "docProps/app.xml" in names:
            root = ET.fromstring(_member(z, "docProps/app.xml"))
            for el in root:
                if _local(el.tag) == "Application":
                    meta.software = _clean(el.text or "")

        if "word/document.xml" in names:
            meta.lines = _paragraphs(_member(z, "word/document.xml"))[:MAX_LINES]
            for n in sorted(names):
                if re.fullmatch(r"word/(header|footer)\d*\.xml", n):
                    meta.headers += _paragraphs(_member(z, n))
        elif any(n.startswith("ppt/slides/slide") for n in names):
            slides = sorted(
                (n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()),
            )
            for n in slides[:3]:
                meta.lines += _paragraphs(_member(z, n))
            meta.lines = meta.lines[:MAX_LINES]
        elif "xl/workbook.xml" in names:
            root = ET.fromstring(_member(z, "xl/workbook.xml"))
            sheets = [el.get("name", "") for el in root.iter() if _local(el.tag) == "sheet"]
            meta.lines = [s for s in sheets if s and not re.fullmatch(r"Sheet\d*", s)]
            meta.columns = _xlsx_first_row(z, names)
    return meta


def _xlsx_first_row(z: zipfile.ZipFile, names: set[str]) -> list[str]:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(_member(z, "xl/sharedStrings.xml"))
        shared = [_clean("".join(si.itertext())) for si in root if _local(si.tag) == "si"]
    if "xl/worksheets/sheet1.xml" not in names:
        return []
    root = ET.fromstring(_member(z, "xl/worksheets/sheet1.xml"))
    for row in root.iter():
        if _local(row.tag) != "row":
            continue
        cells = []
        for c in row:
            v = next((x.text for x in c.iter() if _local(x.tag) in ("v", "t")), None)
            if v is None:
                continue
            if c.get("t") == "s" and v.isdigit() and int(v) < len(shared):
                v = shared[int(v)]
            cells.append(_clean(v))
        return [c for c in cells if c]
    return []


# --- OpenDocument (odt / ods / odp) ----------------------------------------

def _odf(path: Path) -> Meta:
    meta = Meta(source="odf")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "meta.xml" in names:
            root = ET.fromstring(_member(z, "meta.xml"))
            for el in root.iter():
                tag, text = _local(el.tag), _clean(el.text or "")
                if tag == "title":
                    meta.title = text
                elif tag == "subject":
                    meta.subject = text
                elif tag in ("initial-creator", "creator") and not meta.author:
                    meta.author = text
                elif tag == "keyword":
                    meta.keywords.append(text)
                elif tag == "creation-date":
                    meta.created = _parse_iso(text)
                elif tag == "date":
                    meta.modified = _parse_iso(text)
                elif tag == "generator":
                    meta.software = text
        if "content.xml" in names:
            meta.lines = _paragraphs(_member(z, "content.xml"))[:MAX_LINES]
        if "styles.xml" in names:  # page headers/footers live in master styles
            meta.headers = _paragraphs(_member(z, "styles.xml"))
    return meta


# --- PDF -------------------------------------------------------------------

def _pdf(path: Path) -> Meta:
    meta = Meta(source="pdf")
    if PdfReader is None:
        return meta
    reader = PdfReader(str(path))
    info = reader.metadata or {}
    meta.title = _clean(str(info.get("/Title", "") or ""))
    meta.subject = _clean(str(info.get("/Subject", "") or ""))
    meta.author = _clean(str(info.get("/Author", "") or ""))
    meta.software = _clean(str(info.get("/Producer", "") or info.get("/Creator", "") or ""))
    kw = str(info.get("/Keywords", "") or "")
    meta.keywords = [k.strip() for k in re.split(r"[;,]", kw) if k.strip()]
    for attr, key in (("created", "creation_date"), ("modified", "modification_date")):
        try:
            dt = getattr(reader.metadata, key, None) if reader.metadata else None
        except Exception:  # malformed PDF date strings
            dt = None
        if dt is not None:
            setattr(meta, attr, dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt)

    # A line that repeats at the top/bottom of several pages is a running header.
    edges: Counter[str] = Counter()
    for i, page in enumerate(reader.pages[:4]):
        try:
            lines = [_clean(l) for l in (page.extract_text() or "").splitlines() if _clean(l)]
        except Exception:
            continue
        if i == 0:
            meta.lines = lines[:MAX_LINES]
        for line in {*lines[:2], *lines[-2:]}:
            if not re.fullmatch(r"(page )?\d+( of \d+)?", line, re.I):
                edges[line] += 1
    meta.headers = [l for l, n in edges.items() if n >= 2]
    return meta


# --- Images ----------------------------------------------------------------

_EXIF_DT = "%Y:%m:%d %H:%M:%S"


def _image(path: Path) -> Meta:
    meta = Meta(source="image")
    if Image is None:
        return meta
    with Image.open(path) as img:
        exif = img.getexif()
        sub = exif.get_ifd(0x8769)  # Exif sub-IFD holds the capture time
        for raw in (sub.get(36867), sub.get(36868), exif.get(306)):
            if raw:
                try:
                    meta.taken = datetime.strptime(str(raw).strip("\x00 ")[:19], _EXIF_DT)
                    break
                except ValueError:
                    continue
        meta.camera = _clean(f"{exif.get(271, '')} {exif.get(272, '')}")
        meta.software = _clean(str(exif.get(305, "") or img.info.get("Software", "")))
        desc = img.info.get("Description") or img.info.get("Comment") or ""
        if isinstance(desc, bytes):
            desc = desc.decode("utf-8", "ignore")
        if desc:
            meta.lines = [_clean(desc)]
    return meta


# --- Plain text / CSV --------------------------------------------------------

def _read_text(path: Path) -> str:
    with path.open("rb") as fh:
        data = fh.read(MAX_TEXT_BYTES)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def _text(path: Path) -> Meta:
    meta = Meta(source="text")
    lines = [_clean(l) for l in _read_text(path).splitlines()]
    meta.lines = [l.lstrip("#").strip() for l in lines if l][:MAX_LINES]
    return meta


def _csv(path: Path) -> Meta:
    meta = Meta(source="csv")
    text = _read_text(path)
    first = text.splitlines()[0] if text else ""
    delim = "\t" if path.suffix.lower() == ".tsv" or first.count("\t") > first.count(",") else ","
    row = next(csv.reader(io.StringIO(first), delimiter=delim), [])
    meta.columns = [_clean(c) for c in row if _clean(c)]
    # Exports (bank statements, gradebooks) carry their real period in the rows.
    found = []
    for line in text.splitlines()[1:200]:
        for m in _ROW_DATE.finditer(line):
            y, mo, d = (m["y"], m["m"], m["d"]) if m["y"] else (m["y2"], m["m2"], m["d2"])
            y = int(y) + (2000 if len(y) == 2 else 0)
            try:
                found.append(datetime(y, int(mo), int(d)))
            except ValueError:
                pass
    meta.content_date = max(found) if found else None
    return meta


# 2024-05-12 or US-style 05/12/2024
_ROW_DATE = re.compile(r"(?<!\d)(?:(?P<y>(?:19|20)\d\d)-(?P<m>[01]?\d)-(?P<d>[0-3]?\d)"
                       r"|(?P<m2>[01]?\d)/(?P<d2>[0-3]?\d)/(?P<y2>(?:19|20)?\d\d))(?!\d)")


EXTRACTORS = {
    **dict.fromkeys((".docx", ".docm", ".dotx", ".xlsx", ".xlsm", ".pptx"), _ooxml),
    **dict.fromkeys((".odt", ".ods", ".odp"), _odf),
    ".pdf": _pdf,
    **dict.fromkeys(
        (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".avif"),
        _image,
    ),
    **dict.fromkeys((".txt", ".md", ".markdown", ".rtf", ".tex"), _text),
    **dict.fromkeys((".csv", ".tsv"), _csv),
}


def extract(path: Path) -> Meta:
    fn = EXTRACTORS.get(path.suffix.lower())
    if fn is None:
        return Meta()
    try:
        return fn(path)
    except Exception:  # corrupt, encrypted, truncated download, etc.
        return Meta(source="error")
