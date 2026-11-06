"""Discover recurring topics across files and split them into document types.

The idea: a phrase that shows up in the header, title, opening lines or name of
several different files ("English 3", "Invoice", "Lab Safety") is a signal
that those files belong together. Each file contributes weighted *signals*;
a phrase that at least ``min_files`` files share becomes a folder. Inside a
topic, files are split by document type (Essays, Glossaries, Notes, ...) using
keyword rules, and leftovers are split again by any further recurring phrase
("Unit 2", "Chapter 5").
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

# Weight of a phrase depending on where it was found.
W_HEADER, W_TITLE, W_LINE, W_NAME, W_BODY = 3.0, 2.5, 2.0, 1.5, 1.0
COURSE_BONUS = 2.0

STOP = set("""
a an the and or of for to in on at by with from into about as is are was were be been this that these
those it its my your our their his her i me we you he she they them not no yes do does did can will
just than then so if but per vs via etc re fw fwd
""".split())
# Words that describe *what kind* of file it is, or are filler, not *what it's about*.
NOISE = set("""
copy final draft untitled document doc docs file files new old version ver v rev revised scan scanned
img image photo pic picture screenshot download downloaded edit edited updated update latest
th st nd rd name date due period pd class student teacher mr mrs ms dr prof professor page pages
jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july
august september october november december monday tuesday wednesday thursday friday saturday sunday
""".split())
SEQUENCE_WORDS = {"unit", "chapter", "ch", "week", "module", "lesson", "part", "section", "topic",
                  "quarter", "semester", "term", "volume", "vol", "book", "act", "session"}
COURSE_PREFIX = {"ap", "ib", "honors", "hon", "intro", "advanced", "adv"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}

# Document types, most specific first. Matched against name/title first, then opening lines.
DOC_TYPES: list[tuple[str, re.Pattern[str]]] = [(name, re.compile(rx, re.I)) for name, rx in [
    ("Syllabus", r"\b(syllabus|course (outline|overview|policies))\b"),
    ("Rubrics", r"\brubrics?\b"),
    ("Study Guides", r"\b(study ?guides?|review (sheet|guide|packet)|cheat ?sheet)\b"),
    ("Glossaries", r"\b(glossar(y|ies)|vocab(ulary)?|definitions?|key terms|terms list|word list)\b"),
    ("Essays", r"\b(essays?|argumentative|persuasive|expository|literary analysis|research paper|"
               r"reflection paper|thesis|compare and contrast)\b"),
    ("Lab Reports", r"\b(lab ?reports?|labs?|experiments?)\b"),
    ("Quizzes & Tests", r"\b(quiz(zes)?|tests?|exams?|midterms?|finals? exam|assessments?)\b"),
    ("Worksheets", r"\b(worksheets?|packets?|handouts?|activity|activities)\b"),
    ("Notes", r"\b(notes?|cornell|lecture|annotations?)\b"),
    ("Presentations", r"\b(presentations?|slides?|slideshow)\b"),
    ("Projects", r"\b(projects?)\b"),
    ("Outlines", r"\b(outlines?|brainstorm(ing)?)\b"),
    ("Readings", r"\b(readings?|articles?|chapter text)\b"),
    ("Assignments", r"\b(assignments?|homework|hw|prompts?|tasks?|classwork)\b"),
    ("Invoices", r"\binvoices?\b"),
    ("Receipts", r"\b(receipts?|order confirmation)\b"),
    ("Statements", r"\b(statements?|bank|transactions)\b"),
    ("Tax Forms", r"\b(w-?2|1099|1040|tax(es)?)\b"),
    ("Resumes", r"\b(resumes?|résumés?|cv|curriculum vitae)\b"),
    ("Cover Letters", r"\bcover letters?\b"),
    ("Contracts", r"\b(contracts?|agreements?|leases?)\b"),
    ("Manuals", r"\b(manuals?|user guide|instructions)\b"),
    ("Reports", r"\breports?\b"),
]]
_TYPE_WORDS = {w for _, rx in DOC_TYPES for w in re.findall(r"[a-z]+", rx.pattern) if len(w) > 2}
NOISE |= _TYPE_WORDS - {"bank"}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z&'’]*|(?<!\d)\d{1,4}[A-Za-z]?(?!\d)")  # 5+ digit runs are IDs, not numbers


def tokenize(text: str) -> list[str]:
    # split camelCase / letter-digit joins and separators: "English3_EssayFinal" -> English 3 Essay Final
    text = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z]{2})", " ", text)
    text = re.sub(r"[_\-.+()\[\]{},;:|/\\]+", " ", text)
    return [t.strip("'’") for t in _TOKEN_RE.findall(text) if t.strip("'’")]


def _norm(tok: str) -> str:
    t = tok.lower()
    return "and" if t == "&" else t


def _is_num(tok: str) -> bool:
    return tok[0].isdigit() or tok.lower() in ROMAN


def _key(tokens: list[str]) -> str:
    out = [_norm(t) for t in tokens]
    if len(out) > 1 and out[-1] in ROMAN:
        out[-1] = ROMAN[out[-1]]
    return " ".join(out)


def _content(tok: str) -> bool:
    t = tok.lower()
    noise = t in NOISE or f"{t}s" in NOISE or f"{t}es" in NOISE  # "statement" as well as "statements"
    return t not in STOP and not noise and t not in SEQUENCE_WORDS and not _is_num(tok) and len(t) > 1


@dataclass
class Signal:
    weight: float
    surface: str
    course: bool = False


def phrases(text: str, weight: float, *, whole_line: bool, singles: bool,
            allow_sequence: bool = False) -> dict[str, Signal]:
    """Candidate phrases in one piece of text, keyed by normalized form."""
    toks = tokenize(text)
    found: dict[str, Signal] = {}

    def add(span: list[str], w: float, course: bool = False) -> None:
        k = _key(span)
        if k not in found or found[k].weight < w:
            found[k] = Signal(w, " ".join(span), course)

    # Course-like: "English 3", "AP Biology", "MATH 101", "Chem II"
    for i, tok in enumerate(toks):
        if not _is_num(tok) or i == 0 or (tok.isdigit() and len(tok) == 4 and tok.startswith(("19", "20"))):
            continue
        j = i
        while j > 0 and i - j < 3 and _content(toks[j - 1]):
            j -= 1
        if j < i:
            add(toks[j:i + 1], weight + COURSE_BONUS, course=True)
        elif allow_sequence and toks[i - 1].lower() in SEQUENCE_WORDS:
            add([toks[i - 1].capitalize(), tok], weight + COURSE_BONUS, course=True)
    for i, tok in enumerate(toks[:-1]):
        if tok.lower() in COURSE_PREFIX and _content(toks[i + 1]):
            add(toks[i:i + 2], weight + COURSE_BONUS, course=True)

    # Runs of content words -> n-grams (1..4)
    run: list[str] = []
    for tok in [*toks, "."]:
        if tok != "." and _content(tok):
            run.append(tok)
            continue
        for n in range(1 if singles else 2, 5):
            for s in range(0, len(run) - n + 1):
                span = run[s:s + n]
                if n == 1 and len(span[0]) < 3:
                    continue
                add(span, weight * (1 + 0.3 * (n - 1)))
        run = []

    # A short line on its own (an MLA heading line, a running header) is a strong unit.
    content = [t for t in toks if _content(t) or _is_num(t)]
    if whole_line and 1 <= len(content) <= 5 and any(_content(t) for t in content) and not content[0][0].isdigit():
        add(content, weight * 1.2)
    return found


def signals_for(*, name: str, title: Iterable[str] = (), headers: Iterable[str] = (),
                lines: Iterable[str] = (), allow_sequence: bool = False) -> dict[str, Signal]:
    merged: dict[str, Signal] = {}
    sources = [(t, W_TITLE, True, True) for t in title]
    sources += [(h, W_HEADER, True, True) for h in headers]
    sources += [(l, W_LINE, True, False) for l in list(lines)[:6]]
    sources += [(name, W_NAME, False, True)]
    for text, w, whole, singles in sources:
        for k, sig in phrases(text, w, whole_line=whole, singles=singles, allow_sequence=allow_sequence).items():
            if k not in merged or merged[k].weight < sig.weight:
                merged[k] = sig
    return merged


def _contains(longer: str, shorter: str) -> bool:
    return longer != shorter and f" {shorter} " in f" {longer} "


def _display(surfaces: Counter[str]) -> str:
    raw = surfaces.most_common(1)[0][0]
    if raw.islower() or raw.isupper():
        words = []
        for w in raw.split():
            if w.isupper() and len(w) <= 3 or w.isdigit():
                words.append(w)
            elif w.lower() in ROMAN:
                words.append(w.upper())
            else:
                words.append(w.capitalize())
        raw = " ".join(words)
    return raw


@dataclass
class Groups:
    assignment: dict[int, str] = field(default_factory=dict)   # item index -> topic display name
    evidence: dict[int, str] = field(default_factory=dict)     # item index -> why


def discover(item_signals: list[dict[str, Signal]], *, min_files: int = 2,
             max_share: float = 0.6, exclude: set[str] = frozenset()) -> Groups:
    """Assign items to recurring phrases. ``item_signals[i]`` are the phrases of item i."""
    n = len(item_signals)
    files: dict[str, set[int]] = defaultdict(set)
    score: Counter[str] = Counter()
    surfaces: dict[str, Counter[str]] = defaultdict(Counter)
    course: set[str] = set()
    for i, sigs in enumerate(item_signals):
        for k, sig in sigs.items():
            if k in exclude or any(_contains(k, e) or _contains(e, k) for e in exclude):
                continue
            files[k].add(i)
            score[k] += sig.weight
            surfaces[k][sig.surface] += 1
            if sig.course:
                course.add(k)

    def ok(k: str) -> bool:
        df = len(files[k])
        # a phrase on (nearly) every file is a name/school/watermark, not a topic
        return df >= min_files and not (n >= 5 and df / n > max_share and k not in course)

    kept = {k for k in files if ok(k)}
    while True:  # re-assign until every surviving group is big enough (kept shrinks each pass)
        result = Groups()
        members: dict[str, list[int]] = defaultdict(list)
        for i, sigs in enumerate(item_signals):
            cands = [k for k in sigs if k in kept]
            # prefer the most specific phrase: drop "english" when "english 3" also matches
            cands = [k for k in cands if not any(_contains(o, k) for o in cands)]
            if not cands:
                continue
            best = max(cands, key=lambda k: (k in course, score[k] * len(files[k]), len(k)))
            members[best].append(i)
        small = {k for k, m in members.items() if len(m) < min_files}
        if not small:
            for k, m in members.items():
                name = _display(surfaces[k])
                for i in m:
                    result.assignment[i] = name
                    result.evidence[i] = f"'{name}' recurs in {len(files[k])} files"
            return result
        kept -= small


def doc_type(*, name: str, title: Iterable[str] = (), lines: Iterable[str] = ()) -> str | None:
    strong = " ".join([" ".join(tokenize(name)), *title])
    weak = " ".join(list(lines)[:4])
    for text in (strong, weak):
        for label, rx in DOC_TYPES:
            if rx.search(text):
                return label
    return None


def common_prefix_name(names: list[str]) -> str:
    """'Chase_Statement_Jan', 'Chase_Statement_Feb' -> 'Chase Statement'."""
    toks = [tokenize(n) for n in names]
    out = []
    for parts in zip(*toks):
        if len({p.lower() for p in parts}) != 1 or _is_num(parts[0]):
            break
        out.append(parts[0])
    return " ".join(out)
