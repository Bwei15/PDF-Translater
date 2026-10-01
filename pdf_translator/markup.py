"""Inline-Markup zwischen PDF-Spans, Übersetzer und HTML-Rendering.

Erlaubte Tags: <b> <i> <sup> <sub> <m>. ``<m>`` umschließt Formeln/Symbole,
die wortgleich erhalten bleiben müssen. Text ist XML-escaped (&amp; &lt; &gt;).
"""

from __future__ import annotations

import html
import re
from collections import Counter

ALLOWED_TAGS = ("b", "i", "sup", "sub", "m")
_TAG_RE = re.compile(r"</?(%s)>" % "|".join(ALLOWED_TAGS))
_ANY_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_MATH_RE = re.compile(r"<m>(.*?)</m>", re.S)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def escape(text: str) -> str:
    return html.escape(text, quote=False)


def strip_tags(tagged: str) -> str:
    return html.unescape(_ANY_TAG_RE.sub("", tagged))


def is_well_formed(tagged: str) -> bool:
    """Prüft, dass nur erlaubte Tags vorkommen und sie korrekt verschachtelt sind."""
    stack: list[str] = []
    for m in _ANY_TAG_RE.finditer(tagged):
        tag = m.group(0)
        if not _TAG_RE.fullmatch(tag):
            return False
        name = tag.strip("</>")
        if tag.startswith("</"):
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


def check_translation(source: str, target: str) -> list[str]:
    """Sicherheitsprüfungen einer Übersetzung. Gibt eine Liste von Problemen zurück.

    - Markup muss wohlgeformt sein.
    - Formeln (<m>…</m>) müssen exakt erhalten bleiben.
    - Alle Zahlen (Werte, Jahreszahlen, Zitationen wie [12]) müssen erhalten bleiben.
    - Die Übersetzung darf nicht leer sein.
    """
    problems = []
    if not strip_tags(target).strip():
        problems.append("leere Übersetzung")
    if not is_well_formed(target):
        problems.append("Markup nicht wohlgeformt")
    if Counter(_MATH_RE.findall(source)) != Counter(_MATH_RE.findall(target)):
        problems.append("Formeln (<m>) verändert")
    src_nums = Counter(n.replace(",", ".") for n in _NUMBER_RE.findall(strip_tags(source)))
    tgt_nums = Counter(n.replace(",", ".") for n in _NUMBER_RE.findall(strip_tags(target)))
    if src_nums != tgt_nums:
        missing = src_nums - tgt_nums
        extra = tgt_nums - src_nums
        problems.append(f"Zahlen abweichend (fehlend: {dict(missing)}, zusätzlich: {dict(extra)})")
    return problems


def to_html(tagged: str) -> str:
    """Wandelt das Inline-Markup in HTML für ``Page.insert_htmlbox`` um."""
    if not is_well_formed(tagged):
        return escape(strip_tags(tagged))
    out = tagged.replace("<m>", '<span class="m">').replace("</m>", "</span>")
    return out
