"""Tests del motor STT configurable y del adaptador de resultados de CrisperWhisper.

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_stt_engine -v
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.config import (
    DEFAULT_STT_ENGINE,
    STT_ENGINES,
    get_stt_engine,
    set_stt_engine,
)
from src.stt_crisper import (
    _crisper_result_to_segments,
    _language_scores,
    _split_device,
    detect_language_crisper,
)


class TestSttEngineSetting(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("V2V_STT_ENGINE", None)

    def tearDown(self):
        self._env.stop()

    def test_default_sin_variable(self):
        self.assertEqual(DEFAULT_STT_ENGINE, "stable")
        self.assertEqual(get_stt_engine(), "stable")

    def test_roundtrip(self):
        self.assertEqual(set_stt_engine("crisper"), "crisper")
        self.assertEqual(get_stt_engine(), "crisper")
        self.assertEqual(set_stt_engine("stable"), "stable")
        self.assertEqual(get_stt_engine(), "stable")

    def test_normaliza_mayusculas_y_espacios(self):
        self.assertEqual(set_stt_engine("  CRISPER  "), "crisper")
        self.assertEqual(get_stt_engine(), "crisper")

    def test_valor_invalido_lanza(self):
        with self.assertRaises(ValueError):
            set_stt_engine("whisperx")
        with self.assertRaises(ValueError):
            set_stt_engine("")

    def test_variable_de_entorno_invalida_cae_al_default(self):
        os.environ["V2V_STT_ENGINE"] = "desconocido"
        self.assertEqual(get_stt_engine(), DEFAULT_STT_ENGINE)

    def test_variable_de_entorno_valida_se_lee(self):
        os.environ["V2V_STT_ENGINE"] = "CRISPER"
        self.assertEqual(get_stt_engine(), "crisper")

    def test_engines_declarados(self):
        self.assertEqual(set(STT_ENGINES), {"stable", "crisper"})


class TestSplitDevice(unittest.TestCase):
    def test_con_indice(self):
        self.assertEqual(_split_device("cuda:1"), ("cuda", 1))
        self.assertEqual(_split_device("cuda:0"), ("cuda", 0))

    def test_sin_indice(self):
        self.assertEqual(_split_device("cpu"), ("cpu", 0))
        self.assertEqual(_split_device("cuda"), ("cuda", 0))

    def test_vacio(self):
        self.assertEqual(_split_device(""), ("auto", 0))
        self.assertEqual(_split_device(None), ("auto", 0))


class TestCrisperResultToSegments(unittest.TestCase):
    def test_con_palabras(self):
        result = SimpleNamespace(
            text=" Eh, hola mundo. ",
            words=[
                SimpleNamespace(word=" Eh,", start=0.1, end=0.4),
                SimpleNamespace(word=" hola", start=0.5, end=0.8),
                SimpleNamespace(word=" mundo.", start=0.9, end=1.4),
            ],
        )
        payload = _crisper_result_to_segments(result, "es")

        self.assertEqual(payload["language"], "es")
        self.assertEqual(payload["text"], "Eh, hola mundo.")
        self.assertEqual(len(payload["segments"]), 1)
        segment = payload["segments"][0]
        self.assertEqual(segment["start"], 0.1)
        self.assertEqual(segment["end"], 1.4)
        self.assertEqual(segment["text"], "Eh, hola mundo.")
        self.assertEqual([w["word"] for w in segment["words"]], [" Eh,", " hola", " mundo."])

    def test_filtra_palabras_sin_tiempo_o_vacias(self):
        result = SimpleNamespace(
            text="hola",
            words=[
                SimpleNamespace(word="hola", start=0.2, end=0.6),
                SimpleNamespace(word="", start=0.7, end=0.8),
                SimpleNamespace(word="tarde", start=None, end=None),
                SimpleNamespace(word=" fin", start=0.9, end=0.5),
            ],
        )
        payload = _crisper_result_to_segments(result, "pt")

        words = payload["segments"][0]["words"]
        self.assertEqual([w["word"] for w in words], ["hola", " fin"])
        # El fin nunca queda antes del inicio.
        self.assertEqual(words[1]["end"], 0.9)

    def test_sin_palabras_usa_texto_y_duracion(self):
        result = SimpleNamespace(text="solo texto", words=[], duration=3.5)
        payload = _crisper_result_to_segments(result, "en")

        self.assertEqual(payload["text"], "solo texto")
        segment = payload["segments"][0]
        self.assertEqual(segment["start"], 0.0)
        self.assertEqual(segment["end"], 3.5)
        self.assertEqual(segment["words"], [])

    def test_resultado_vacio(self):
        result = SimpleNamespace(text="", words=[])
        payload = _crisper_result_to_segments(result, "fr")

        self.assertEqual(payload["language"], "fr")
        self.assertEqual(payload["text"], "")
        self.assertEqual(payload["segments"], [])


class TestCrisperLanguageDetection(unittest.TestCase):
    def test_scores_elige_el_mayor_y_normaliza(self):
        lang_ids = {"en": 0, "es": 1, "pt": 2}
        language, probability = _language_scores([1.0, 3.0, 2.0], lang_ids)

        self.assertEqual(language, "es")
        self.assertGreater(probability, 0.5)
        self.assertLessEqual(probability, 1.0)

    def test_scores_rechaza_ids_fuera_del_vocabulario(self):
        with self.assertRaises(RuntimeError):
            _language_scores([1.0, 2.0], {"en": 5})

    def test_detecta_con_prefill_sin_depender_de_detect_language(self):
        """Regresión: el config.json CT2 pierde lang_ids y detect_language revienta."""

        class RawModel:
            def __init__(self):
                self.prompts = []

            def detect_language(self, features):
                raise RuntimeError(
                    "[json.exception.type_error.302] type must be number, but is number"
                )

            def prefill(self, features, prompt):
                self.prompts.append((features, prompt))
                return object(), [0.0, 4.0, 1.0]

        class Engine:
            _lang_ids = {"en": 0, "es": 1, "pt": 2}
            sot_id = 50258

            def __init__(self):
                self.model = RawModel()
                self.audio = []

            def extract_features(self, audio):
                self.audio.append(audio)
                return "features"

        engine = Engine()
        model = SimpleNamespace(_engine=engine)

        with (
            patch("src.stt_crisper._load_audio_head", return_value="audio"),
            patch("builtins.print"),
        ):
            language = detect_language_crisper(model, "vocals.wav")

        # Código limpio, sin los marcadores <|...|>.
        self.assertEqual(language, "es")
        self.assertEqual(engine.audio, ["audio"])
        self.assertEqual(engine.model.prompts, [("features", [Engine.sot_id])])

    def test_falla_sin_decoder_ct2(self):
        model = SimpleNamespace(_engine=SimpleNamespace(_lang_ids={}, sot_id=None))
        with self.assertRaises(RuntimeError):
            detect_language_crisper(model, "vocals.wav")


if __name__ == "__main__":
    unittest.main()
