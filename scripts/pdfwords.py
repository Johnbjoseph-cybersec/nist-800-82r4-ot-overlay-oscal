"""Word-level PDF reading via poppler's `pdftotext -bbox`.

Standard library only. Requires the `pdftotext` binary (poppler) on PATH.
"""

import html
import re
import subprocess
from dataclasses import dataclass

_WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>'
)


@dataclass(frozen=True)
class Word:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def xc(self):
        return (self.x0 + self.x1) / 2

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2


def read_pages(pdf, first, last):
    """Return {page_number: [Word, ...]} for pages first..last (1-based, inclusive)."""
    out = subprocess.run(
        ["pdftotext", "-f", str(first), "-l", str(last), "-bbox", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pages = {}
    for i, chunk in enumerate(out.split("<page ")[1:]):
        num = first + i
        pages[num] = [
            Word(num, float(a), float(b), float(c), float(d), html.unescape(t))
            for a, b, c, d, t in _WORD.findall(chunk)
        ]
    return pages


def group_lines(words, tol=4.0):
    """Group words into visual lines by vertical centre; each line sorted left to right."""
    lines = []
    for w in sorted(words, key=lambda w: (w.yc, w.x0)):
        if lines and abs(lines[-1][0] - w.yc) <= tol:
            lines[-1][1].append(w)
        else:
            lines.append([w.yc, [w]])
    return [(y, sorted(ws, key=lambda w: w.x0)) for y, ws in lines]


def find_page(pdf, first, last, needle):
    """First page in range whose plain text contains needle."""
    for p in range(first, last + 1):
        txt = subprocess.run(
            ["pdftotext", "-f", str(p), "-l", str(p), str(pdf), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if needle in txt:
            return p
    raise LookupError(f"{needle!r} not found in pages {first}-{last}")
