# PDF-Translater

Übersetzt PDF-Dokumente in eine andere Sprache. Layout, Bilder, Grafiken, Formeln und Farben bleiben erhalten:
Nur der Text wird ausgetauscht, und zwar an genau der Stelle, an der er im Original steht.

* **Übersetzung im Kontext statt Wort für Wort.** Übersetzt wird immer ein ganzer Absatz. Das Modell sieht zusätzlich
  die Nachbarabsätze, damit Sätze, die über Spalten- oder Seitengrenzen laufen, korrekt bleiben.
* **Einheitliche Fachbegriffe in langen Dokumenten.** Vorab wird ein Glossar der Fachbegriffe erstellt, und jeder Abschnitt
  wird damit übersetzt.
* **Geprüfte Übersetzungen.** Jede Übersetzung wird automatisch kontrolliert: Formeln müssen identisch bleiben,
  Zahlen und Zitate wie `[12]` dürfen nicht fehlen, und die Formatierung muss stimmen. Fehlerhafte Absätze werden mit
  einer Rückmeldung neu übersetzt. Was danach noch auffällt, steht als Hinweis im Ergebnis.
* **Lange Dokumente.** Mehrere Anfragen laufen parallel. Ein SQLite-Cache sorgt dafür, dass ein abgebrochener Lauf
  dort weitermacht, wo er aufgehört hat.
* **Formatierung bleibt erhalten.** *Kursiv*, **fett**, Hochstellungen und Inline-Formeln werden als Markup mitübersetzt.
  So landen sie auch bei geänderter Wortstellung an der richtigen Stelle.

## Funktionsweise

```
PDF ──► extract.py ──► Absätze mit Position, Schrift, Größe, Farbe, Ausrichtung
                         (Bilder, Formeln, Seitenzahlen, gedrehter Text werden übersprungen)
     ──► pipeline.py ──► Glossar ► Stapel mit Kontext ► Übersetzer ► Prüfung ► ggf. Nachbesserung ► Cache
     ──► render.py ───► Originaltext entfernen (Bilder/Grafik unangetastet, nichts übermalt)
                         ► Übersetzung in dieselbe Box setzen (nutzt freien Platz, verkleinert nur wenn nötig)
```

| Modul | Aufgabe |
|---|---|
| `pdf_translator/extract.py` | Textblöcke mit Layout-Informationen aus dem PDF lesen (PyMuPDF) |
| `pdf_translator/markup.py` | Inline-Markup (`<b> <i> <sup> <sub> <m>`) und Prüfregeln |
| `pdf_translator/translators/` | Übersetzungs-Backends: `claude` (kontextbewusst) und `pseudo` (Offline-Test) |
| `pdf_translator/pipeline.py` | Ablaufsteuerung: Stapel, Kontext, Parallelität, Prüfung, Cache |
| `pdf_translator/render.py` | Übersetzten Text an die Originalposition schreiben |
| `webapp/` | Lokale Weboberfläche (Flask) |

## Installation

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...                   # Windows: set ANTHROPIC_API_KEY=...
```

Den API-Key gibt es unter https://console.anthropic.com.

## Nutzung

### Weboberfläche

```bash
python webapp/app.py
```

Dann http://127.0.0.1:5000 öffnen und das PDF hineinziehen. Sprachen auswählen, auf „Übersetzen“ klicken, danach ansehen oder
herunterladen. Die Oberfläche ist nur auf dem eigenen Rechner erreichbar.

### Kommandozeile

```bash
python -m pdf_translator paper.pdf                  # Englisch -> Deutsch, ergibt paper.de.pdf
python -m pdf_translator paper.pdf -t French -o paper_fr.pdf
python -m pdf_translator paper.pdf -b pseudo        # Layout-Test ohne API-Key/Kosten
python -m pdf_translator paper.pdf --effort xhigh   # noch gründlicher (teurer, langsamer)
```

Wichtige Optionen: `--workers` für die Anzahl paralleler Anfragen, `--batch-chars` für die Zeichen pro Anfrage,
`--no-glossary`, `--model`, `--cache` und `--font` (siehe unten).

### Als Bibliothek

```python
from pdf_translator import get_translator, translate_pdf

translator = get_translator("claude", "English", "German")
result = translate_pdf("paper.pdf", "paper.de.pdf", translator, cache_path="paper.cache.sqlite")
print(result.warnings)
```

Ein eigenes Backend (z. B. DeepL oder ein lokales Modell) erbt von `Translator` und implementiert `translate_batch`.

## Tipps für LaTeX-Dokumente

Die Originalschriften im PDF sind meist nur teilweise eingebettet (Subset), deshalb fehlen ihnen oft Zeichen wie ä, ö,
ü und ß. Standardmäßig wird darum eine Unicode-Serifenschrift verwendet. Mit der Schrift „Latin Modern“ (der LaTeX-Standardlook,
frei verfügbar unter https://www.gust.org.pl/projects/e-foundry/latin-modern) fällt die Übersetzung optisch kaum auf:

```bash
python -m pdf_translator paper.pdf --font regular=lmroman10-regular.otf bold=lmroman10-bold.otf \
    italic=lmroman10-italic.otf bolditalic=lmroman10-bolditalic.otf
```

## Kosten und Dauer

Standardmodell ist `claude-opus-5-5` mit `effort=high`. Ein Dokument mit 126 Seiten ergibt grob einige hunderttausend
Tokens Ein- und Ausgabe, einschließlich der Denkschritte des Modells. Das kostet grob 5–15 US-Dollar und dauert mit 4 parallelen
Anfragen etwa 10–30 Minuten. Das sind Schätzungen, also am besten erst einen Teil testen. Dank Cache wird nichts
doppelt bezahlt. Mit `--effort medium` wird es günstiger und schneller.

## Grenzen

* Gescannte PDFs (Bilder ohne Textebene) brauchen vorher eine OCR, z. B. `ocrmypdf`.
* Abgesetzte Formeln bleiben unverändert. Inline-Formeln werden erhalten, aber mit der Ersatzschrift gesetzt.
* Text in Vektorgrafiken (Achsenbeschriftungen) wird übersetzt, wenn er als Text vorliegt. Text in Pixelbildern nicht.
* Deutsch ist ca. 20–30 % länger als Englisch. Der Text nutzt zuerst freien Platz in der Nähe und wird nur wenn nötig
  leicht verkleinert. Stark verkleinerte Blöcke erscheinen als Hinweis.

## Tests

```bash
python -m pytest tests
```

Die Tests laufen offline und erzeugen ihr Beispiel-PDF selbst (`tests/make_sample.py`).
