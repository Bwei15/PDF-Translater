"""Lokale Weboberfläche: PDF hochladen, Fortschritt verfolgen, Übersetzung herunterladen.

Start:  python webapp/app.py   ->  http://127.0.0.1:5000
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import traceback
import uuid

from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf_translator import get_translator, lang_suffix, translate_pdf  # noqa: E402
from pdf_translator.translators import BACKENDS  # noqa: E402
from pdf_translator.translators.ollama import DEFAULT_MODEL, OllamaTranslator  # noqa: E402

LANGUAGES = ["German", "English", "French", "Spanish", "Italian", "Portuguese", "Dutch",
             "Polish", "Czech", "Swedish", "Turkish", "Russian", "Ukrainian", "Chinese", "Japanese", "Korean"]

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
WORK_DIR = os.environ.get("PDF_TRANSLATOR_WORKDIR", os.path.join(tempfile.gettempdir(), "pdf_translator"))
CACHE_PATH = os.path.join(WORK_DIR, "cache.sqlite")
os.makedirs(WORK_DIR, exist_ok=True)

jobs: dict[str, dict] = {}


def _run(job_id: str, src: str, dst: str, backend: str, source: str, target: str, model: str) -> None:
    job = jobs[job_id]

    def progress(phase: str, frac: float) -> None:
        job.update(phase=phase, progress=frac)

    try:
        kwargs = {"model": model} if backend == "ollama" and model else {}
        translator = get_translator(backend, source, target, **kwargs)
        result = translate_pdf(src, dst, translator, cache_path=CACHE_PATH, progress=progress)
        job.update(status="done", warnings=result.warnings,
                   summary=f"{result.blocks_translated}/{result.blocks_total} Textblöcke übersetzt "
                           f"({result.blocks_from_cache} aus dem Cache)")
    except RuntimeError as exc:  # erwartete Fehler (Ollama/Modell fehlt): im Browser anzeigen
        job.update(status="error", error=str(exc))
    except Exception as exc:
        traceback.print_exc()
        job.update(status="error", error=str(exc))


@app.get("/")
def index():
    return render_template("index.html", languages=LANGUAGES, default_model=DEFAULT_MODEL)


@app.get("/models")
def models():
    """Lokal in Ollama installierte Modelle (leer, wenn Ollama nicht läuft)."""
    try:
        tags = OllamaTranslator("English", "German", timeout=3)._request("/api/tags")
        return jsonify(models=sorted(m["name"] for m in tags.get("models", [])))
    except RuntimeError:
        return jsonify(models=[])


@app.post("/translate")
def translate():
    file = request.files.get("pdf")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify(error="Bitte eine PDF-Datei auswählen."), 400
    job_id = uuid.uuid4().hex
    name = secure_filename(file.filename) or "dokument.pdf"
    src = os.path.join(WORK_DIR, f"{job_id}_{name}")
    target = request.form.get("target", "German")
    dst = os.path.join(WORK_DIR, f"{job_id}_{os.path.splitext(name)[0]}.{lang_suffix(target)}.pdf")
    file.save(src)
    jobs[job_id] = {"status": "running", "phase": "Warteschlange", "progress": 0.0,
                    "output": dst, "download_name": os.path.basename(dst).split("_", 1)[1]}
    backend = request.form.get("backend", "ollama")
    if backend not in BACKENDS:
        return jsonify(error="Unbekanntes Backend."), 400
    args = (job_id, src, dst, backend, request.form.get("source", "English"),
            target, request.form.get("model", "").strip())
    threading.Thread(target=_run, args=args, daemon=True).start()
    return jsonify(job_id=job_id)


@app.get("/status/<job_id>")
def status(job_id: str):
    job = jobs.get(job_id) or abort(404)
    return jsonify({k: v for k, v in job.items() if k != "output"})


@app.get("/download/<job_id>")
def download(job_id: str):
    job = jobs.get(job_id) or abort(404)
    if job["status"] != "done":
        abort(409)
    inline = request.args.get("view") == "1"
    return send_file(job["output"], mimetype="application/pdf", as_attachment=not inline,
                     download_name=job["download_name"])


if __name__ == "__main__":
    # Nur lokal erreichbar.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
