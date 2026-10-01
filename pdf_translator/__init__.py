"""pdf_translator – PDFs übersetzen, ohne das Layout zu verändern."""

from .extract import extract_document
from .languages import lang_code
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
    "lang_code",
    "lang_suffix",
]

lang_suffix = lang_code  # Dateiendung, z. B. dokument.de.pdf

