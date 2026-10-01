"""Kommandozeile: python -m pdf_translator dokument.pdf -t Deutsch"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import lang_suffix
from .pipeline import translate_pdf
from .translators import BACKENDS, get_translator


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pdf_translator", description="PDF übersetzen, Layout und Bilder bleiben erhalten.")
    p.add_argument("input", help="Eingabe-PDF")
    p.add_argument("-o", "--output", help="Ausgabe-PDF (Standard: <name>.<ziel>.pdf)")
    p.add_argument("-s", "--source", default="English", help="Ausgangssprache (Standard: English)")
    p.add_argument("-t", "--target", default="German", help="Zielsprache (Standard: German)")
    p.add_argument("-b", "--backend", default="ollama", choices=list(BACKENDS),
                   help="ollama = lokales Sprachmodell (Standard, beste Qualität), "
                        "argos = leichte Offline-Übersetzung, pseudo = Layout-Test")
    p.add_argument("-m", "--model", default=None,
                   help="Ollama-Modell (Standard: gemma3:12b; schwächere PCs: gemma3:4b, starke: gemma3:27b)")
    p.add_argument("--ollama-url", default=None, help="Adresse des Ollama-Servers (Standard: http://localhost:11434)")
    p.add_argument("--no-glossary", action="store_true", help="Kein Fachbegriff-Glossar vorab erstellen")
    p.add_argument("--workers", type=int, default=None, help="Parallele Anfragen (Standard je nach Backend)")
    p.add_argument("--batch-chars", type=int, default=None, help="Zeichen pro Anfrage (Standard je nach Backend)")
    p.add_argument("--cache", default=None, help="Cache-Datei (Standard: <name>.cache.sqlite neben der Eingabe)")
    p.add_argument("--font", nargs="+", metavar="ART=DATEI",
                   help="Eigene Schrift, z. B. regular=lmroman10-regular.otf bold=lmroman10-bold.otf "
                        "italic=lmroman10-italic.otf bolditalic=lmroman10-bolditalic.otf")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    base, _ = os.path.splitext(args.input)
    output = args.output or f"{base}.{lang_suffix(args.target)}.pdf"
    cache = args.cache or f"{base}.cache.sqlite"
    fonts = dict(f.split("=", 1) for f in args.font) if args.font else None

    kwargs = {}
    if args.backend == "ollama":
        if args.model:
            kwargs["model"] = args.model
        if args.ollama_url:
            kwargs["url"] = args.ollama_url
        kwargs["use_glossary"] = not args.no_glossary
    translator = get_translator(args.backend, args.source, args.target, **kwargs)

    last = {"phase": None}

    def progress(phase: str, frac: float) -> None:
        if phase != last["phase"]:
            print(file=sys.stderr)
            last["phase"] = phase
        print(f"\r{phase}: {frac:5.0%}", end="", file=sys.stderr, flush=True)

    try:
        result = translate_pdf(
            args.input, output, translator, cache_path=cache, fonts=fonts, progress=progress,
            workers=args.workers, batch_chars=args.batch_chars,
        )
    except RuntimeError as exc:
        print(f"\nFehler: {exc}", file=sys.stderr)
        return 1
    print(file=sys.stderr)
    print(f"Fertig: {result.output_path}")
    print(f"  {result.blocks_translated}/{result.blocks_total} Blöcke übersetzt "
          f"({result.blocks_from_cache} aus dem Cache)")
    if result.warnings:
        print(f"  {len(result.warnings)} Hinweise:")
        for w in result.warnings:
            print(f"   - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
