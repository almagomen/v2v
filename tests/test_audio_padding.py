"""Pruebas del reparto de silencio en los valles internos del TTS."""
import unittest

import numpy as np

from src.audio_utils import (
    distribute_silence_padding,
    pad_tail_silence,
    synthesize_segment_audio,
)

RATE = 1000  # 1 muestra = 1 ms; las ventanas de 40/20 ms siguen siendo válidas


def _speech(seconds: float, amplitude: float = 0.5) -> np.ndarray:
    return np.full((1, int(seconds * RATE)), amplitude, dtype=np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros((1, int(seconds * RATE)), dtype=np.float32)


def _silence_runs(arr: np.ndarray) -> list[float]:
    """Duración en segundos de cada tramo de ceros consecutivos."""
    silent = np.abs(arr).max(axis=0) < 1e-6
    runs: list[float] = []
    start = None
    for i, value in enumerate(silent):
        if value and start is None:
            start = i
        elif not value and start is not None:
            runs.append((i - start) / RATE)
            start = None
    if start is not None:
        runs.append((len(silent) - start) / RATE)
    return runs


class TestDistributeSilencePadding(unittest.TestCase):
    def test_encuentra_pausas_de_120ms_y_llega_al_objetivo(self):
        arr = np.concatenate([
            _speech(1.0), _silence(0.12),
            _speech(1.0), _silence(0.12),
            _speech(1.0),
        ], axis=-1)
        target = arr.shape[-1] + int(0.30 * RATE)

        out = distribute_silence_padding(
            arr, target, RATE,
            max_per_valley=int(0.60 * RATE),
            allow_tail_pad=False,
            min_silence_sec=0.10,
            valley_growth=1.6,
        )

        self.assertEqual(out.shape[-1], target)

    def test_prioriza_los_valles_mas_largos(self):
        arr = np.concatenate([
            _speech(0.8), _silence(0.50),
            _speech(0.8), _silence(0.12),
            _speech(0.8),
        ], axis=-1)
        target = arr.shape[-1] + int(0.48 * RATE)

        out = distribute_silence_padding(
            arr, target, RATE,
            max_per_valley=int(0.60 * RATE),
            allow_tail_pad=False,
            min_silence_sec=0.10,
            valley_growth=1.6,
        )

        runs = _silence_runs(out)
        self.assertEqual(len(runs), 2)
        # La pausa larga absorbe todo el relleno; la corta no se toca.
        self.assertAlmostEqual(runs[0], 0.98, delta=0.03)
        self.assertAlmostEqual(runs[1], 0.12, delta=0.03)

    def test_respeta_el_tope_por_valle(self):
        arr = np.concatenate([
            _speech(1.0), _silence(1.0), _speech(1.0),
        ], axis=-1)
        original = arr.shape[-1]

        out = distribute_silence_padding(
            arr, original + int(1.0 * RATE), RATE,
            max_per_valley=int(0.60 * RATE),
            allow_tail_pad=False,
            min_silence_sec=0.10,
            valley_growth=1.6,
        )

        # Un solo valle de 1 s: su tope de crecimiento es 0.60 s.
        self.assertEqual(out.shape[-1], original + int(0.60 * RATE))

    def test_no_anade_silencio_al_final(self):
        arr = np.concatenate([_speech(1.0), _silence(0.50)], axis=-1)
        original = arr.shape[-1]

        out = distribute_silence_padding(
            arr, original + int(0.50 * RATE), RATE,
            max_per_valley=int(0.60 * RATE),
            allow_tail_pad=False,
        )

        self.assertEqual(out.shape[-1], original)

    def test_no_se_pasa_del_objetivo(self):
        arr = np.concatenate([
            _speech(1.0), _silence(0.30),
            _speech(1.0), _silence(0.30),
            _speech(1.0),
        ], axis=-1)
        target = arr.shape[-1] + int(0.10 * RATE)

        out = distribute_silence_padding(
            arr, target, RATE,
            max_per_valley=int(0.60 * RATE),
            allow_tail_pad=False,
        )

        self.assertLessEqual(out.shape[-1], target)


class TestPadTailSilence(unittest.TestCase):
    def test_rellena_la_cola_hasta_la_duracion_objetivo(self):
        arr = _speech(1.0)

        out = pad_tail_silence(arr, RATE, 1.5)

        self.assertEqual(out.shape[-1], int(1.5 * RATE))
        self.assertTrue(np.all(out[..., -int(0.5 * RATE):] == 0.0))
        self.assertTrue(np.all(out[..., :int(1.0 * RATE)] == 0.5))

    def test_no_recorta_si_ya_es_mas_largo(self):
        arr = _speech(2.0)

        out = pad_tail_silence(arr, RATE, 1.5)

        self.assertEqual(out.shape, arr.shape)

    def test_conserva_la_forma_estereo(self):
        arr = np.concatenate([_speech(1.0), _speech(1.0)], axis=0)

        out = pad_tail_silence(arr, RATE, 1.5)

        self.assertEqual(out.shape[0], 2)
        self.assertEqual(out.shape[-1], int(1.5 * RATE))
        self.assertTrue(np.all(out[:, -int(0.5 * RATE):] == 0.0))

    def test_no_hace_nada_con_objetivo_invalido(self):
        arr = _speech(1.0)

        self.assertIs(pad_tail_silence(arr, RATE, 0), arr)
        self.assertIs(pad_tail_silence(arr, 0, 1.5), arr)


class TestSynthesizeTailPadding(unittest.TestCase):
    def _synth(self, tts_seconds, orig_duration, max_allowed_dur=None):
        def fake_tts(text, lang, speaker, **kwargs):
            return _speech(tts_seconds), RATE

        return synthesize_segment_audio(
            text="Hola mundo.",
            lang="es",
            speaker="default",
            orig_duration=orig_duration,
            sync_to_original=True,
            max_allowed_dur=max_allowed_dur,
            tts_fn=fake_tts,
        )

    def test_rellena_el_hueco_cuando_el_tts_es_mas_corto(self):
        arr, rate, raw_dur, final_dur, _tag = self._synth(1.90, 2.0, 2.0)

        self.assertAlmostEqual(raw_dur, 1.90, places=3)
        self.assertAlmostEqual(final_dur, 2.0, places=3)
        self.assertEqual(arr.shape[-1], int(2.0 * RATE))
        self.assertTrue(np.all(arr[..., -int(0.10 * RATE):] == 0.0))

    def test_no_rellena_mas_alla_del_limite_del_siguiente_clip(self):
        arr, rate, _raw_dur, final_dur, _tag = self._synth(1.90, 2.0, 1.95)

        self.assertAlmostEqual(final_dur, 1.95, places=3)
        self.assertEqual(arr.shape[-1], int(1.95 * RATE))

    def test_no_rellena_si_el_tts_ya_es_mas_largo(self):
        arr, rate, raw_dur, final_dur, _tag = self._synth(2.20, 2.0, 2.65)

        self.assertAlmostEqual(raw_dur, 2.20, places=3)
        self.assertAlmostEqual(final_dur, 2.20, places=3)
        self.assertEqual(arr.shape[-1], int(2.20 * RATE))


if __name__ == "__main__":
    unittest.main()
