"""pdf_translator – PDFs übersetzen, ohne das Layout zu verändern."""

from .extract import extract_document
from .pipeline import TranslationResult, translate_document, translate_pdf
from .render import render_document
from .translators import Translator, get_translator

__all__ = [
    "extract_document",
    "translate_document",
    "translate_pdf",
    "render_document",
    "TranslationResult",
    "Translator",
    "get_translator",
]

_LANG_CODES = {
    "german": "de", "deutsch": "de", "english": "en", "french": "fr", "spanish": "es", "italian": "it",
    "portuguese": "pt", "dutch": "nl", "polish": "pl", "czech": "cs", "swedish": "sv", "turkish": "tr",
    "russian": "ru", "ukrainian": "uk", "chinese": "zh", "japanese": "ja", "korean": "ko",
}


def lang_suffix(language: str) -> str:
    """'German' -> 'de' (für Dateinamen wie dokument.de.pdf)."""
    return _LANG_CODES.get(language.lower(), language.lower()[:2])
