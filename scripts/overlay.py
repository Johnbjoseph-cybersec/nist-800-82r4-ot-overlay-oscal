"""Extract the SP 800-53r5 OT overlay from NIST SP 800-82 (r3 final, r4 ipd).

Three independent readings are produced from the PDF:

* summary   - the "Control baselines" summary table (Table 18 in r4 ipd, Table 22 in r3):
              per baseline column, the set of control and enhancement IDs printed in it.
* detailed  - the per-control specification tables (E.7 in r4 ipd, F.7 in r3):
              per control, the marker in each baseline column (Select, Add, Remove or blank).
* prose     - r4 only: OT Discussion, enhancement discussions, rationale and family tailoring
              text, taken only from line-numbered body lines, so table cells never leak in.

Standard library only, plus the poppler `pdftotext` binary.
"""

import re
from dataclasses import dataclass, field

try:
    from . import pdfwords
except ImportError:  # run as a script
    import pdfwords

LEVELS = ("LOW", "MOD", "HIGH")
MARKERS = {"Select", "Add", "Remove"}
ID_RE = re.compile(r"^[A-Z]{2}-\d{1,2}$")
ENH_RE = re.compile(r"^\((\d{1,2})\)$")


@dataclass(frozen=True)
class Edition:
    key: str
    pdf_name: str
    sha256: str
    summary_caption: str
    detailed_start: str
    detailed_end: str
    line_numbered: bool
    search_from: int
    search_to: int
    # (pdf page, label as printed, label meant, evidence) - applied and reported, never guessed
    errata: tuple = ()


R4 = Edition(
    key="r4-ipd",
    pdf_name="NIST.SP.800-82r4.ipd.pdf",
    sha256="66e00d5c8dbbfaf0342890e75d2492f72e1ef34da81df5c6a94cc339bd91f683",
    summary_caption="Table 18. Control baselines",
    detailed_start="E.7.1. ACCESS CONTROL",
    detailed_end="Appendix F. Applying the Risk",
    line_numbered=True,
    search_from=200,
    search_to=321,
)
R3 = Edition(
    key="r3",
    pdf_name="NIST.SP.800-82r3.pdf",
    sha256="608f554514d381853e24e0b33123b7080fbd757826f460032690aade63394616",
    summary_caption="Table 22. Control baselines",
    detailed_start="F.7.1. ACCESS CONTROL",
    detailed_end="Appendix G. Change Log",
    line_numbered=False,
    search_from=200,
    search_to=320,
    errata=(
        (285, "PL-4(1)", "PL-8(1)",
         "row titled 'SECURITY AND PRIVACY ARCHITECTURES | DEFENSE IN DEPTH' under PL-8; PL-4(1) is already on p. 284"),
    ),
)


def label(base, enh=None):
    """Canonical SP 800-53 label, e.g. AC-2(13)."""
    return f"{base}({enh})" if enh else base


def oscal_id(lbl):
    """AC-2(13) -> ac-2.13 (the id form used in NIST's OSCAL catalog)."""
    m = re.fullmatch(r"([A-Z]{2})-(\d+)(?:\((\d+)\))?", lbl)
    if not m:
        raise ValueError(f"not a control label: {lbl!r}")
    fam, num, enh = m.groups()
    return f"{fam.lower()}-{num}" + (f".{enh}" if enh else "")


def _line_number_ys(words):
    return [w.yc for w in words if w.x1 < 62 and w.text.isdigit()]


def _numbered(y, ys, tol=4.0):
    return any(abs(y - v) <= tol for v in ys)


def _header(line_words):
    """Column centres if this visual line is a LOW / MOD / HIGH header row."""
    found = {w.text: w.xc for w in line_words if w.text in LEVELS}
    return found if len(found) == 3 else None


def _anchor_y(words, needle):
    """y of the first visual line whose text starts with needle's first token sequence."""
    toks = needle.split()
    for y, ws in pdfwords.group_lines(words):
        texts = [w.text for w in ws]
        for i in range(len(texts) - len(toks) + 1):
            if texts[i : i + len(toks)] == toks:
                return y
    return None


@dataclass
class Reading:
    edition: str
    summary: dict = field(default_factory=dict)  # level -> {label: [page, ...]}
    detailed: dict = field(default_factory=dict)  # label -> {"markers": {level: marker}, "page": n, "name": str}
    pages: dict = field(default_factory=dict)  # which pdf pages each reading used
    tables: list = field(default_factory=list)
    summary_pos: dict = field(default_factory=dict)


def read_summary(pdf, ed, first):
    """Read the summary table starting at page `first`, until a page has no column header."""
    out = {lv: {} for lv in LEVELS}
    pos = {lv: {} for lv in LEVELS}  # level -> label -> [(page, x-centre, y-centre)] of its token
    used = []
    page = first
    while True:
        words = pdfwords.read_pages(pdf, page, page)[page]
        lines = pdfwords.group_lines(words)
        hdr = None
        for y, ws in lines:
            h = _header(ws)
            if h:
                hdr = (y, h)
                break
        if not hdr:
            break
        used.append(page)
        hy, centres = hdr
        lo, md, hi = centres["LOW"], centres["MOD"], centres["HIGH"]
        bounds = {
            "LOW": (lo - (md - lo) / 2, (lo + md) / 2),
            "MOD": ((lo + md) / 2, (md + hi) / 2),
            "HIGH": ((md + hi) / 2, hi + (hi - md) / 2 + 20),
        }
        nums = _line_number_ys(words) if ed.line_numbered else []
        current = {lv: None for lv in LEVELS}
        for y, ws in lines:
            if y <= hy + 2:
                continue
            if _numbered(y, nums):
                continue
            if ws[0].x0 < 76 and not ID_RE.match(ws[0].text):
                break  # body prose after the table: table ends on this page
            for w in ws:
                lv = next((k for k, (a, b) in bounds.items() if a <= w.xc < b), None)
                if lv is None:
                    continue
                if ID_RE.match(w.text):
                    current[lv] = w.text
                    out[lv].setdefault(label(w.text), []).append(page)
                    pos[lv].setdefault(label(w.text), []).append((page, w.xc, w.yc))
                else:
                    m = ENH_RE.match(w.text)
                    if m and current[lv]:
                        out[lv].setdefault(label(current[lv], m.group(1)), []).append(page)
                        pos[lv].setdefault(label(current[lv], m.group(1)), []).append((page, w.xc, w.yc))
        page += 1
    return out, used, pos


def read_detailed(pdf, ed, start_page, end_page):
    """Read every control row of the detailed specification tables.

    A table starts at a LOW / MOD / HIGH header line and ends at the first body-prose line
    (a line starting at the left margin with no control ID) or the next header. Inside a table,
    each control ID in the CNTL NO. column is a row anchor, and each Select / Add / Remove word
    belongs to the anchor nearest to it vertically (r3 sometimes prints a marker one line off
    the ID when the control name wraps).
    """
    pages = pdfwords.read_pages(pdf, start_page, end_page)
    rows = {}
    tables = []  # reading-order events: {"page", "y", "base"} - used to attach prose to controls
    hdr = None

    def close(table, page):
        anchors, marks = table
        if marks and not anchors:
            raise RuntimeError(f"markers with no control row on page {page}")
        for a in anchors:
            a["markers"] = {}
        for w, centres in marks:
            a = min(anchors, key=lambda a: abs(a["y"] - w.yc))
            if abs(a["y"] - w.yc) > 14:
                raise RuntimeError(f"marker {w.text} at y={w.yc:.0f} p{page} far from any row")
            lv = min(LEVELS, key=lambda k: abs(centres[k] - w.xc))
            if lv in a["markers"]:
                raise RuntimeError(f"two markers in {lv} for {a['label']} on page {page}")
            a["markers"][lv] = w.text
        for a in anchors:
            for e_page, printed, meant, _why in ed.errata:
                if page == e_page and a["label"] == printed:
                    a["label"] = meant
            if a["label"] in rows:
                raise RuntimeError(f"{a['label']} appears twice (pages {rows[a['label']]['page']} and {page})")
            rows[a["label"]] = {"markers": a["markers"], "page": page, "name": a["name"]}
        if anchors:
            tables.append({"page": page, "y": anchors[0]["y"], "base": anchors[0]["label"].split("(")[0]})

    for page in range(start_page, end_page + 1):
        words = pages[page]
        y_min = _anchor_y(words, ed.detailed_start) if page == start_page else None
        y_max = _anchor_y(words, ed.detailed_end) if page == end_page else None
        nums = _line_number_ys(words) if ed.line_numbered else []
        table = None
        for y, ws in pdfwords.group_lines(words):
            if y_min is not None and y < y_min:
                continue
            if y_max is not None and y >= y_max:
                continue
            h = _header(ws)
            if h:
                if table:
                    close(table, page)
                hdr = h
                table = ([], [])
                continue
            if _numbered(y, nums):
                if table:
                    close(table, page)
                    table = None
                continue
            first = ws[0]
            if table and ENH_RE.match(first.text) and first.x0 < 120 and table[0]:
                last = table[0][-1]
                if "(" not in last["label"] and 0 < y - last["y"] <= 26:
                    # r3 wraps the enhancement number onto its own line under the ID
                    last["label"] = label(last["label"], ENH_RE.match(first.text).group(1))
                    last["y"] = (last["y"] + y) / 2
                    for w in ws[1:]:
                        if w.text in MARKERS:
                            table[1].append((w, hdr))
                    continue
            is_id = ID_RE.match(first.text) and first.x0 < 140
            if not is_id and first.x0 < 76:
                if table:
                    close(table, page)
                    table = None
                continue
            if table is None:
                # a table continued from the previous page repeats no header in some layouts
                if is_id and any(w.text in MARKERS for w in ws) and hdr:
                    table = ([], [])
                else:
                    continue
            rest = ws[1:] if is_id else ws
            enh = None
            if is_id and rest and ENH_RE.match(rest[0].text) and rest[0].x0 < 160:
                enh = ENH_RE.match(rest[0].text).group(1)
                rest = rest[1:]
            for w in rest:
                if w.text in MARKERS:
                    table[1].append((w, hdr))
            if is_id:
                name = " ".join(w.text for w in rest if w.text not in MARKERS)
                table[0].append({"label": label(first.text, enh), "y": y, "name": name})
        if table:
            close(table, page)
    return rows, tables


def locate(pdf, ed):
    s = pdfwords.find_page(pdf, ed.search_from, ed.search_to, ed.summary_caption)
    d0 = pdfwords.find_page(pdf, s, ed.search_to, ed.detailed_start)
    d1 = pdfwords.find_page(pdf, d0, ed.search_to, ed.detailed_end)
    return s, d0, d1


def read_tables(pdf, ed):
    s, d0, d1 = locate(pdf, ed)
    r = Reading(edition=ed.key)
    r.summary, used, r.summary_pos = read_summary(pdf, ed, s)
    r.detailed, r.tables = read_detailed(pdf, ed, d0, d1)
    r.pages = {"summary": used, "detailed": [d0, d1]}
    return r


def baseline_sets(detailed):
    """level -> set of labels the overlay places in that baseline (Select or Add)."""
    return {
        lv: {k for k, v in detailed.items() if v["markers"].get(lv) in ("Select", "Add")}
        for lv in LEVELS
    }


# ---------------------------------------------------------------- prose (r4 only)

_HEADER_FOOTER = re.compile(r"^(NIST SP 800-82r4 ipd|September 2026|Guide to OT Security)")


def prose_lines(pdf, ed, start_page, end_page):
    """(page, y, line_no, text) for every line-numbered body line in the range."""
    pages = pdfwords.read_pages(pdf, start_page, end_page)
    out = []
    for page in range(start_page, end_page + 1):
        words = pages[page]
        nums = {round(w.yc, 1): w.text for w in words if w.x1 < 62 and w.text.isdigit()}
        body = [w for w in words if w.x0 >= 62]
        for y, ws in pdfwords.group_lines(body):
            hit = [n for ny, n in nums.items() if abs(ny - y) <= 4]
            if not hit:
                continue
            text = " ".join(w.text for w in ws)
            text = re.sub(r"\s+([.,;:])(?=\s|$)", r"\1", text)  # pdftotext splits some full stops off
            out.append((page, y, int(hit[0]), text))
    return out


_CTRL_HEAD = re.compile(r"^([A-Z]{2}-\d{1,2})\s+([A-Z][A-Z0-9 ,\-/()&]+)$")
_FAMILY = re.compile(r"^E\.7\.(\d+)\.\s+(.+?)(?:\s+(?:-|–)\s+([A-Z]{2}))?$")
_FAMILY_TAIL = re.compile(r"^(?:-|–)\s+([A-Z]{2})$")
_SUBSECTION = re.compile(r"^(E\.7\.(\d+)\.(\d+)\.)\s+(Tailoring Considerations|Characteristics)\b")
_ENH = re.compile(r"^Control Enhancements?:\s+((?:\(\d+\)\s*)+)(.*)$")
_RATIONALE = re.compile(
    r"^Rationale for (adding|removing|supplementing)\s+([A-Z]{2}-\d+(?: \(\d+\))?)(?:\s+control)?\s+(?:to|from)\s+(.+?)\s*:\s*(.*)$"
)
_NO_DISC = "no ot discussion for this control"


def _join(parts):
    text = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if text.endswith("-") and not text.endswith(" -"):
            text += p  # hyphenated compound split across lines, e.g. "non-" / "routable"
        else:
            text += (" " if text else "") + p
    return text


def read_prose(pdf, ed, start_page, end_page, tables):
    """Parse E.7 body text into family notes and per-control discussion and rationale.

    r4 prints a heading line only for some controls, so each "OT Discussion:" is attached to
    the control of the specification table that precedes it in reading order (`tables`, from
    read_detailed). Returns (families, controls, anomalies, subsections).
    """
    events = [(p, y, "line", (no, text)) for p, y, no, text in prose_lines(pdf, ed, start_page, end_page)]
    events += [(t["page"], t["y"], "table", t["base"]) for t in tables]
    events.sort(key=lambda e: (e[0], e[1], 0 if e[2] == "table" else 1))

    families, controls, anomalies, subsections = {}, {}, [], []
    started = False
    fam = None
    pending_family = None
    ctrl = None
    buf = None  # [kind, key, texts, first_line, page]

    def entry(lbl):
        return controls.setdefault(lbl, {"family": lbl.split("-")[0]})

    def flush():
        nonlocal buf
        if not buf:
            return
        kind, key, texts, first, page = buf
        text = _join(texts)
        if kind == "family-note":
            families[key]["note"] = text
            families[key]["note_line"] = first
        elif kind == "discussion":
            e = entry(key)
            if text.lower().rstrip(".") == _NO_DISC:
                e["no_ot_discussion_line"] = first
            else:
                e["discussion"] = text
                e["discussion_line"] = first
        elif kind == "enh":
            ids, body = key
            for n in ids:
                e = entry(label(ctrl, n))
                if body is None:
                    e["no_ot_discussion_line"] = first
                else:
                    e["discussion"] = _join([body] + texts)
                    e["discussion_line"] = first
        elif kind == "rationale":
            verb, target, level = key
            entry(target).setdefault("rationale", []).append(
                {"action": verb, "baselines": level, "text": text, "line": first}
            )
        buf = None

    heading_no = None
    heading_wrap = False
    for page, y, kind, payload in events:
        if kind == "table":
            if started:
                flush()
                ctrl = payload
                entry(ctrl)
            continue
        no, text = payload
        if not started:
            if text.startswith(ed.detailed_start):
                started = True
            else:
                continue
        if text.startswith("Appendix F."):
            break
        if pending_family is not None:
            m = _FAMILY_TAIL.match(text)
            if m:
                fam = m.group(1)
                families[fam] = pending_family
                pending_family = None
                continue
            raise RuntimeError(f"line {no}: family heading without a family code")
        m = _FAMILY.match(text)
        if m:
            flush()
            info = {"title": m.group(2).strip(), "section": f"E.7.{m.group(1)}", "line": no}
            ctrl = None
            if m.group(3):
                fam = m.group(3)
                families[fam] = info
            else:
                pending_family = info
            continue
        m = _SUBSECTION.match(text)
        if m:
            flush()
            subsections.append({"number": m.group(1), "family_section": f"E.7.{m.group(2)}",
                                "ordinal": int(m.group(3)), "family": fam, "line": no, "page": page,
                                "heading": text})
            buf = ["family-note", fam, [], no, page]
            heading_wrap = not text.rstrip().endswith("Family")
            continue
        if heading_wrap:
            heading_wrap = False
            continue  # second line of a wrapped subsection heading (PM)
        if heading_no is not None and no == heading_no + 1 and text.upper() == text:
            heading_no = no
            continue  # wrapped control heading, e.g. PM-25
        m = _CTRL_HEAD.match(text)
        if m and fam and m.group(1).startswith(fam + "-"):
            flush()
            heading_no = no
            ctrl = m.group(1)  # PM tables have no baseline header, so the heading sets the control
            entry(ctrl)["heading_line"] = no
            continue
        if text.startswith("OT Discussion:"):
            flush()
            if not ctrl:
                raise RuntimeError(f"line {no}: OT Discussion before any control table")
            buf = ["discussion", ctrl, [text[len("OT Discussion:"):]], no, page]
            continue
        m = _ENH.match(text)
        if m and ctrl:
            flush()
            ids = re.findall(r"\((\d+)\)", m.group(1))
            rest = m.group(2).strip()
            if rest.lower().startswith("no ot discussion"):
                if rest.lower().rstrip(".") != _NO_DISC:
                    anomalies.append({"line": no, "page": page, "kind": "nonstandard-no-discussion-wording", "text": text})
                buf = ["enh", (ids, None), [], no, page]
                flush()
            elif rest.lower().startswith("ot discussion:"):
                buf = ["enh", (ids, rest[len("OT Discussion:"):].strip()), [], no, page]
            else:
                anomalies.append({"line": no, "page": page, "kind": "enhancement-without-label", "text": text})
                buf = ["enh", (ids, rest), [], no, page]
            continue
        m = _RATIONALE.match(text)
        if m:
            flush()
            target = m.group(2).replace(" (", "(")
            buf = ["rationale", (m.group(1), target, m.group(3)), [m.group(4)], no, page]
            continue
        if text.lower().rstrip(".") == _NO_DISC and ctrl and not buf:
            anomalies.append({"line": no, "page": page, "kind": "no-discussion-without-label", "text": text,
                              "control": ctrl})
            entry(ctrl)["no_ot_discussion_line"] = no
            continue
        if not buf and fam and ctrl is None and families[fam].get("line") is not None:
            # family introduction printed without a numbered subsection heading (RA)
            anomalies.append({"line": no, "page": page, "kind": "family-text-without-subsection-heading",
                              "text": text, "family": fam})
            buf = ["family-note", fam, [text], no, page]
            continue
        if buf:
            buf[2].append(text)
        else:
            anomalies.append({"line": no, "page": page, "kind": "unattached-text", "text": text})
    flush()
    return families, controls, anomalies, subsections


# ---------------------------------------------------------------- summary-table emphasis (r4)

_XML_TEXT = re.compile(r'<text top="(\d+)" left="(\d+)" width="(\d+)" height="(\d+)" font="\d+">(.*?)</text>')


def read_summary_bold(pdf, summary_pos):
    """level -> {label: bold?} for every summary-table token, using pdftohtml's <b> markup.

    The table key says bold marks controls and enhancements that carry an OT discussion.
    Token positions come from read_summary (pdftotext -bbox, PDF points); pdftohtml -xml
    reports the same page at 1.5x, so each token is looked up by its centre point.
    """
    import html as _html
    import subprocess

    pages = sorted({p for lv in summary_pos for lst in summary_pos[lv].values() for p, _, _ in lst})
    segs = {}
    for page in pages:
        xml = subprocess.run(
            ["pdftohtml", "-xml", "-i", "-f", str(page), "-l", str(page), "-stdout", str(pdf)],
            check=True, capture_output=True, text=True,
        ).stdout
        m = re.search(r'<page number="\d+"[^>]* height="(\d+)" width="(\d+)"', xml)
        scale = int(m.group(1)) / 792.0
        segs[page] = [
            (int(l) / scale, int(t) / scale, (int(l) + int(w)) / scale, (int(t) + int(h)) / scale, "<b>" in body)
            for t, l, w, h, body in _XML_TEXT.findall(xml)
        ]
    out = {lv: {} for lv in LEVELS}
    for lv in LEVELS:
        for lbl, lst in summary_pos[lv].items():
            if lbl.startswith("PM-"):
                continue
            page, xc, yc = lst[0]
            hits = [(x0, x1, b) for x0, y0, x1, y1, b in segs[page] if x0 <= xc <= x1 and y0 <= yc <= y1]
            if not hits:
                raise RuntimeError(f"no text run under {lbl} ({lv}) on page {page}")
            # runs can overlap by a fraction of a point: take the run centred nearest the token
            out[lv][lbl] = min(hits, key=lambda h: abs((h[0] + h[1]) / 2 - xc))[2]
    return out
