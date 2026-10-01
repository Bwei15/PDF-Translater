"""Schreibt übersetzten Text an die Originalposition zurück.

Vorgehen pro Seite:
  1. Den Originaltext der übersetzten Blöcke per Redaction entfernen – dabei
     ausdrücklich Bilder und Vektorgrafiken unangetastet lassen und nichts
     übermalen (Hintergründe/Farbkästen bleiben erhalten).
  2. Die Übersetzung als HTML in die ursprüngliche Blockbox setzen. Passt der
     (meist längere) Text nicht hinein, wird er minimal verkleinert.
"""

from __future__ import annotations

import os

import pymupdf

from .markup import to_html
from .models import Document, TextBlock

_FONT_FACES = {
    "regular": ("normal", "normal"),
    "bold": ("bold", "normal"),
    "italic": ("normal", "italic"),
    "bolditalic": ("bold", "italic"),
}


def _font_css(fonts: dict[str, str] | None) -> tuple[str, pymupdf.Archive | None]:
    """@font-face-Regeln für eigene Schriftdateien, z. B. Latin Modern für LaTeX-PDFs."""
    if not fonts:
        return "", None
    archive = pymupdf.Archive()
    rules = []
    for kind, path in fonts.items():
        weight, style = _FONT_FACES[kind]
        folder, name = os.path.split(os.path.abspath(path))
        archive.add(folder)
        rules.append(
            f"@font-face {{font-family: docfont; src: url({name}); "
            f"font-weight: {weight}; font-style: {style};}}"
        )
    return "\n".join(rules), archive


def _block_html(block: TextBlock, use_custom_font: bool) -> str:
    family = "docfont" if use_custom_font and block.font_family == "serif" else block.font_family
    c = block.color
    color = f"#{c:06x}" if isinstance(c, int) else "#000000"
    style = (
        f"font-family: {family}; font-size: {block.font_size:.2f}px; color: {color}; "
        f"text-align: {block.align}; line-height: {block.line_height:.3f};"
    )
    return f'<div style="{style}">{to_html(block.translation or block.tagged)}</div>'


def _expanded_rect(
    block: TextBlock, obstacles: list[pymupdf.Rect], page_rect: pymupdf.Rect
) -> pymupdf.Rect:
    """Vergrößert die Blockbox in angrenzenden freien Platz (ohne Text/Bilder zu überdecken).

    Nach unten bis zum nächsten Element (max. 3 Zeilen); einzeilige Blöcke
    (Überschriften, Beschriftungen) zusätzlich in der Breite.
    """
    rect = pymupdf.Rect(block.bbox)
    own = pymupdf.Rect(block.bbox) + (-1, -1, 1, 1)
    others = [o for o in obstacles if not own.contains(o) and not o.is_empty]
    margin = 36
    pitch = block.font_size * block.line_height

    below = [o.y0 for o in others if o.y0 >= rect.y1 - 1 and o.x0 < rect.x1 and o.x1 > rect.x0]
    bottom = min([y - 0.5 * pitch for y in below] + [page_rect.y1 - margin, rect.y1 + 3 * pitch])
    result = pymupdf.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1, bottom))

    if len(block.line_rects) == 1:
        def overlaps_v(o):
            return o.y0 < result.y1 and o.y1 > result.y0

        right = min([o.x0 for o in others if overlaps_v(o) and o.x0 >= rect.x1 - 1] + [page_rect.x1 - margin]) - 2
        left = max([o.x1 for o in others if overlaps_v(o) and o.x1 <= rect.x0 + 1] + [page_rect.x0 + margin]) + 2
        if block.align == "center":
            grow = max(0.0, min(rect.x0 - left, right - rect.x1))
            result.x0, result.x1 = rect.x0 - grow, rect.x1 + grow
        else:
            result.x1 = max(rect.x1, right)
    return result


def render_document(
    document: Document,
    output_path: str,
    fonts: dict[str, str] | None = None,
    min_scale: float = 0.6,
) -> list[str]:
    """Erzeugt das übersetzte PDF. Gibt Warnungen zurück (z. B. stark verkleinerte Blöcke)."""
    warnings: list[str] = []
    font_rules, archive = _font_css(fonts)
    css = font_rules + "\n.m {font-style: italic;} sup, sub {font-size: 70%;} p, div {margin: 0; padding: 0;}"

    pdf = pymupdf.open(document.path)
    for pno, page in enumerate(pdf):
        blocks = [b for b in document.blocks_on_page(pno) if b.translation]
        if not blocks:
            continue
        # Alle Text- und Bildbereiche der Originalseite als Hindernisse merken.
        obstacles = [pymupdf.Rect(b[:4]) for b in page.get_text("blocks")]
        obstacles += [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]

        for block in blocks:
            for x0, y0, x1, y1 in block.line_rects:
                # Etwas schmaler in der Höhe, damit Nachbarzeilen unberührt bleiben.
                pad = (y1 - y0) * 0.15
                page.add_redact_annot(pymupdf.Rect(x0, y0 + pad, x1, y1 - pad), fill=False)
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )

        for block in blocks:
            rect = pymupdf.Rect(block.bbox)
            # Etwas Luft nach rechts/unten: Rendering-Unterschiede der Ersatzschrift.
            rect.x1 += block.font_size * 0.15
            rect.y1 += block.font_size * 0.25
            wide = _expanded_rect(block, obstacles, page.rect) | rect
            html = _block_html(block, archive is not None)
            # Reihenfolge: Originalbox in Originalgröße -> freien Platz nutzen ->
            # verkleinern (bis min_scale) -> notfalls beliebig verkleinern.
            for target, low in ((rect, 1), (wide, 1), (wide, min_scale), (wide, 0)):
                spare, scale = page.insert_htmlbox(target, html, css=css, archive=archive, scale_low=low)
                if spare >= 0:
                    break
            if scale < 0.85:
                warnings.append(f"Seite {pno + 1}, Block {block.id}: Schrift auf {scale:.0%} verkleinert")

    pdf.subset_fonts()
    pdf.save(output_path, garbage=3, deflate=True)
    pdf.close()
    return warnings
