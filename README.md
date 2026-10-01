# PDF-Translater

Übersetzt PDF-Dokumente in eine andere Sprache. Layout, Bilder, Grafiken, Formeln und Farben bleiben erhalten:
Nur der Text wird ausgetauscht, und zwar an genau der Stelle, an der er im Original steht.

**Alles läuft lokal auf dem eigenen Rechner.** Es wird kein Cloud-Dienst genutzt, und das Dokument verlässt den PC nicht.

* **Übersetzung im Kontext statt Wort für Wort.** Übersetzt wird immer ein ganzer Absatz. Das lokale Sprachmodell sieht
  zusätzlich die Nachbarabsätze, damit Sätze, die über Spalten- oder Seitengrenzen laufen, korrekt bleiben.
* **Einheitliche Fachbegriffe in langen Dokumenten.** Vorab wird ein Glossar der Fachbegriffe erstellt, und jeder Abschnitt
  wird damit übersetzt.
* **Geprüfte Übersetzungen.** Jede Übersetzung wird automatisch kontrolliert: Formeln müssen identisch bleiben,
  Zahlen und Zitate wie `[12]` dürfen nicht fehlen, und die Formatierung muss stimmen. Fehlerhafte Absätze werden mit
  einer Rückmeldung neu übersetzt. Was danach noch auffällt, steht als Hinweis im Ergebnis.
* **Lange Dokumente.** Ein Cache speichert jeden fertigen Absatz. Ein abgebrochener Lauf macht dort weiter, wo er
  aufgehört hat.

## Übersetzungs-Backends

| Backend | Was | Qualität | Hardware |
|---|---|---|---|
| `ollama` (Standard) | Lokales Sprachmodell über [Ollama](https://ollama.com), z. B. Gemma 3 | Beste Qualität: Absatzkontext, Glossar, Formatierung bleibt | Ideal mit Grafikkarte, geht aber auch ohne (dann langsam) |
| `argos` | [Argos Translate](https://github.com/argosopentech/argos-translate), klassische Offline-Übersetzung | Gut, aber Satz für Satz: ohne Nachbarkontext und Glossar, Fett/Kursiv im Fließtext geht verloren | Jeder Rechner, schnell |
| `pseudo` | Verfremdet nur die Wörter | – | Zum Testen des Layouts |

### Welches Modell für welchen Rechner?

| Modell | Download | Empfohlen für |
|---|---|---|
| `gemma3:4b` | ca. 3 GB | Laptops ohne Grafikkarte, 8 GB RAM |
| `gemma3:12b` (Standard) | ca. 8 GB | 16 GB RAM, oder eine Grafikkarte mit mind. 8 GB |
| `gemma3:27b` | ca. 17 GB | Grafikkarte mit mind. 16–24 GB, oder Apple Silicon mit 32 GB |

Andere Modelle wie `qwen3`, `mistral-small` oder `llama3.1` funktionieren ebenfalls (`--model ...`).

Grobe Dauer für ein Dokument mit 126 Seiten. Das sind Schätzungen, die stark von der Hardware abhängen:
mit Grafikkarte und `gemma3:12b` etwa 1–2 Stunden, nur mit dem Prozessor eher mehrere Stunden bis über Nacht.
`argos` braucht deutlich weniger. Dank Cache kann man jederzeit abbrechen und später weitermachen.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Für das lokale Sprachmodell (empfohlen):**
1. Ollama installieren: https://ollama.com/download. Das Programm startet danach im Hintergrund.
2. Ein Modell einmalig herunterladen:
   ```bash
   ollama pull gemma3:12b
   ```

**Für Argos (leichte Alternative):**
```bash
pip install argostranslate
```
Das Sprachpaket (ca. 100 MB) wird beim ersten Lauf automatisch geladen. Danach läuft alles offline.

## Nutzung

### Weboberfläche

```bash
python webapp/app.py
```

Dann http://127.0.0.1:5000 öffnen und das PDF hineinziehen. Sprachen, Backend und Modell auswählen (die installierten
Ollama-Modelle werden vorgeschlagen). Danach auf „Übersetzen“ klicken und das Ergebnis ansehen oder herunterladen.
Die Oberfläche ist nur auf dem eigenen Rechner erreichbar.

### Kommandozeile

```bash
python -m pdf_translator paper.pdf                       # Englisch -> Deutsch mit gemma3:12b, ergibt paper.de.pdf
python -m pdf_translator paper.pdf -m gemma3:4b          # kleineres Modell für schwächere PCs
python -m pdf_translator paper.pdf -b argos              # leichte Offline-Übersetzung
python -m pdf_translator paper.pdf -b pseudo             # nur Layout testen
python -m pdf_translator paper.pdf -t French -o paper_fr.pdf
```

Weitere Optionen: `--no-glossary`, `--ollama-url`, `--workers`, `--batch-chars`, `--cache` und `--font` (siehe unten).
`python -m pdf_translator -h` zeigt alle.

### Als Bibliothek

```python
from pdf_translator import get_translator, translate_pdf

translator = get_translator("ollama", "English", "German", model="gemma3:12b")
result = translate_pdf("paper.pdf", "paper.de.pdf", translator, cache_path="paper.cache.sqlite")
print(result.warnings)
```

Ein eigenes Backend erbt von `Translator` und implementiert `translate_batch`.

## Funktionsweise

```
PDF ──► extract.py ──► Absätze mit Position, Schrift, Größe, Farbe, Ausrichtung
                         (Bilder, Formeln, Seitenzahlen, gedrehter Text werden übersprungen)
     ──► pipeline.py ──► Glossar ► Stapel mit Kontext ► lokales Modell ► Prüfung ► ggf. Nachbesserung ► Cache
     ──► render.py ───► Originaltext entfernen (Bilder/Grafik unangetastet, nichts übermalt)
                         ► Übersetzung in dieselbe Box setzen (nutzt freien Platz, verkleinert nur wenn nötig)
```

| Modul | Aufgabe |
|---|---|
| `pdf_translator/extract.py` | Textblöcke mit Layout-Informationen aus dem PDF lesen (PyMuPDF) |
| `pdf_translator/markup.py` | Inline-Markup (`<b> <i> <sup> <sub> <m>`) und Prüfregeln |
| `pdf_translator/translators/` | Backends: `ollama`, `argos`, `pseudo` |
| `pdf_translator/pipeline.py` | Ablaufsteuerung: Stapel, Kontext, Prüfung, Cache |
| `pdf_translator/render.py` | Übersetzten Text an die Originalposition schreiben |
| `webapp/` | Lokale Weboberfläche (Flask) |

## Tipps für LaTeX-Dokumente

Die Originalschriften im PDF sind meist nur teilweise eingebettet (Subset), deshalb fehlen ihnen oft Zeichen wie ä, ö,
ü und ß. Standardmäßig wird darum eine Unicode-Serifenschrift verwendet. Mit der Schrift „Latin Modern“ (der LaTeX-Standardlook,
frei verfügbar unter https://www.gust.org.pl/projects/e-foundry/latin-modern) fällt die Übersetzung optisch kaum auf:

```bash
python -m pdf_translator paper.pdf --font regular=lmroman10-regular.otf bold=lmroman10-bold.otf \
    italic=lmroman10-italic.otf bolditalic=lmroman10-bolditalic.otf
```

## Grenzen

* Gescannte PDFs (Bilder ohne Textebene) brauchen vorher eine OCR, z. B. `ocrmypdf`.
* Abgesetzte Formeln bleiben unverändert. Inline-Formeln werden erhalten, aber mit der Ersatzschrift gesetzt.
* Text in Vektorgrafiken (Achsenbeschriftungen) wird übersetzt, wenn er als Text vorliegt. Text in Pixelbildern nicht.
* Deutsch ist ca. 20–30 % länger als Englisch. Der Text nutzt zuerst freien Platz in der Nähe und wird nur wenn nötig
  leicht verkleinert. Stark verkleinerte Blöcke erscheinen als Hinweis.
* Lokale Modelle sind kleiner als große Cloud-Modelle. Größere Modelle (`gemma3:27b`) übersetzen spürbar besser als
  kleine (`gemma3:4b`).

## Tests

```bash
python -m pytest tests
```

Die Tests laufen offline und ohne Modell. Ollama und Argos werden dabei simuliert.
