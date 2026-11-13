"""Fill NIST's SP 800-82r4 ipd comment template with comment/comment-items.json.

    python3 comment/make_xlsx.py   ->  comment/SP800-82r4-ipd-comments.xlsx

The template (sources/sp800-82r4-ipd-comment-template.xlsx, hash in SOURCES.md) is copied byte for
byte except the first worksheet's rows 2..n+1 and the "Submitted by" page header. Standard library only.
"""
import json
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "sources" / "sp800-82r4-ipd-comment-template.xlsx"
OUT = ROOT / "comment" / "SP800-82r4-ipd-comments.xlsx"
COLS = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]  # # | Submitter | Type | Page | Start | End | Section | Comment | Proposed change
STYLE = "1"  # template style: thin border, wrap text


def cell(ref, value):
    if isinstance(value, int):
        return f'<c r="{ref}" s="{STYLE}"><v>{value}</v></c>'
    return f'<c r="{ref}" s="{STYLE}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def main():
    data = json.loads((ROOT / "comment" / "comment-items.json").read_text())
    rows = {}
    for i, it in enumerate(data["items"], start=1):
        r = i + 1
        vals = [i, data["submitter"], it["type"], it["page"], it["start"], it["end"], it["section"], it["comment"], it["proposed"]]
        rows[r] = f'<row r="{r}" spans="1:9">' + "".join(cell(f"{c}{r}", v) for c, v in zip(COLS, vals)) + "</row>"
    with zipfile.ZipFile(TEMPLATE) as zin, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            body = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                xml = body.decode("utf-8")
                for r, new in rows.items():
                    pat = re.compile(rf'<row r="{r}"[^>]*?(?:/>|>.*?</row>)', re.S)
                    xml, n = pat.subn(new, xml, count=1)
                    if n != 1:
                        raise SystemExit(f"template row {r} not found")
                xml = xml.replace("Submitted by: ______________________", "Submitted by: " + escape(data["submitter"]))
                xml = xml.replace("Date: ___________", "Date: " + escape(data.get("date", "___________")))
                body = xml.encode("utf-8")
            zout.writestr(info, body)
    print(f"wrote {OUT.relative_to(ROOT)} with {len(rows)} comments")


if __name__ == "__main__":
    main()
