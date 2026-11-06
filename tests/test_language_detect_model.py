"""El detector de idioma debe usar el modelo ligero, no el de transcripción.

`detect_language_whisper` importa Whisper y `src.stt` de forma perezosa, así que
aquí se sustituyen ambos por dobles: la prueba corre sin torch ni google-genai.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import numpy as np

from src import language_detect

SPAN = 48_000  # 3 s a 16 kHz: suficiente para el doble


class _Mel:
    def to(self, device):
        return self


class _Model:
    dims = types.SimpleNamespace(n_mels=80)
    device = "cpu"

    def __init__(self, probs: dict[str, float]):
        self.probs = probs

    def detect_language(self, mel):
        return None, self.probs


class TestLanguageDetectorModel(unittest.TestCase):
    def _run(
        self,
        probs: dict[str, float],
        model: _Model | None = None,
        total_samples: int = SPAN,
    ):
        calls: list[str] = []
        fake_model = model or _Model(probs)

        def _detector():
            calls.append("detector")
            return fake_model

        def _transcription_model():
            raise AssertionError("no debe cargar el modelo de transcripción")

        fake_stt = types.ModuleType("src.stt")
        fake_stt.get_language_detector_model = _detector
        fake_stt.get_whisper_model = _transcription_model

        fake_whisper = types.ModuleType("whisper")
        fake_whisper.audio = types.SimpleNamespace(N_SAMPLES=SPAN)
        fake_whisper.load_audio = lambda path: np.zeros(total_samples, dtype=np.float32)
        fake_whisper.pad_or_trim = lambda chunk: chunk
        fake_whisper.log_mel_spectrogram = lambda chunk, n_mels: _Mel()

        with mock.patch.dict(
            sys.modules, {"whisper": fake_whisper, "src.stt": fake_stt}
        ):
            result = language_detect.detect_language_whisper("audio.wav")

        return result, calls

    def test_usa_el_detector_ligero(self):
        (language, probability, detail), calls = self._run({"es": 0.91, "pt": 0.09})

        self.assertEqual(language, "es")
        self.assertAlmostEqual(probability, 0.91)
        self.assertEqual(detail, "")
        self.assertEqual(calls, ["detector"])

    def test_promedia_las_ventanas(self):
        # Con un audio de 3 ventanas, la probabilidad final es la media de las tres.
        probs = {"es": 0.6, "en": 0.4}
        (language, probability, _detail), _calls = self._run(
            probs, total_samples=SPAN * 3
        )

        self.assertEqual(language, "es")
        self.assertAlmostEqual(probability, 0.6)

    def test_confianza_baja_incluye_alternativas(self):
        (language, probability, detail), _calls = self._run({"es": 0.4, "en": 0.3, "pt": 0.2})

        self.assertEqual(language, "es")
        self.assertAlmostEqual(probability, 0.4)
        self.assertIn("alternativas", detail)
        self.assertIn("en 0.30", detail)


if __name__ == "__main__":
    unittest.main()
