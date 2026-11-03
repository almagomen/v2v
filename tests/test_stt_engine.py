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
from src.stt_crisper import _crisper_result_to_segments, _split_device


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


if __name__ == "__main__":
    unittest.main()
