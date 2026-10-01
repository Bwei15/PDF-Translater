"""Schnittstelle für Übersetzungs-Backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Segment:
    id: str
    text: str  # Text mit Inline-Markup


@dataclass
class BatchRequest:
    """Ein Stapel aufeinanderfolgender Absätze plus umgebender Kontext."""

    segments: list[Segment]
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)
    feedback: dict[str, list[str]] = field(default_factory=dict)  # id -> Probleme beim letzten Versuch


class Translator(ABC):
    """Ein Backend übersetzt Stapel von Absätzen und sieht dabei den Kontext.

    Eigene Backends (weitere lokale Modelle, …) implementieren nur
    ``translate_batch`` und optional ``prepare``.
    """

    name = "base"
    default_batch_chars = 6000  # Zeichen pro Anfrage
    default_workers = 4  # parallele Anfragen

    def __init__(self, source_lang: str, target_lang: str):
        self.source_lang = source_lang
        self.target_lang = target_lang

    def prepare(self, document_text: str) -> None:
        """Wird einmal pro Dokument aufgerufen (z. B. um ein Glossar zu erstellen)."""

    @abstractmethod
    def translate_batch(self, request: BatchRequest) -> dict[str, str]:
        """Gibt ein Mapping Segment-ID -> übersetzter Text (mit Markup) zurück."""

    def cache_key(self) -> str:
        """Identifiziert die Konfiguration für den Übersetzungs-Cache."""
        return f"{self.name}:{self.source_lang}:{self.target_lang}"
