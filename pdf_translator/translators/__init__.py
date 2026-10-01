from .base import BatchRequest, Segment, Translator
from .pseudo import PseudoTranslator

BACKENDS = ("ollama", "argos", "pseudo")


def get_translator(name: str, source_lang: str, target_lang: str, **kwargs) -> Translator:
    """Erzeugt ein Übersetzungs-Backend anhand seines Namens. Alle laufen lokal."""
    if name == "ollama":
        from .ollama import OllamaTranslator

        return OllamaTranslator(source_lang, target_lang, **kwargs)
    if name == "argos":
        from .argos import ArgosTranslator

        return ArgosTranslator(source_lang, target_lang)
    if name == "pseudo":
        return PseudoTranslator(source_lang, target_lang)
    raise ValueError(f"Unbekanntes Backend: {name}")


__all__ = ["BACKENDS", "BatchRequest", "Segment", "Translator", "PseudoTranslator", "get_translator"]
