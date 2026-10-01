import json
import os
import sys
from types import SimpleNamespace

import pymupdf
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_sample import make_sample  # noqa: E402
from pdf_translator import extract_document, get_translator, translate_pdf  # noqa: E402
from pdf_translator.markup import check_translation, is_well_formed  # noqa: E402
from pdf_translator.translators.base import BatchRequest, Translator  # noqa: E402
from pdf_translator.translators.claude import ClaudeTranslator  # noqa: E402


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("pdf") / "sample.pdf")
    make_sample(path, pages=2)
    return path


def test_markup_checks():
    assert is_well_formed("a <b>b <i>c</i></b>")
    assert not is_well_formed("a <b>b <i>c</b></i>")
    assert not is_well_formed("<script>x</script>")
    assert check_translation("We use <m>x+y</m> in 3.5 s [12].", "Wir nutzen <m>x+y</m> in 3,5 s [12].") == []
    assert any("Formeln" in p for p in check_translation("<m>x+y</m>", "<m>x + y</m>"))
    assert any("Zahlen" in p for p in check_translation("in 2020 [12]", "im Jahr [12]"))


def test_extraction_keeps_formulas_and_images_out(sample):
    doc = extract_document(sample)
    texts = [b.plain for b in doc.blocks]
    assert any("Layout-Preserving" in t for t in texts)
    assert not any("a + b" in t for t in texts), "Formel-Block darf nicht übersetzt werden"
    assert not any(t.strip() == "1" for t in texts), "Seitenzahl darf nicht übersetzt werden"
    styled = next(b for b in doc.blocks if "proposed method" in b.plain)
    assert "<i>" in styled.tagged and "<b>" in styled.tagged


def test_pseudo_translation_preserves_images(sample, tmp_path):
    out = str(tmp_path / "out.pdf")
    translator = get_translator("pseudo", "English", "German")
    result = translate_pdf(sample, out, translator, cache_path=str(tmp_path / "c.sqlite"))
    assert result.blocks_translated == result.blocks_total > 0

    src, dst = pymupdf.open(sample), pymupdf.open(out)
    assert src.page_count == dst.page_count
    for p_src, p_dst in zip(src, dst):
        assert [i["bbox"] for i in p_src.get_image_info()] == [i["bbox"] for i in p_dst.get_image_info()]
        text = p_dst.get_text()
        assert "rëportrt" in text  # übersetzt
        assert "report" not in text  # Original entfernt
        assert text.count("a + b = g") == p_src.get_text().count("a + b = g") == 2  # Formel unverändert

    # Zweiter Lauf kommt komplett aus dem Cache.
    again = translate_pdf(sample, out, translator, cache_path=str(tmp_path / "c.sqlite"))
    assert again.blocks_from_cache == again.blocks_total


class FlakyTranslator(Translator):
    """Lässt beim ersten Versuch eine Zahl weg – die Pipeline muss nachbessern lassen."""

    name = "flaky"

    def __init__(self):
        super().__init__("English", "German")
        self.calls = []

    def translate_batch(self, request: BatchRequest) -> dict[str, str]:
        self.calls.append(request)
        if len(self.calls) == 1:
            return {s.id: "kaputt" for s in request.segments}
        return {s.id: s.text for s in request.segments}


def test_retry_with_feedback(sample, tmp_path):
    t = FlakyTranslator()
    translate_pdf(sample, str(tmp_path / "o.pdf"), t, workers=1, batch_chars=10**6, batch_segments=10**6)
    assert len(t.calls) == 2
    assert t.calls[1].feedback  # Probleme werden an das Modell zurückgemeldet


def test_claude_request_shape():
    """Prüft den API-Aufruf mit einem Fake-Client (ohne Netzwerk)."""
    seen = {}

    class FakeStream:
        def __init__(self, **kw):
            seen.update(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            payload = json.loads(seen["messages"][0]["content"].split("\n\n", 1)[1])
            out = {"translations": [{"id": s["id"], "text": "Hallo <b>Welt</b>"} for s in payload["segments"]]}
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(out))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: FakeStream(**kw))))
    t = ClaudeTranslator("English", "German", client=client, use_glossary=False)
    from pdf_translator.translators.base import Segment

    res = t.translate_batch(BatchRequest([Segment("a", "Hello <b>world</b>")], ["prev"], ["next"]))
    assert res == {"a": "Hallo <b>Welt</b>"}
    assert seen["model"] == "claude-opus-5-5"
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["fallbacks"] == "default"
