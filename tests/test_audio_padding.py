"""Pruebas del reparto de silencio en los valles internos del TTS."""
import unittest
from unittest import mock

import numpy as np

from src.audio_utils import (
    _format_aligned_segment_texts,
    distribute_silence_padding,
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


class TestSyncToOriginal(unittest.TestCase):
    """El clip TTS debe ocupar el mismo tramo que su clip original, sin ceros."""

    @staticmethod
    def _fake_stretch(audio, target_samples, rate):
        """Simula atempo interpolando la voz, sin añadir silencio."""
        n = int(audio.shape[-1])
        idx = np.linspace(0, n - 1, int(target_samples))
        stretched = np.interp(idx, np.arange(n), np.asarray(audio)[0])
        return stretched.reshape(1, -1).astype(np.asarray(audio).dtype)

    def _synth(self, tts_arr, orig_duration, max_allowed_dur=None, patch_stretch=True):
        def fake_tts(text, lang, speaker, **kwargs):
            return tts_arr, RATE

        cm = mock.patch(
            "src.audio_utils.adjust_audio_duration", new=self._fake_stretch
        ) if patch_stretch else mock.patch(
            "src.audio_utils.adjust_audio_duration",
            new=mock.Mock(side_effect=AssertionError("no debía estirar")),
        )
        with cm:
            return synthesize_segment_audio(
                text="Hola mundo.",
                lang="es",
                speaker="default",
                orig_duration=orig_duration,
                sync_to_original=True,
                max_allowed_dur=max_allowed_dur,
                tts_fn=fake_tts,
            )

    def test_estira_hasta_igualar_el_original_sin_anadir_silencio(self):
        arr, _rate, raw_dur, final_dur, _tag = self._synth(_speech(1.90), 2.0, 2.0)

        self.assertAlmostEqual(raw_dur, 1.90, places=3)
        self.assertAlmostEqual(final_dur, 2.0, places=3)
        self.assertEqual(arr.shape[-1], int(2.0 * RATE))
        # La cola sigue siendo voz estirada, no una cola de ceros.
        self.assertNotEqual(float(arr[..., -1][0]), 0.0)

    def test_no_toca_el_audio_si_ya_es_mas_largo_pero_cabe(self):
        arr, _rate, raw_dur, final_dur, _tag = self._synth(
            _speech(2.20), 2.0, 2.65, patch_stretch=False
        )

        self.assertAlmostEqual(raw_dur, 2.20, places=3)
        self.assertAlmostEqual(final_dur, 2.20, places=3)
        self.assertEqual(arr.shape[-1], int(2.20 * RATE))

    def test_usa_las_pausas_internas_antes_de_estirar(self):
        # 0.8s voz + 0.5s pausa + 0.8s voz = 2.1s; el original son 2.4s.
        # La pausa interna puede crecer 0.3s y llenar el hueco sin atempo.
        tts = np.concatenate(
            [_speech(0.8), _silence(0.5), _speech(0.8)], axis=-1
        )

        arr, _rate, _raw_dur, final_dur, _tag = self._synth(
            tts, 2.4, 2.4, patch_stretch=False
        )

        self.assertAlmostEqual(final_dur, 2.4, places=3)
        self.assertEqual(arr.shape[-1], int(2.4 * RATE))
        self.assertNotEqual(float(arr[..., -1][0]), 0.0)

    def test_suelo_de_estiramiento_sin_relleno_artificial(self):
        # 1.0s de voz para un hueco de 2.0s: el suelo 0.80x solo llega a 1.25s.
        # Se prefiere dejar el hueco real antes que inventar silencio.
        arr, _rate, _raw_dur, final_dur, _tag = self._synth(_speech(1.0), 2.0, 2.0)

        self.assertAlmostEqual(final_dur, 1.25, places=3)
        self.assertEqual(arr.shape[-1], int(1.25 * RATE))
        self.assertNotEqual(float(arr[..., -1][0]), 0.0)


class TestAlignedSegmentTexts(unittest.TestCase):
    """El log no debe repetir la misma frase cuando no hubo traducción."""

    ORIG = (
        "Si tienes una prenda con el escote demasiado holgado, primero identifica "
        "las costuras de los hombros."
    )
    ENHANCED = (
        "[excited] Si tienes una prenda con el escote demasiado holgado, "
        "[short pause] [emphasis] primero identifica las costuras de los hombros."
    )

    def test_sin_traduccion_emite_una_sola_linea_con_el_enhance(self):
        lines = _format_aligned_segment_texts(
            orig_text=self.ORIG,
            final_text=self.ENHANCED,
            source_lang="es",
            target_lang="es",
        )

        self.assertEqual(lines, [self.ENHANCED])

    def test_mismo_texto_con_etiquetas_no_se_confunde_con_traduccion(self):
        # Las etiquetas dejan espacios dobles al quitarlas; sin normalizar,
        # el mismo texto parecía una traducción distinta.
        lines = _format_aligned_segment_texts(
            orig_text=self.ORIG,
            final_text=self.ENHANCED,
            source_lang=None,
            target_lang=None,
        )

        self.assertEqual(lines, [self.ENHANCED])

    def test_traduccion_real_muestra_original_y_final(self):
        lines = _format_aligned_segment_texts(
            orig_text="Se o decote estiver largo, marque as costuras.",
            final_text="[excited] Si el escote queda largo, marca las costuras.",
            source_lang="pt",
            target_lang="es",
        )

        self.assertEqual(len(lines), 2)
        self.assertIn("[pt]", lines[0])
        self.assertIn("Se o decote estiver largo", lines[0])
        self.assertIn("[excited]", lines[1])
        self.assertIn("Si el escote queda largo", lines[1])

    def test_idioma_desconocido_compara_el_texto(self):
        lines = _format_aligned_segment_texts(
            orig_text="Hola mundo.",
            final_text="Hola mundo.",
            source_lang=None,
            target_lang=None,
        )

        self.assertEqual(lines, ["Hola mundo."])


if __name__ == "__main__":
    unittest.main()
