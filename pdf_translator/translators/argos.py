"""Offline-Übersetzung mit Argos Translate (klassische neuronale Maschinenübersetzung).

Sehr leichtgewichtig: läuft auf jedem Rechner ohne Grafikkarte, das Sprachpaket
(ca. 100 MB) wird einmalig heruntergeladen, danach ist alles offline.

Im Vergleich zum lokalen Sprachmodell (Ollama):
  * schneller und genügsamer,
  * übersetzt Satz für Satz innerhalb eines Absatzes, sieht aber keine
    Nachbarabsätze und kennt kein Glossar,
  * Fett/Kursiv innerhalb eines Absatzes geht verloren (ganze fette/kursive
    Blöcke wie Überschriften bleiben fett/kursiv); Formeln, Hoch- und
    Tiefstellungen bleiben erhalten.
"""

from __future__ import annotations

import html
import logging
import re
import threading

from ..languages import lang_code
from ..markup import escape
from .base import BatchRequest, Translator

log = logging.getLogger(__name__)

_PROTECTED_RE = re.compile(r"<m>.*?</m>|<sup>.*?</sup>|<sub>.*?</sub>", re.S)
_FORMAT_TAG_RE = re.compile(r"</?(?:b|i)>")
_WRAPPER_RE = re.compile(r"^((?:<(?:b|i)>)+)(.*?)((?:</(?:b|i)>)+)$", re.S)
_LETTER_RE = re.compile(r"[^\W\d_]")


def _placeholder(n: int) -> str:
    # Buchstaben-Ziffern-Folge, die das Modell wie einen Eigennamen unverändert lässt.
    return f"QX{n}Z"


class ArgosTranslator(Translator):
    name = "argos"
    default_batch_chars = 20000
    default_workers = 1

    def __init__(self, source_lang: str, target_lang: str):
        super().__init__(source_lang, target_lang)
        self.from_code = lang_code(source_lang)
        self.to_code = lang_code(target_lang)
        self._translation = None
        self._lock = threading.Lock()

    def prepare(self, document_text: str) -> None:
        self._load()

    def _load(self):
        if self._translation is not None:
            return self._translation
        try:
            import argostranslate.package
            import argostranslate.translate
        except ImportError as exc:
            raise RuntimeError("Argos Translate fehlt. Installation: pip install argostranslate") from exc

        installed = {lang.code for lang in argostranslate.translate.get_installed_languages()}
        if not {self.from_code, self.to_code} <= installed:
            log.warning("Lade Sprachpaket %s -> %s herunter (einmalig) …", self.from_code, self.to_code)
            argostranslate.package.update_package_index()
            if not argostranslate.package.install_package_for_language_pair(self.from_code, self.to_code):
                raise RuntimeError(f"Kein Argos-Sprachpaket für {self.from_code} -> {self.to_code} verfügbar")
        self._translation = argostranslate.translate.get_translation_from_codes(self.from_code, self.to_code)
        return self._translation

    def _plain(self, text: str) -> str:
        """Übersetzt reinen Text (ohne Markup); Text ohne Buchstaben bleibt unverändert."""
        if not _LETTER_RE.search(text):
            return text
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()) :]
        with self._lock:
            out = self._load().translate(text.strip())
        return lead + out + trail

    def translate_segment(self, tagged: str) -> str:
        # Ganzer Block fett/kursiv (z. B. Überschrift)? Dann die Hülle behalten.
        prefix = suffix = ""
        m = _WRAPPER_RE.match(tagged)
        if m and not _FORMAT_TAG_RE.search(m.group(2)):
            prefix, tagged, suffix = m.group(1), m.group(2), m.group(3)

        protected = _PROTECTED_RE.findall(tagged)
        body = _FORMAT_TAG_RE.sub("", tagged)  # Fett/Kursiv innerhalb des Absatzes entfällt

        if protected:
            masked = body
            glued = []  # stand das Element direkt am vorherigen Wort (z. B. Fußnote "word¹")?
            for n, item in enumerate(protected):
                i = masked.index(item)
                glued.append(i > 0 and not masked[i - 1].isspace())
                # Mit Leerzeichen absetzen, damit das Modell den Platzhalter als eigenes Wort sieht.
                masked = masked[:i] + f" {_placeholder(n)} " + masked[i + len(item) :]
            lead, trail = body[: len(body) - len(body.lstrip())], body[len(body.rstrip()) :]
            translated = lead + self._plain(html.unescape(re.sub(r"  +", " ", masked)).strip()) + trail
            if all(translated.count(_placeholder(n)) == 1 for n in range(len(protected))):
                for n, is_glued in enumerate(glued):
                    if is_glued:
                        translated = re.sub(r"\s+" + _placeholder(n), _placeholder(n), translated)
                out = escape(translated)
                for n, item in enumerate(protected):
                    out = out.replace(_placeholder(n), item)
            else:
                # Platzhalter nicht sauber erhalten: Textstücke zwischen den Formeln
                # einzeln übersetzen – weniger Kontext, aber garantiert korrekt.
                pieces = _PROTECTED_RE.split(body)
                out = ""
                for n, piece in enumerate(pieces):
                    out += escape(self._plain(html.unescape(piece)))
                    if n < len(protected):
                        out += protected[n]
        else:
            out = escape(self._plain(html.unescape(body)))
        return prefix + out + suffix

    def translate_batch(self, request: BatchRequest) -> dict[str, str]:
        return {s.id: self.translate_segment(s.text) for s in request.segments}
