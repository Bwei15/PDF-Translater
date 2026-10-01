"""Kontextbewusste Übersetzung mit Claude (Anthropic API).

Warum ein LLM statt Wort-für-Wort-Übersetzung?
  * Übersetzt wird immer ein ganzer Absatz – nie einzelne Wörter oder Zeilen.
  * Das Modell sieht zusätzlich die vorangehenden und folgenden Absätze, damit
    Sätze, die über Spalten- oder Seitengrenzen umbrechen, korrekt bleiben.
  * Ein einmal pro Dokument erzeugtes Glossar sorgt dafür, dass Fachbegriffe in
    langen Dokumenten überall gleich übersetzt werden.
"""

from __future__ import annotations

import json
import logging

import anthropic

from .base import BatchRequest, Translator

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}

_GLOSSARY_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string"},
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "target": {"type": "string"}},
                "required": ["source", "target"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["domain", "terms"],
    "additionalProperties": False,
}


class ClaudeTranslator(Translator):
    name = "claude"

    def __init__(
        self,
        source_lang: str,
        target_lang: str,
        model: str = DEFAULT_MODEL,
        effort: str = "high",
        use_glossary: bool = True,
        client: anthropic.Anthropic | None = None,
    ):
        super().__init__(source_lang, target_lang)
        self.model = model
        self.effort = effort
        self.use_glossary = use_glossary
        self.client = client or anthropic.Anthropic(max_retries=5)
        self.domain = ""
        self.glossary: list[dict] = []

    def cache_key(self) -> str:
        return f"{super().cache_key()}:{self.model}"

    # ------------------------------------------------------------------ API
    def _call(self, system: str, user: str, schema: dict, max_tokens: int) -> dict:
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            # Der Systemprompt ist pro Dokument stabil -> Prompt-Caching spart
            # bei langen Dokumenten einen Großteil der Eingabekosten.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Anfrage abgelehnt: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Antwort abgeschnitten (max_tokens) – Stapelgröße verkleinern")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)

    # ------------------------------------------------------------ Glossar
    def prepare(self, document_text: str) -> None:
        if not self.use_glossary or not document_text.strip():
            return
        system = (
            "You are a terminology expert preparing a professional translation "
            f"from {self.source_lang} into {self.target_lang}."
        )
        user = (
            "Read the beginning of the document below. Return (1) a one-sentence "
            "description of its domain and (2) a glossary of up to 60 recurring "
            "technical terms, names of methods and fixed expressions together with "
            f"the established {self.target_lang} translation used by experts in that "
            "field. If a term is conventionally left untranslated in the target "
            "language (e.g. an English technical term commonly used in German "
            "papers), give the term itself as the translation.\n\n"
            f"<document>\n{document_text[:60000]}\n</document>"
        )
        data = self._call(system, user, _GLOSSARY_SCHEMA, max_tokens=16000)
        self.domain = data.get("domain", "")
        self.glossary = data.get("terms", [])
        log.info("Glossar mit %d Begriffen erstellt", len(self.glossary))

    # -------------------------------------------------------- Übersetzung
    def _system_prompt(self) -> str:
        glossary = "\n".join(f"- {t['source']} → {t['target']}" for t in self.glossary)
        return f"""You are a professional translator. Translate segments of a PDF document from {self.source_lang} into {self.target_lang}.

The translated text is placed back into the PDF at exactly the position of the original, so the reader should not notice that the document was translated. Requirements:

1. Translate meaning in context, not word by word. The result must read like text originally written in {self.target_lang} by an expert of the field, in the same register and tone as the source.
2. Each segment is one text block of the page layout (usually a paragraph, heading, caption or table cell). A segment can begin or end in the middle of a sentence because the sentence continues in a neighbouring block (column or page break). Use the context to understand the full sentence, but translate only the segment itself so that the translated segments still join up naturally in reading order.
3. Inline markup must be kept: <b>, <i>, <sup>, <sub> mark formatting — place them around the corresponding translated words. <m>…</m> marks formulas and symbols: copy every <m> element exactly, character for character, never translate or change it. Keep the escaped entities &amp; &lt; &gt; as they are.
4. Keep all numbers, citation markers such as [12] or (Smith et al., 2020), references like "Fig. 3"/"Eq. (2)" (translate the word, keep the number), URLs, e-mail addresses, code and proper names. You may adapt number formatting to {self.target_lang} conventions (e.g. decimal comma), but never change a value.
5. Use the glossary for consistent terminology across the whole document.
6. Do not add explanations, do not merge or split segments, do not omit anything. If a segment is already in {self.target_lang} or must not be translated (e.g. a name, a formula label, code), return it unchanged.
7. Keep the length close to the source where the target language allows — prefer concise phrasing, because the text has to fit into the original space.

Document domain: {self.domain or "unknown"}

Glossary:
{glossary or "(none)"}

Return one entry per input segment with the same id."""

    def translate_batch(self, request: BatchRequest) -> dict[str, str]:
        payload: dict = {
            "context_before": request.context_before,
            "segments": [{"id": s.id, "text": s.text} for s in request.segments],
            "context_after": request.context_after,
        }
        note = ""
        if request.feedback:
            payload["previous_problems"] = request.feedback
            note = (
                "\nA previous attempt for some of these segments had problems (listed in "
                "previous_problems). Make sure they do not occur again."
            )
        user = (
            "Translate every entry of `segments`. `context_before`/`context_after` are the "
            "neighbouring source blocks for reference only — do not translate them."
            f"{note}\n\n{json.dumps(payload, ensure_ascii=False, indent=1)}"
        )
        # Ausgabe ~ 1,5x Eingabe (Deutsch ist länger) plus Spielraum fürs Denken.
        chars = sum(len(s.text) for s in request.segments)
        max_tokens = min(64000, 8000 + chars)
        data = self._call(self._system_prompt(), user, _TRANSLATION_SCHEMA, max_tokens=max_tokens)
        return {t["id"]: t["text"] for t in data["translations"]}
