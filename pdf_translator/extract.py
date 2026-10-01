"""Extraktion übersetzbarer Textblöcke inkl. Layout-Informationen mit PyMuPDF."""

from __future__ import annotations

import re
from collections import Counter

import pymupdf

from .markup import escape
from .models import Document, TextBlock

# Schriften, deren Inhalt als Formel gilt und unverändert bleiben muss
# (Computer-Modern/AMS-Mathefonts aus LaTeX und gängige Symbolfonts).
MATH_FONT_RE = re.compile(
    r"CMMI|CMSY|CMEX|CMBSY|MSAM|MSBM|EUFM|EUSM|RSFS|LMMath|Math|Symbol|STIX|"
    r"Cambria.?Math|esint|wasy|stmary|txsy|pxsy|txex|pxex|rtxmi|ntxmi",
    re.I,
)
MONO_FONT_RE = re.compile(r"Mono|Courier|CMTT|LMMono|Consol|Menlo", re.I)
SANS_FONT_RE = re.compile(r"Sans|Helvetica|Arial|CMSS|LMSans|Verdana|Calibri|DejaVuSans", re.I)
BOLD_FONT_RE = re.compile(r"Bold|CMBX|Black|Heavy|Semibold|\bBX", re.I)
ITALIC_FONT_RE = re.compile(r"Italic|Oblique|CMTI|CMSL|\bTI\d", re.I)

_LETTER_RE = re.compile(r"[^\W\d_]", re.U)


def _span_style(span: dict) -> tuple[bool, bool, bool, bool]:
    font = span["font"]
    flags = span["flags"]
    is_math = bool(MATH_FONT_RE.search(font))
    bold = bool(flags & pymupdf.TEXT_FONT_BOLD) or bool(BOLD_FONT_RE.search(font))
    italic = bool(flags & pymupdf.TEXT_FONT_ITALIC) or bool(ITALIC_FONT_RE.search(font))
    sup = bool(flags & pymupdf.TEXT_FONT_SUPERSCRIPT)
    return is_math, bold, italic, sup


def _wrap(text: str, is_math: bool, bold: bool, italic: bool, sup: bool) -> str:
    if not text:
        return ""
    if is_math:
        return f"<m>{text}</m>"
    if italic:
        text = f"<i>{text}</i>"
    if bold:
        text = f"<b>{text}</b>"
    if sup:
        text = f"<sup>{text}</sup>"
    return text


def _line_to_tagged(line: dict, base_size: float) -> tuple[str, int, int]:
    """Baut den getaggten Text einer Zeile. Gibt (text, Buchstaben, Mathe-Zeichen) zurück."""
    parts: list[str] = []
    letters = math_chars = 0
    prev_style = None
    buf = ""
    for span in line["spans"]:
        text = span["text"]
        if not text:
            continue
        is_math, bold, italic, sup = _span_style(span)
        # Hochgestellt auch über die Größe/Position erkennen (Fußnotenzeichen, Zitate).
        if not sup and span["size"] < 0.8 * base_size and text.strip().isdigit():
            sup = True
        # Leerzeichen tragen keine Formatierung – sonst entstehen unnötige Tag-Grenzen.
        style = (is_math, bold, italic, sup) if text.strip() else prev_style
        n_letters = len(_LETTER_RE.findall(text))
        letters += n_letters
        if is_math:
            math_chars += len(text.strip())
        if style != prev_style and buf:
            parts.append(_wrap(escape(buf), *(prev_style or (False,) * 4)))
            buf = ""
        buf += text
        prev_style = style
    if buf:
        parts.append(_wrap(escape(buf), *(prev_style or (False,) * 4)))
    return "".join(parts), letters, math_chars


def _join_lines(lines: list[str]) -> str:
    """Verbindet Zeilen zu einem Absatz und repariert Silbentrennung am Zeilenende."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif re.search(r"[a-zäöüß]-$", out) and re.match(r"[a-zäöüß]", line):
            out = out[:-1] + line  # "transla-" + "tion" -> "translation"
        else:
            out += " " + line
    out = re.sub(r"\s+", " ", out)
    return _CLOSE_OPEN_RE.sub(_merge_adjacent, out)


# "</i></b> <b><i>" -> " ": gleiche Formatierung über Zeilengrenzen zusammenfassen
_CLOSE_OPEN_RE = re.compile(r"((?:</(?:b|i|sup|m)>)+)(\s*)((?:<(?:b|i|sup|m)>)+)")


def _merge_adjacent(m: re.Match) -> str:
    closing = re.findall(r"</(\w+)>", m.group(1))
    opening = re.findall(r"<(\w+)>", m.group(3))
    return m.group(2) if closing == opening[::-1] else m.group(0)


def _font_family(fonts: Counter) -> str:
    font = fonts.most_common(1)[0][0] if fonts else ""
    if MONO_FONT_RE.search(font):
        return "monospace"
    if SANS_FONT_RE.search(font):
        return "sans-serif"
    return "serif"


def _alignment(lines: list[dict], bbox: pymupdf.Rect, page_width: float) -> str:
    if len(lines) == 1:
        center = (bbox.x0 + bbox.x1) / 2
        if abs(center - page_width / 2) < 0.03 * page_width and bbox.width < 0.7 * page_width:
            return "center"
        return "left"
    lefts = [ln["bbox"][0] for ln in lines]
    rights = [ln["bbox"][2] for ln in lines[:-1]]
    if max(lefts) - min(lefts) > 6 and abs(
        (bbox.x0 + bbox.x1) / 2 - page_width / 2
    ) < 0.03 * page_width:
        return "center"
    if rights and max(rights) - min(rights) < 3:
        return "justify"
    return "left"


def _line_size(line: dict) -> float | None:
    sizes: Counter = Counter()
    for s in line["spans"]:
        n = len(s["text"].strip())
        if n and not MATH_FONT_RE.search(s["font"]):
            sizes[round(s["size"], 1)] += n
    return sizes.most_common(1)[0][0] if sizes else None


def _rows(lines: list[dict]) -> list[list[dict]]:
    """Fasst Zeilen auf derselben Höhe (nebeneinander stehende Spans) zu Zeilenreihen zusammen."""
    rows: list[list[dict]] = []
    for ln in lines:
        y0, y1 = ln["bbox"][1], ln["bbox"][3]
        if rows:
            r0 = min(x["bbox"][1] for x in rows[-1])
            r1 = max(x["bbox"][3] for x in rows[-1])
            if min(y1, r1) - max(y0, r0) > 0.5 * min(y1 - y0, r1 - r0):
                rows[-1].append(ln)
                continue
        rows.append([ln])
    return rows


def _split_lines(lines: list[dict]) -> list[list[dict]]:
    """Teilt einen PyMuPDF-Block, wenn sich Schriftgröße oder Zeilenabstand deutlich ändern.

    PyMuPDF fasst gelegentlich Überschrift und Folgetext zu einem Block
    zusammen; zusammen gerendert hätten sie sonst eine einzige Schriftgröße.
    """
    groups: list[list[dict]] = []
    group_size = None
    prev_bottom = None
    for row in _rows(lines):
        size = next((s for s in map(_line_size, row) if s), None) or group_size
        top = min(ln["bbox"][1] for ln in row)
        new = (
            not groups
            or (size and group_size and abs(size - group_size) / group_size > 0.15)
            or (prev_bottom is not None and size and top - prev_bottom > 0.9 * size)
        )
        if new:
            groups.append([])
            group_size = size
        groups[-1].extend(row)
        prev_bottom = max(ln["bbox"][3] for ln in row)
    return groups


def _make_block(lines: list[dict], block_id: str, pno: int, page_width: float, min_letters: int) -> TextBlock | None:
    sizes: Counter = Counter()
    fonts: Counter = Counter()
    colors: Counter = Counter()
    for ln in lines:
        for s in ln["spans"]:
            n = len(s["text"].strip())
            if n and not MATH_FONT_RE.search(s["font"]):
                sizes[round(s["size"], 1)] += n
                fonts[s["font"]] += n
                colors[s["color"]] += n
    if not sizes:
        return None  # nur Formel-Schriften
    base_size = sizes.most_common(1)[0][0]

    tagged_lines = []
    letters = math_chars = 0
    for ln in lines:
        t, nl, nm = _line_to_tagged(ln, base_size)
        tagged_lines.append(t)
        letters += nl
        math_chars += nm
    if letters < min_letters or math_chars > letters:
        return None  # Seitenzahl, Zahlentabelle oder abgesetzte Formel

    bbox = pymupdf.Rect()
    for ln in lines:
        bbox |= ln["bbox"]
    rows = _rows(lines)
    line_height = 1.2
    if len(rows) > 1:
        pitch = (rows[-1][0]["bbox"][1] - rows[0][0]["bbox"][1]) / (len(rows) - 1)
        line_height = max(1.0, min(2.0, pitch / base_size))

    return TextBlock(
        id=block_id,
        page=pno,
        bbox=tuple(bbox),
        line_rects=[tuple(ln["bbox"]) for ln in lines],
        tagged=_join_lines(tagged_lines),
        font_size=base_size,
        color=colors.most_common(1)[0][0],
        font_family=_font_family(fonts),
        align=_alignment([r[0] for r in rows] if len(rows) > 1 else lines, bbox, page_width),
        line_height=round(line_height, 3),
    )


def extract_document(path: str, min_letters: int = 2) -> Document:
    """Zerlegt das PDF in übersetzbare Textblöcke.

    Übersprungen werden: Bilder, gedrehter Text, Blöcke ohne nennenswerten Text
    (Seitenzahlen) und Blöcke, die überwiegend aus Formeln bestehen.
    """
    doc = pymupdf.open(path)
    result = Document(path=path, page_count=doc.page_count)
    for pno, page in enumerate(doc):
        data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES)
        for bno, block in enumerate(data["blocks"]):
            if block["type"] != 0:
                continue  # Bild-Block: bleibt unverändert
            lines = [ln for ln in block["lines"] if any(s["text"].strip() for s in ln["spans"])]
            if not lines:
                continue
            if any(abs(ln["dir"][0] - 1) > 1e-3 for ln in lines):
                continue  # gedrehter Text (z. B. arXiv-Randvermerk)
            groups = _split_lines(lines)
            for gno, group in enumerate(groups):
                block_id = f"p{pno}b{bno}" if len(groups) == 1 else f"p{pno}b{bno}g{gno}"
                tb = _make_block(group, block_id, pno, page.rect.width, min_letters)
                if tb:
                    result.blocks.append(tb)
    doc.close()
    return result
