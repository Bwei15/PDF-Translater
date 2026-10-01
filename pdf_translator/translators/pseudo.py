"""Offline-Pseudoübersetzung zum Testen von Layout und Pipeline ohne API-Key.

Markiert jedes Wort und verlängert den Text um ca. 30 % (typisch für EN -> DE),
erhält dabei Markup, Formeln und Zahlen.
"""

from __future__ import annotations

import re

from .base import BatchRequest, Translator

_TOKEN_RE = re.compile(r"(<m>.*?</m>|</?\w+>|&\w+;|\s+)", re.S)


class PseudoTranslator(Translator):
    name = "pseudo"

    def _pseudo(self, tagged: str) -> str:
        out = []
        for tok in _TOKEN_RE.split(tagged):
            word = re.fullmatch(r"([A-Za-z]{4,})(\W*)", tok) if tok else None
            if word:
                w, punct = word.groups()
                out.append(w.replace("e", "ë").replace("a", "ä") + w[-2:] + punct)
            else:
                out.append(tok)
        return "".join(out)

    def translate_batch(self, request: BatchRequest) -> dict[str, str]:
        return {s.id: self._pseudo(s.text) for s in request.segments}
