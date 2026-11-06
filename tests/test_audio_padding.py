"""Pruebas del reparto de silencio en los valles internos del TTS."""
import unittest

import numpy as np

from src.audio_utils import distribute_silence_padding, trim_edge_silence

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


class TestTrimEdgeSilence(unittest.TestCase):
    def test_recorta_aire_largo_al_inicio_y_al_final(self):
        arr = np.concatenate([
            _silence(0.50), _speech(2.0), _silence(1.00),
        ], axis=-1)

        out = trim_edge_silence(arr, RATE)

        self.assertLess(out.shape[-1], arr.shape[-1])
        # Queda voz y solo los márgenes de seguridad (80 ms + 60 ms).
        expected = int((2.0 + 0.08 + 0.06) * RATE)
        self.assertAlmostEqual(out.shape[-1], expected, delta=2)

    def test_conserva_pausas_internas(self):
        arr = np.concatenate([
            _silence(0.50), _speech(1.0), _silence(0.80), _speech(1.0), _silence(0.50),
        ], axis=-1)

        out = trim_edge_silence(arr, RATE)

        runs = _silence_runs(out)
        self.assertTrue(any(abs(run - 0.80) < 0.03 for run in runs), runs)

    def test_no_recorta_silencios_menores_al_minimo(self):
        arr = np.concatenate([
            _silence(0.05), _speech(1.0), _silence(0.05),
        ], axis=-1)

        out = trim_edge_silence(arr, RATE)

        self.assertEqual(out.shape, arr.shape)

    def test_no_recorta_un_clip_sin_voz(self):
        arr = _silence(1.0)

        out = trim_edge_silence(arr, RATE)

        self.assertEqual(out.shape, arr.shape)

    def test_no_deja_un_clip_demasiado_corto(self):
        arr = np.concatenate([
            _silence(0.50), _speech(0.15), _silence(0.50),
        ], axis=-1)

        out = trim_edge_silence(arr, RATE)

        self.assertGreaterEqual(out.shape[-1], int(0.10 * RATE))
        self.assertGreater(out.shape[-1], 0)


if __name__ == "__main__":
    unittest.main()
