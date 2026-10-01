"""Gesamtablauf: PDF extrahieren -> im Kontext übersetzen -> prüfen -> rendern."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .cache import TranslationCache
from .extract import extract_document
from .markup import check_translation, escape, is_well_formed, strip_tags
from .models import Document, TextBlock
from .render import render_document
from .translators.base import BatchRequest, Segment, Translator

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]  # (Phase, Fortschritt 0..1)


@dataclass
class TranslationResult:
    output_path: str
    blocks_total: int
    blocks_translated: int
    blocks_from_cache: int
    warnings: list[str] = field(default_factory=list)


def _make_batches(blocks: list[TextBlock], max_chars: int, max_segments: int) -> list[list[int]]:
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for i, block in enumerate(blocks):
        n = len(block.tagged)
        if current and (size + n > max_chars or len(current) >= max_segments):
            batches.append(current)
            current, size = [], 0
        current.append(i)
        size += n
    if current:
        batches.append(current)
    return batches


def _translate_with_checks(
    translator: Translator, request: BatchRequest, retries: int
) -> tuple[dict[str, str], list[str]]:
    """Übersetzt einen Stapel und lässt fehlerhafte Segmente gezielt neu übersetzen."""
    by_id = {s.id: s for s in request.segments}
    result: dict[str, str] = {}
    problems: dict[str, list[str]] = {}
    pending = request

    for attempt in range(retries + 1):
        try:
            out = translator.translate_batch(pending)
        except Exception as exc:  # Netzwerk/API: nach Retries des SDKs
            if attempt == retries:
                raise
            log.warning("Stapel fehlgeschlagen (%s), neuer Versuch", exc)
            continue
        problems = {}
        for seg in pending.segments:
            text = out.get(seg.id)
            issues = ["Segment fehlt in der Antwort"] if text is None else check_translation(seg.text, text)
            if text is not None:
                result[seg.id] = text
            if issues:
                problems[seg.id] = issues
        if not problems:
            break
        pending = BatchRequest(
            segments=[by_id[i] for i in problems],
            context_before=request.context_before,
            context_after=request.context_after,
            feedback=problems,
        )

    warnings = []
    for seg_id, issues in problems.items():
        text = result.get(seg_id)
        if text is None:
            result[seg_id] = by_id[seg_id].text  # lieber Original als nichts
        elif not is_well_formed(text):
            result[seg_id] = escape(strip_tags(text))
        warnings.append(f"Block {seg_id}: {'; '.join(issues)}")
    return result, warnings


def translate_document(
    document: Document,
    translator: Translator,
    cache: TranslationCache | None = None,
    batch_chars: int | None = None,
    batch_segments: int = 40,
    context_blocks: int = 2,
    workers: int | None = None,
    retries: int = 1,
    progress: ProgressCallback | None = None,
) -> tuple[int, list[str]]:
    """Füllt ``block.translation`` für alle Blöcke. Gibt (aus Cache, Warnungen) zurück."""
    progress = progress or (lambda phase, frac: None)
    cache = cache or TranslationCache(None)
    batch_chars = batch_chars or translator.default_batch_chars
    workers = workers or translator.default_workers
    ns = translator.cache_key()
    blocks = document.blocks

    from_cache = 0
    todo: list[int] = []
    for i, block in enumerate(blocks):
        cached = cache.get(ns, block.tagged)
        if cached is not None:
            block.translation = cached
            from_cache += 1
        else:
            todo.append(i)

    if not todo:
        progress("Übersetzung", 1.0)
        return from_cache, []

    progress("Glossar", 0.0)
    translator.prepare("\n\n".join(b.plain for b in blocks))

    todo_blocks = [blocks[i] for i in todo]
    batches = _make_batches(todo_blocks, batch_chars, batch_segments)
    requests = []
    for batch in batches:
        first, last = todo[batch[0]], todo[batch[-1]]
        requests.append(
            BatchRequest(
                segments=[Segment(blocks[todo[j]].id, blocks[todo[j]].tagged) for j in batch],
                context_before=[b.plain for b in blocks[max(0, first - context_blocks) : first]],
                context_after=[b.plain for b in blocks[last + 1 : last + 1 + context_blocks]],
            )
        )

    by_id = {b.id: b for b in blocks}
    warnings: list[str] = []
    done = 0
    progress("Übersetzung", 0.0)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_translate_with_checks, translator, r, retries) for r in requests]
        for fut in as_completed(futures):
            translations, batch_warnings = fut.result()
            warnings.extend(batch_warnings)
            for seg_id, text in translations.items():
                block = by_id[seg_id]
                block.translation = text
                if not any(w.startswith(f"Block {seg_id}:") for w in batch_warnings):
                    cache.put(ns, block.tagged, text)
            done += 1
            progress("Übersetzung", done / len(requests))
    return from_cache, warnings


def translate_pdf(
    input_path: str,
    output_path: str,
    translator: Translator,
    cache_path: str | None = None,
    fonts: dict[str, str] | None = None,
    progress: ProgressCallback | None = None,
    **kwargs,
) -> TranslationResult:
    """Übersetzt ``input_path`` und schreibt das Ergebnis nach ``output_path``."""
    progress = progress or (lambda phase, frac: None)
    progress("Analyse", 0.0)
    document = extract_document(input_path)
    log.info("%d Seiten, %d Textblöcke", document.page_count, len(document.blocks))

    cache = TranslationCache(cache_path)
    try:
        from_cache, warnings = translate_document(document, translator, cache, progress=progress, **kwargs)
    finally:
        cache.close()

    progress("PDF erstellen", 0.0)
    warnings += render_document(document, output_path, fonts=fonts)
    progress("Fertig", 1.0)
    return TranslationResult(
        output_path=output_path,
        blocks_total=len(document.blocks),
        blocks_translated=sum(1 for b in document.blocks if b.translation),
        blocks_from_cache=from_cache,
        warnings=warnings,
    )
