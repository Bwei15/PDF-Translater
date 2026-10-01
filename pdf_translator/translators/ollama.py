"""Kontextbewusste Übersetzung mit einem lokalen Sprachmodell über Ollama.

Alles läuft auf dem eigenen Rechner – keine Cloud, keine Daten verlassen den PC.
Installation: https://ollama.com, danach z. B. ``ollama pull gemma3:12b``.

Warum ein Sprachmodell statt Wort-für-Wort-Übersetzung?
  * Übersetzt wird immer ein ganzer Absatz – nie einzelne Wörter oder Zeilen.
  * Das Modell sieht zusätzlich die vorangehenden und folgenden Absätze, damit
    Sätze, die über Spalten- oder Seitengrenzen umbrechen, korrekt bleiben.
  * Ein einmal pro Dokument erzeugtes Glossar sorgt dafür, dass Fachbegriffe in
    langen Dokumenten überall gleich übersetzt werden.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .base import BatchRequest, Translator

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemma3:12b"
DEFAULT_URL = "http://localhost:11434"

_TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"],
            },
        }
    },
    "required": ["translations"],
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
            },
        },
    },
    "required": ["domain", "terms"],
}


class OllamaTranslator(Translator):
    name = "ollama"
    # Lokale Modelle haben weniger Kontext und Rechenleistung: kleinere Stapel,
    # eine Anfrage nach der anderen.
    default_batch_chars = 2500
    default_workers = 1

    def __init__(
        self,
        source_lang: str,
        target_lang: str,
        model: str = DEFAULT_MODEL,
        url: str = DEFAULT_URL,
        use_glossary: bool = True,
        num_ctx: int = 16384,
        timeout: float = 1800,
    ):
        super().__init__(source_lang, target_lang)
        self.model = model
        self.url = url.rstrip("/")
        self.use_glossary = use_glossary
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.domain = ""
        self.glossary: list[dict] = []

    def cache_key(self) -> str:
        return f"{super().cache_key()}:{self.model}"

    # ----------------------------------------------------------- Ollama-API
    def _request(self, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.url + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            if exc.code == 404:
                raise RuntimeError(
                    f"Modell '{self.model}' ist nicht installiert. Bitte zuerst ausführen: ollama pull {self.model}"
                ) from exc
            raise RuntimeError(f"Ollama-Fehler {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama ist unter {self.url} nicht erreichbar. Ist Ollama installiert und gestartet "
                "(https://ollama.com, Befehl: ollama serve)?"
            ) from exc

    def check_model(self) -> None:
        """Prüft vorab, ob Ollama läuft und das Modell vorhanden ist."""
        names = {m["name"] for m in self._request("/api/tags").get("models", [])}
        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        if wanted not in names:
            raise RuntimeError(
                f"Modell '{self.model}' ist nicht installiert. Bitte zuerst ausführen: ollama pull {self.model}"
            )

    def _chat(self, system: str, user: str, schema: dict) -> dict:
        resp = self._request(
            "/api/chat",
            {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "stream": False,
                "format": schema,  # erzwingt gültiges JSON nach Schema
                "options": {"temperature": 0, "num_ctx": self.num_ctx},
                "keep_alive": "30m",
            },
        )
        content = resp.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ungültige Antwort des Modells: {content[:200]}") from exc

    # ------------------------------------------------------------ Glossar
    def prepare(self, document_text: str) -> None:
        self.check_model()
        if not self.use_glossary or not document_text.strip():
            return
        system = (
            "You are a terminology expert preparing a professional translation "
            f"from {self.source_lang} into {self.target_lang}. Answer in JSON."
        )
        user = (
            "Read the beginning of the document below. Return (1) `domain`: a one-sentence "
            "description of its subject and (2) `terms`: a glossary of up to 40 recurring "
            "technical terms and fixed expressions with the established "
            f"{self.target_lang} translation used by experts in that field. If a term is "
            "conventionally left untranslated in the target language, give the term itself "
            f"as the translation.\n\n<document>\n{document_text[:12000]}\n</document>"
        )
        try:
            data = self._chat(system, user, _GLOSSARY_SCHEMA)
        except RuntimeError as exc:  # Glossar ist hilfreich, aber nicht zwingend
            log.warning("Glossar konnte nicht erstellt werden: %s", exc)
            return
        self.domain = str(data.get("domain", ""))
        self.glossary = [t for t in data.get("terms", []) if t.get("source") and t.get("target")]
        log.info("Glossar mit %d Begriffen erstellt", len(self.glossary))

    # -------------------------------------------------------- Übersetzung
    def _system_prompt(self) -> str:
        glossary = "\n".join(f"- {t['source']} → {t['target']}" for t in self.glossary)
        return f"""You are a professional translator. Translate segments of a PDF document from {self.source_lang} into {self.target_lang}.

The translated text is placed back into the PDF at exactly the position of the original, so the reader should not notice that the document was translated. Rules:

1. Translate meaning in context, not word by word. The result must read like text originally written in {self.target_lang} by an expert of the field, in the same register and tone.
2. Each segment is one text block of the page layout (paragraph, heading, caption or table cell). A segment can begin or end in the middle of a sentence because the sentence continues in a neighbouring block. Use the context to understand the full sentence, but translate only the segment itself.
3. Keep the inline markup: <b>, <i>, <sup>, <sub> mark formatting — put them around the corresponding translated words. <m>…</m> marks formulas: copy every <m> element exactly, never change it. Keep &amp; &lt; &gt; as they are.
4. Keep all numbers, citation markers such as [12] or (Smith et al., 2020), URLs, code and proper names. "Fig. 3"/"Eq. (2)": translate the word, keep the number. Never change a value.
5. Use the glossary for consistent terminology.
6. Do not add explanations, do not merge or split segments, do not omit anything. If a segment needs no translation (name, formula label, code), return it unchanged.
7. Keep the length close to the source — prefer concise phrasing, because the text has to fit into the original space.

Document domain: {self.domain or "unknown"}

Glossary:
{glossary or "(none)"}

Answer in JSON: {{"translations": [{{"id": "<segment id>", "text": "<translation>"}}, ...]}} with exactly one entry per input segment and the same ids."""

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
                "\nA previous attempt for these segments had problems (listed in "
                "previous_problems). Make sure they do not occur again."
            )
        user = (
            "Translate every entry of `segments`. `context_before`/`context_after` are the "
            "neighbouring source blocks for reference only — do not translate them."
            f"{note}\n\n{json.dumps(payload, ensure_ascii=False, indent=1)}"
        )
        data = self._chat(self._system_prompt(), user, _TRANSLATION_SCHEMA)
        return {str(t["id"]): str(t["text"]) for t in data.get("translations", []) if "id" in t and "text" in t}
