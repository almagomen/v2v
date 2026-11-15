"""
Aplicación de una variación de segmentación (banco de cortes, fase 3).

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_segmentation_apply -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from src.segmentation_apply import (
    VALID_MODES,
    _cleanup_stale,
    _contains_span,
    _match_reuse,
    _seq_index,
    apply_segmentation,
)


def _word(text: str, start: float, end: float, speaker: str = "SPEAKER_00") -> dict:
    return {"word": text, "start": start, "end": end, "speaker": speaker}


def _result(segments: list[dict], duration: float = 5.0) -> dict:
    return {
        "version": 2,
        "url": "https://example.com/v",
        "output_name": "v",
        "source_lang": "es",
        "target_lang": "es",
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
        "start": src_start,
        "end": src_end,
        "duration": round(src_end - src_start, 3),
        "orig_start": orig_start,
        "orig_end": orig_end,
        "orig_duration": round(orig_end - orig_start, 3),
        "src_start": src_start,
        "src_end": src_end,
        "text": text,
        "original_text": text,
        "speaker": "mrbeast",
        "original_speaker": speaker,
    }
    if phonemes:
        entry["phonemes"] = phonemes
    return entry


def _folder(tmp: Path) -> Path:
    """Tres segmentos con dos pausas de ~1.1 s: 0.85 deja tres, 1.5 une dos."""
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
    (tmp / "result.json").write_text(json.dumps(_result(segments)), encoding="utf-8")
    (tmp / "vocals.wav").write_bytes(b"RIFF")
    (tmp / "Seqs_src").mkdir()
    (tmp / "Seqs_trg").mkdir()
    for idx in (1, 2, 3):
        (tmp / "Seqs_trg" / f"tts_mrbeast_{idx:03d}.m4a").write_bytes(b"m4a")
        (tmp / "Seqs_trg" / f"tts_mrbeast_{idx:03d}_raw.wav").write_bytes(b"wav")
    return tmp


def _fake_split(vocals: Path, entries: list[dict], params=None):
    out = vocals.parent / "Seqs_src"
    out.mkdir(exist_ok=True)
    for idx, entry in enumerate(entries):
        entry.setdefault("src_start", entry["start"])
        entry.setdefault("src_end", entry["end"])
        (out / f"vocals_{idx + 1:03d}.wav").write_bytes(b"wav")


def _fake_clone(vocals, entries, language, audio_ref, tts_fn, cached_arrays=None, **kwargs):
    out = vocals.parent / "Seqs_trg"
    out.mkdir(exist_ok=True)
    for idx, entry in enumerate(entries):
        entry["start"] = entry["src_start"]
        entry["end"] = round(entry["src_start"] + 0.9, 3)
        (out / f"tts_mrbeast_{idx + 1:03d}.m4a").write_bytes(b"m4a")
    return [], [], 0


class _ApplyHarness:
    """Sustituye audio, TTS y TAR para probar la lógica sin torch ni Fish."""

    def __init__(self, cached: dict[int, tuple] | None = None):
        self.cached = cached or {}

    def __enter__(self):
        self._patches = [
            mock.patch(
                "src.segmentation_apply._load_cached_arrays",
                return_value=self.cached,
            ),
            mock.patch.dict(
                sys.modules,
                {
                    "src.pipeline": types.SimpleNamespace(
                        split_audio_sequences=_fake_split
                    ),
                    "src.audio_utils": types.SimpleNamespace(
                        clone_voice_segments=_fake_clone
                    ),
                    "src.tts": types.SimpleNamespace(model_tts=lambda *a, **k: None),
                    "api.routes.files": types.SimpleNamespace(
                        ensure_audio_segments_tar=lambda folder: None,
                        ensure_src_audio_segments_tar=lambda folder: None,
                    ),
                },
            ),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False


class TestMatchReuse(unittest.TestCase):
    def test_resync_exige_la_misma_agrupacion(self):
        current = [_segment(1, 0.0, 1.0, 0.0, 1.2, "a"), _segment(2, 2.0, 3.0, 2.0, 3.2, "b")]
        same = [{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 2.0, "end": 3.0, "text": "b"}]
        self.assertEqual(_match_reuse("resync", current, same), {0: 0, 1: 1})

        with self.assertRaises(ValueError):
            _match_reuse("resync", current, same[:1])
        with self.assertRaises(ValueError):
            _match_reuse(
                "resync",
                current,
                [{"start": 0.0, "end": 3.0, "text": "a b"}],
            )

    def test_regenerate_changed_reutiliza_por_texto(self):
        current = [_segment(1, 0.0, 1.0, 0.0, 1.2, "a"), _segment(2, 2.0, 3.0, 2.0, 3.2, "b")]
        proposed = [
            {"start": 2.0, "end": 3.0, "text": "b"},
            {"start": 4.0, "end": 5.0, "text": "c"},
        ]
        self.assertEqual(_match_reuse("regenerate_changed", current, proposed), {0: 1})

    def test_repeticiones_reales_ganan_por_solape(self):
        current = [
            _segment(1, 0.0, 1.0, 0.0, 1.2, "sí"),
            _segment(2, 5.0, 6.0, 5.0, 6.2, "sí"),
        ]
        proposed = [
            {"start": 5.0, "end": 6.0, "text": "sí"},
            {"start": 0.0, "end": 1.0, "text": "sí"},
        ]
        self.assertEqual(_match_reuse("regenerate_changed", current, proposed), {0: 1, 1: 0})

    def test_regenerate_all_no_reutiliza_nada(self):
        current = [_segment(1, 0.0, 1.0, 0.0, 1.2, "a")]
        proposed = [{"start": 0.0, "end": 1.0, "text": "a"}]
        self.assertEqual(_match_reuse("regenerate_all", current, proposed), {})


class TestContainsSpan(unittest.TestCase):
    def test_tramo_contenido(self):
        cur = {"orig_start": 1.0, "orig_end": 3.0}
        self.assertTrue(_contains_span(cur, {"start": 1.2, "end": 2.8}))
        self.assertFalse(_contains_span(cur, {"start": 0.5, "end": 2.8}))
        self.assertFalse(_contains_span(cur, {"start": 1.2, "end": 3.4}))


class TestCleanupStale(unittest.TestCase):
    def test_borra_solo_indices_fuera_de_rango_y_respeta_los_masters(self):
        with tempfile.TemporaryDirectory() as td:
            folder = _folder(Path(td))
            trg = folder / "Seqs_trg"
            (trg / "tts_mrbeast_004.m4a").write_bytes(b"x")
            (trg / "tts_mrbeast_004_raw.wav").write_bytes(b"x")
            (folder / "Seqs_src" / "vocals_004.wav").write_bytes(b"x")

            _cleanup_stale(folder, 3)

            self.assertFalse((trg / "tts_mrbeast_004.m4a").exists())
            self.assertFalse((trg / "tts_mrbeast_004_raw.wav").exists())
            self.assertFalse((folder / "Seqs_src" / "vocals_004.wav").exists())
            for idx in (1, 2, 3):
                self.assertTrue((trg / f"tts_mrbeast_{idx:03d}.m4a").exists())
                self.assertTrue((trg / f"tts_mrbeast_{idx:03d}_raw.wav").exists())

    def test_indice_se_ancla_al_final_del_nombre(self):
        self.assertEqual(_seq_index(Path("tts_default_fish_007_raw.wav")), 7)
        self.assertEqual(_seq_index(Path("vocals_012.wav")), 12)
        self.assertIsNone(_seq_index(Path("vocals_final.wav")))


class TestApplySegmentation(unittest.TestCase):
    def test_modo_invalido(self):
        with tempfile.TemporaryDirectory() as td:
            folder = _folder(Path(td))
            with self.assertRaises(ValueError):
                apply_segmentation(folder, {}, "otro")
        self.assertEqual(VALID_MODES, ("resync", "regenerate_changed", "regenerate_all"))

    def test_resync_no_toca_texto_ni_llama_a_tts(self):
        with tempfile.TemporaryDirectory() as td:
            folder = _folder(Path(td))
            with _ApplyHarness(cached={1: (None, 24000), 2: (None, 24000), 3: (None, 24000)}):
                data = apply_segmentation(
                    folder, {"lead_max": 0.05, "tail_max": 0.05}, "resync"
                )
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(data["mode"], "resync")
        self.assertEqual(data["summary"]["reused"], 3)
        self.assertEqual(data["summary"]["resynthesized"], 0)
        self.assertEqual(data["summary"]["retranslated"], 0)
        self.assertEqual(len(result["segments"]), 3)
        # Mismo texto de origen en ambos lados y ningún phonemes perdido.
        self.assertEqual(
            [s.get("original_text", s["text"]) for s in result["segments"]],
            ["Hola qué tal.", "Bien gracias.", "Adiós."],
        )
        self.assertEqual(data["summary"]["phonemes_dropped"], 0)
        self.assertEqual(result["segments"][0]["phonemes"], {"Hola": "ola"})

    def test_regenerate_changed_descarta_phonemes_al_fusionar(self):
        with tempfile.TemporaryDirectory() as td:
            folder = _folder(Path(td))
            with _ApplyHarness(cached={1: (None, 24000)}):
                data = apply_segmentation(folder, {"hard_gap": 1.5}, "regenerate_changed")
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(data["summary"]["reused"], 1)
        self.assertEqual(data["summary"]["retranslated"], 1)
        # Los dos diccionarios de los segmentos fusionados se descartan.
        self.assertEqual(data["summary"]["phonemes_dropped"], 2)
        self.assertNotIn("phonemes", result["segments"][0])

    def test_regenerate_all_resintetiza_todo(self):
        with tempfile.TemporaryDirectory() as td:
            folder = _folder(Path(td))
            with _ApplyHarness(cached={}):
                data = apply_segmentation(folder, {}, "regenerate_all")
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(data["summary"]["reused"], 0)
        self.assertEqual(data["summary"]["resynthesized"], 3)
        self.assertEqual(len(result["segments"]), 3)
        self.assertNotIn("phonemes", result["segments"][0])

    def test_escribe_qa_y_bordes_del_clip(self):
        with tempfile.TemporaryDirectory() as td:
            folder = _folder(Path(td))
            with _ApplyHarness(cached={1: (None, 24000)}):
                data = apply_segmentation(folder, {"hard_gap": 1.5}, "regenerate_changed")
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))

        self.assertIn("qa", data)
        first = result["segments"][0]
        self.assertIn("src_start", first)
        self.assertIn("src_end", first)
        self.assertGreaterEqual(first["src_end"], first["src_start"])
        self.assertEqual(first["start"], first["src_start"])

    def test_actualiza_la_pista_original_con_el_mismo_reparto(self):
        with tempfile.TemporaryDirectory() as td:
            folder = _folder(Path(td))
            with _ApplyHarness(cached={1: (None, 24000)}):
                apply_segmentation(folder, {"hard_gap": 1.5}, "regenerate_changed")
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))

        originals = result["original_segments"]
        self.assertEqual(len(originals), len(result["segments"]))
        self.assertEqual(
            [s["seg"] for s in originals],
            [s["seg"] for s in result["segments"]],
        )
        # El tramo original es el del habla, no el del clip TTS.
        self.assertEqual(originals[0]["start"], result["segments"][0]["orig_start"])
        self.assertEqual(originals[0]["src_start"], result["segments"][0]["src_start"])


if __name__ == "__main__":
    unittest.main()
