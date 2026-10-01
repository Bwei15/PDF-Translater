"""Datenmodell: ein PDF wird in übersetzbare Textblöcke (Absätze) zerlegt."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextBlock:
    """Ein zusammenhängender Textblock (meist ein Absatz) auf einer Seite.

    ``tagged`` ist der Text mit Inline-Markup (``<b>``, ``<i>``, ``<sup>``,
    ``<sub>``, ``<m>`` für Formeln, die unverändert bleiben müssen). Dieses
    Markup wird mitübersetzt, damit Fettdruck/Kursiv nach der Übersetzung an
    der richtigen Stelle landen, obwohl sich die Wortreihenfolge ändert.
    """

    id: str
    page: int
    bbox: tuple[float, float, float, float]
    line_rects: list[tuple[float, float, float, float]]
    tagged: str
    font_size: float
    color: int
    font_family: str  # "serif" | "sans-serif" | "monospace"
    align: str  # "left" | "justify" | "center"
    line_height: float  # als Vielfaches der Schriftgröße
    translation: str | None = None

    @property
    def plain(self) -> str:
        from .markup import strip_tags

        return strip_tags(self.tagged)


@dataclass
class Document:
    path: str
    page_count: int
    blocks: list[TextBlock] = field(default_factory=list)

    def blocks_on_page(self, page: int) -> list[TextBlock]:
        return [b for b in self.blocks if b.page == page]
