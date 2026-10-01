"""Erzeugt ein Beispiel-PDF im Stil eines LaTeX-Papers (2 Spalten, Bild, Formel)."""

from __future__ import annotations

import sys

import pymupdf

LOREM = (
    "Machine translation has improved considerably in recent years. Modern systems "
    "translate whole paragraphs instead of isolated words, which preserves the meaning "
    "of each sentence. In this paper we study how the layout of a document can be kept "
    "intact while its text is replaced by a translation. We evaluate our approach on "
    "126 documents and report an accuracy of 97.5 percent [12]."
)


def make_sample(path: str, pages: int = 3) -> None:
    doc = pymupdf.open()
    for pno in range(pages):
        page = doc.new_page(width=595, height=842)
        if pno == 0:
            page.insert_textbox(pymupdf.Rect(72, 60, 523, 90), "Layout-Preserving Translation of PDF Documents",
                                fontname="tibo", fontsize=16, align=pymupdf.TEXT_ALIGN_CENTER)
            page.insert_textbox(pymupdf.Rect(72, 92, 523, 110), "Jane Doe and John Smith",
                                fontname="tiro", fontsize=11, align=pymupdf.TEXT_ALIGN_CENTER)
        top = 130 if pno == 0 else 72
        for col, x0 in enumerate((72, 310)):
            y = top
            page.insert_text((x0, y), f"{pno * 2 + col + 1}  Introduction" if col == 0 else f"{pno * 2 + col + 1}  Method",
                             fontname="tibo", fontsize=12)
            y += 10
            r = pymupdf.Rect(x0, y, x0 + 213, y + 150)
            page.insert_textbox(r, LOREM, fontname="tiro", fontsize=10, align=pymupdf.TEXT_ALIGN_JUSTIFY)
            y += 155
            page.insert_text((x0, y + 10), "The proposed method is", fontname="tiro", fontsize=10)
            page.insert_text((x0 + 103, y + 10), "fast", fontname="tiit", fontsize=10)
            page.insert_text((x0 + 122, y + 10), "and", fontname="tiro", fontsize=10)
            page.insert_text((x0 + 140, y + 10), "robust.", fontname="tibo", fontsize=10)
            y += 25
            # abgesetzte "Formel" in Symbol-Schrift: darf nicht verändert werden
            page.insert_text((x0 + 70, y + 10), "a + b = g", fontname="symb", fontsize=11)
            y += 25
            # Bild
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 60), 0)
            pix.set_rect(pix.irect, (40, 110, 200))
            pix.set_rect(pymupdf.IRect(0, 0, 60, 60), (230, 120, 30))
            page.insert_image(pymupdf.Rect(x0 + 30, y, x0 + 183, y + 76), pixmap=pix)
            y += 82
            page.insert_textbox(pymupdf.Rect(x0, y, x0 + 213, y + 30),
                                "Figure 1: The colored image must remain unchanged after translation.",
                                fontname="tiro", fontsize=9, align=pymupdf.TEXT_ALIGN_LEFT)
            y += 40
            page.insert_textbox(pymupdf.Rect(x0, y, x0 + 213, y + 150), LOREM, fontname="tiro",
                                fontsize=10, align=pymupdf.TEXT_ALIGN_JUSTIFY)
        page.insert_text((290, 800), str(pno + 1), fontname="tiro", fontsize=10)
    doc.save(path)


if __name__ == "__main__":
    make_sample(sys.argv[1] if len(sys.argv) > 1 else "sample.pdf")
