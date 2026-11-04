"""Tests del motor STT configurable y del adaptador de resultados de CrisperWhisper.

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_stt_engine -v
"""
from __future__ import annotations

import os
import sys
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
    VERBATIM_TAGS,
    _crisper_result_to_segments,
    _language_scores,
    _load_audio_windows,
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

    def test_scores_mueve_la_vista_ct2_a_cpu(self):
        """Regresión: `StorageView` en GPU no expone `__array_interface__`."""
        import numpy as np

        class FakeStorageView:
            def __init__(self, values, device="cuda"):
                self.values = values
                self.device = device

            def to(self, dtype):
                return FakeStorageView(self.values, self.device)

            def to_device(self, device):
                return FakeStorageView(self.values, "cpu")

            @property
            def __array_interface__(self):
                if self.device != "cpu":
                    raise AttributeError(
                        "Cannot get __array_interface__ when the StorageView "
                        "is viewing a CUDA array"
                    )
                return np.asarray(self.values, dtype=np.float32).__array_interface__

        ctranslate2 = SimpleNamespace(
            DataType=SimpleNamespace(float32="float32"),
            Device=SimpleNamespace(cpu="cpu"),
        )
        lang_ids = {"en": 0, "es": 1, "pt": 2}

        with patch.dict(sys.modules, {"ctranslate2": ctranslate2}):
            language, probability = _language_scores(
                FakeStorageView([0.0, 5.0, 1.0]), lang_ids
            )

        self.assertEqual(language, "es")
        self.assertGreater(probability, 0.5)

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
                self.encoded = []

            def encode_text(self, text):
                self.encoded.append(text)
                return [900, 901, 902, 903, 904]

            def extract_features(self, audio):
                self.audio.append(audio)
                return "features"

        engine = Engine()
        model = SimpleNamespace(_engine=engine)

        with (
            patch("src.stt_crisper._load_audio_windows", return_value=["audio"]),
            patch("builtins.print"),
        ):
            language = detect_language_crisper(model, "vocals.wav")

        # Código limpio, sin los marcadores <|...|>.
        self.assertEqual(language, "es")
        self.assertEqual(engine.audio, ["audio"])
        self.assertEqual(engine.encoded, [VERBATIM_TAGS])
        # El prefijo debe imitar al de entrenamiento: etiquetas + [sot].
        self.assertEqual(
            engine.model.prompts, [("features", [900, 901, 902, 903, 904, 50258])]
        )

    def test_falla_sin_decoder_ct2(self):
        model = SimpleNamespace(_engine=SimpleNamespace(_lang_ids={}, sot_id=None))
        with self.assertRaises(RuntimeError):
            detect_language_crisper(model, "vocals.wav")


class TestAudioWindows(unittest.TestCase):
    def _windows(self, total_seconds):
        import numpy as np

        reads = []

        class Info:
            samplerate = 16000
            frames = int(total_seconds * 16000)

        def read(path, start=0, frames=None, **kwargs):
            reads.append(start)
            return np.zeros(frames, dtype=np.float32), Info.samplerate

        soundfile = SimpleNamespace(info=lambda path: Info(), read=read)
        audio_module = SimpleNamespace(load_audio=lambda audio, sr: audio)
        crisperwhisper = SimpleNamespace(audio=audio_module)

        with patch.dict(
            sys.modules,
            {
                "soundfile": soundfile,
                "crisperwhisper": crisperwhisper,
                "crisperwhisper.audio": audio_module,
            },
        ):
            windows = _load_audio_windows("vocals.wav")
        return windows, reads

    def test_audio_corto_usa_una_ventana(self):
        windows, reads = self._windows(10)

        self.assertEqual(len(windows), 1)
        self.assertEqual(reads, [0])

    def test_audio_largo_reparte_tres_ventanas(self):
        windows, reads = self._windows(90)

        self.assertEqual(len(windows), 3)
        self.assertEqual(reads, [0, 30 * 16000, 60 * 16000])

    def test_audio_mediano_no_repite_ventanas(self):
        windows, reads = self._windows(40)

        self.assertEqual(len(windows), 1)
        self.assertEqual(reads, [0])


if __name__ == "__main__":
    unittest.main()
