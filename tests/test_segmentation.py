"""
Parámetros de segmentación, diff de cortes y motor de simulación.

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_segmentation -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.pacing import SOURCE_LEAD_MAX, SOURCE_TAIL_MAX, source_bounds, source_margins
from src.segmentation import (
    ADVANCED_FIELDS,
    BASIC_FIELDS,
    SegmentationParams,
    diff_segments,
)
from src.segmentation_preview import simulate


def _word(text: str, start: float, end: float, speaker: str = "SPEAKER_00") -> dict:
    return {"word": text, "start": start, "end": end, "speaker": speaker}


def _result(segments: list[dict], duration: float = 5.0) -> dict:
    return {
        "version": 2,
        "url": "https://example.com/v",
        "output_name": "v",
        "source_lang": "es",
        "target_lang": "en",
        "segments": segments,
        "info": {"duration": duration},
    }


def _segment(
    seg: int,
    orig_start: float,
    orig_end: float,
    src_start: float,
    src_end: float,
    text: str,
    speaker: str = "SPEAKER_00",
    phonemes: dict | None = None,
) -> dict:
    entry = {
        "seg": seg,
        "start": orig_start,
        "end": orig_end,
        "duration": round(orig_end - orig_start, 3),
        "orig_start": orig_start,
        "orig_end": orig_end,
        "orig_duration": round(orig_end - orig_start, 3),
        "src_start": src_start,
        "src_end": src_end,
        "text": f"[T] {text}",
        "original_text": text,
        "speaker": "mrbeast",
        "original_speaker": speaker,
    }
    if phonemes:
        entry["phonemes"] = phonemes
    return entry


class TestSegmentationParams(unittest.TestCase):
    def test_defaults_reproducen_produccion(self):
        p = SegmentationParams()
        # El pipeline llama siempre con gap=0.85; el 1.3 de la función es un
        # default engañoso que no debe filtrarse al dataclass.
        self.assertEqual(p.hard_gap, 0.85)
        self.assertEqual(p.min_silence_gap, 0.85)
        self.assertEqual(p.min_sentence_gap, 0.18)
        self.assertEqual(p.min_duration, 2.8)
        self.assertEqual(p.uppercase_gap, 0.32)
        self.assertEqual(p.lead_max, SOURCE_LEAD_MAX)
        self.assertEqual(p.tail_max, SOURCE_TAIL_MAX)

    def test_niveles_no_se_solapan(self):
        basic = set(BASIC_FIELDS)
        advanced = set(ADVANCED_FIELDS)
        self.assertFalse(basic & advanced)
        known = {f for f in SegmentationParams().as_dict()}
        self.assertEqual(basic | advanced, known)

    def test_with_overrides_ignora_claves_y_valores_invalidos(self):
        p = SegmentationParams().with_overrides(
            {"hard_gap": 1.2, "desconocido": 9, "min_duration": None, "merge_max_words": "4"}
        )
        self.assertEqual(p.hard_gap, 1.2)
        self.assertEqual(p.min_duration, 2.8)
        self.assertEqual(p.merge_max_words, 4)

    def test_with_overrides_no_muta_el_original(self):
        base = SegmentationParams()
        changed = base.with_overrides({"lead_max": 0.5})
        self.assertEqual(base.lead_max, 0.150)
        self.assertEqual(changed.lead_max, 0.5)

    def test_source_margins_respeta_los_parametros(self):
        p = SegmentationParams().with_overrides({"lead_max": 0.05, "margin_share": 0.5})
        lead, tail = source_margins(2.0, 2.0, p)
        self.assertEqual(lead, 0.05)
        self.assertEqual(tail, SOURCE_TAIL_MAX)

    def test_source_bounds_acepta_parametros(self):
        times = [(1.0, 2.0), (3.0, 4.0)]
        p = SegmentationParams().with_overrides({"lead_max": 0.0, "tail_max": 0.0})
        self.assertEqual(source_bounds(times, 0, 6.0, p), (1.0, 2.0))
        # Sin parámetros recupera los márgenes de producción.
        self.assertEqual(source_bounds(times, 0, 6.0), (0.85, 2.4))


class TestDiffSegments(unittest.TestCase):
    def test_igual_y_ajustado(self):
        current = [{"start": 0.0, "end": 2.0, "text": "hola"}, {"start": 3.0, "end": 5.0, "text": "adios"}]
        proposed = [{"start": 0.0, "end": 2.0, "text": "hola"}, {"start": 2.9, "end": 5.1, "text": "adios"}]
        rows = diff_segments(current, proposed)
        self.assertEqual([r["status"] for r in rows], ["igual", "ajustado"])
        self.assertFalse(any(r["needs_retranslation"] for r in rows))

    def test_fusionado(self):
        current = [
            {"start": 0.0, "end": 1.0, "text": "a"},
            {"start": 1.2, "end": 2.0, "text": "b"},
        ]
        proposed = [{"start": 0.0, "end": 2.0, "text": "a b"}]
        rows = diff_segments(current, proposed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "fusionado")
        self.assertTrue(rows[0]["needs_retranslation"])

    def test_eliminado(self):
        current = [
            {"start": 0.0, "end": 1.0, "text": "a"},
            {"start": 3.0, "end": 4.0, "text": "b"},
        ]
        proposed = [{"start": 0.0, "end": 1.0, "text": "a"}]
        rows = diff_segments(current, proposed)
        self.assertEqual([r["status"] for r in rows], ["igual", "eliminado"])
        self.assertEqual(rows[1]["current_index"], 2)

    def test_partido_y_nuevo(self):
        current = [{"start": 0.0, "end": 4.0, "text": "a b c d"}]
        proposed = [
            {"start": 0.0, "end": 1.8, "text": "a b"},
            {"start": 2.0, "end": 4.0, "text": "c d"},
            {"start": 6.0, "end": 7.0, "text": "e"},
        ]
        rows = diff_segments(current, proposed)
        self.assertEqual(rows[0]["status"], "partido")
        self.assertEqual(rows[1]["status"], "partido")
        self.assertEqual(rows[2]["status"], "nuevo")

    def test_ampliado_y_modificado(self):
        current = [{"start": 1.0, "end": 2.0, "text": "a"}]
        self.assertEqual(
            diff_segments(current, [{"start": 0.5, "end": 2.5, "text": "a b"}])[0]["status"],
            "ampliado",
        )
        self.assertEqual(
            diff_segments(current, [{"start": 0.5, "end": 1.5, "text": "a b"}])[0]["status"],
            "modificado",
        )


class TestSimulate(unittest.TestCase):
    def _folder(self, tmp: Path) -> Path:
        # Palabras con dos pausas de ~1.1-1.2 s: con el default (0.85) son tres
        # segmentos; subiendo el corte a 1.5 s las dos primeras se unen.
        words = [
            _word("Hola", 0.0, 0.3),
            _word("qué", 0.35, 0.55),
            _word("tal.", 0.6, 0.9),
            _word("Bien", 2.0, 2.3),
            _word("gracias.", 2.35, 2.8),
            _word("Adiós.", 4.0, 4.4),
        ]
        (tmp / "words_assigned.json").write_text(
            json.dumps({"language": "es", "words": words}), encoding="utf-8"
        )
        segments = [
            _segment(1, 0.0, 0.9, 0.0, 1.3, "Hola qué tal.", phonemes={"Hola": "ola"}),
            _segment(2, 2.0, 2.8, 1.85, 3.2, "Bien gracias.", phonemes={"Bien": "bien"}),
            _segment(3, 4.0, 4.4, 3.85, 4.64, "Adiós."),
        ]
        (tmp / "result.json").write_text(
            json.dumps(_result(segments)), encoding="utf-8"
        )
        return tmp

    def test_defaults_reproducen_la_segmentacion_actual(self):
        with tempfile.TemporaryDirectory() as td:
            folder = self._folder(Path(td))
            data = simulate(folder)
        self.assertEqual(data["words_source"], "assigned")
        self.assertEqual(len(data["current"]["clips"]), 3)
        self.assertEqual(len(data["proposed"]["clips"]), 3)
        self.assertEqual([r["status"] for r in data["rows"]], ["igual", "igual", "igual"])
        self.assertEqual(data["summary"]["changed"], 0)
        self.assertTrue(all(r["phonemes_carry"] for r in data["rows"][:2]))

    def test_pausa_de_corte_mas_larga_fusiona(self):
        with tempfile.TemporaryDirectory() as td:
            folder = self._folder(Path(td))
            data = simulate(folder, {"hard_gap": 1.5})
        self.assertEqual(len(data["proposed"]["clips"]), 2)
        self.assertEqual(data["rows"][0]["status"], "fusionado")
        self.assertEqual(data["summary"]["retranslate"], 1)
        # Los phonemes de los dos segmentos fusionados no pueden repartirse.
        self.assertEqual(data["summary"]["phonemes_dropped"], 2)

    def test_margen_cero_no_cambia_el_numero_de_clips(self):
        with tempfile.TemporaryDirectory() as td:
            folder = self._folder(Path(td))
            data = simulate(folder, {"lead_max": 0.0, "tail_max": 0.0})
        self.assertEqual(len(data["proposed"]["clips"]), 3)
        self.assertTrue(all(r["status"] in {"ajustado", "igual"} for r in data["rows"]))
        self.assertEqual(data["summary"]["resync"], data["summary"]["changed"])

    def test_sin_words_assigned_usa_whisper_raw(self):
        with tempfile.TemporaryDirectory() as td:
            folder = self._folder(Path(td))
            (folder / "words_assigned.json").unlink()
            raw = {
                "language": "es",
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.8,
                        "text": "Hola qué tal. Bien gracias.",
                        "words": [
                            {"word": "Hola", "start": 0.0, "end": 0.3},
                            {"word": "qué", "start": 0.35, "end": 0.55},
                            {"word": "tal.", "start": 0.6, "end": 0.9},
                            {"word": "Bien", "start": 2.0, "end": 2.3},
                            {"word": "gracias.", "start": 2.35, "end": 2.8},
                        ],
                    }
                ],
            }
            (folder / "whisper_raw.json").write_text(json.dumps(raw), encoding="utf-8")
            data = simulate(folder)
        self.assertEqual(data["words_source"], "raw")
        # El hablante se aproxima por solape y todos caen en SPEAKER_00.
        self.assertTrue(all(c["speaker"] == "SPEAKER_00" for c in data["proposed"]["clips"]))


if __name__ == "__main__":
    unittest.main()
