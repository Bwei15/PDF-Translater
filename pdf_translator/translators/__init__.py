from .base import BatchRequest, Segment, Translator
from .pseudo import PseudoTranslator


def get_translator(name: str, source_lang: str, target_lang: str, **kwargs) -> Translator:
    """Erzeugt ein Übersetzungs-Backend anhand seines Namens."""
    if name == "claude":
        from .claude import ClaudeTranslator

        return ClaudeTranslator(source_lang, target_lang, **kwargs)
    if name == "pseudo":
        return PseudoTranslator(source_lang, target_lang)
    raise ValueError(f"Unbekanntes Backend: {name}")


__all__ = ["BatchRequest", "Segment", "Translator", "PseudoTranslator", "get_translator"]
