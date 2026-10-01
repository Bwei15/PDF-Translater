"""Sprachnamen <-> ISO-Codes."""

LANG_CODES = {
    "german": "de", "deutsch": "de", "english": "en", "englisch": "en", "french": "fr", "spanish": "es",
    "italian": "it", "portuguese": "pt", "dutch": "nl", "polish": "pl", "czech": "cs", "swedish": "sv",
    "turkish": "tr", "russian": "ru", "ukrainian": "uk", "chinese": "zh", "japanese": "ja", "korean": "ko",
}


def lang_code(language: str) -> str:
    """'German' -> 'de'; ISO-Codes werden unverändert übernommen."""
    lang = language.strip().lower()
    return LANG_CODES.get(lang, lang[:2])
