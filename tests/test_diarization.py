"""
Asignación de hablantes por palabra (post-reescritura sin `crop` por palabra).

Ejecutar desde la raíz del repo:
    python -m unittest tests.test_diarization -v
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.diarization import assign_speakers_by_word


class _Turns:
    def __init__(self, turns: list[tuple[float, float, str]]):
        self._turns = turns

    def itertracks(self, yield_label: bool = False):
        for start, end, label in self._turns:
            yield SimpleNamespace(start=start, end=end), "track", label


def _segment(start: float, end: float, words: list[tuple[float, float, str]] | None = None) -> dict:
    seg = {"start": start, "end": end, "text": " ".join(w[2] for w in words) if words else "texto"}
    if words:
        seg["words"] = [{"word": w, "start": s, "end": e} for s, e, w in words]
    return seg


class TestSpeakerAssignment(unittest.TestCase):
    def test_asigna_por_solape_de_palabra(self):
        diar = _Turns([(0.0, 2.0, "SPEAKER_00"), (2.0, 4.0, "SPEAKER_01")])
        segs = [_segment(0.5, 3.5, [(0.6, 1.0, "a"), (1.9, 2.4, "b"), (3.0, 3.4, "c")])]
        out = assign_speakers_by_word(segs, diar)

        self.assertEqual([w["speaker"] for w in out[0]["words"]], ["SPEAKER_00", "SPEAKER_01", "SPEAKER_01"])
        # 01 acumula 0.5 + 0.4 = 0.9 s frente a 0.4 s del 00
        self.assertEqual(out[0]["speaker"], "SPEAKER_01")

    def test_palabra_entre_dos_turnos_gana_el_de_mayor_solape(self):
        diar = _Turns([(0.0, 1.0, "SPEAKER_00"), (1.0, 2.0, "SPEAKER_01")])
        segs = [_segment(0.8, 1.6, [(0.8, 1.3, "x")])]
        out = assign_speakers_by_word(segs, diar)
        self.assertEqual(out[0]["words"][0]["speaker"], "SPEAKER_01")

    def test_sin_diarizacion_todo_unknown(self):
        segs = [_segment(0.0, 1.0, [(0.0, 1.0, "a")])]
        out = assign_speakers_by_word(segs, None)
        self.assertEqual(out[0]["speaker"], "UNKNOWN")
        self.assertEqual(out[0]["words"][0]["speaker"], "UNKNOWN")

    def test_segmento_sin_palabras_usa_su_rango(self):
        diar = _Turns([(0.0, 1.0, "SPEAKER_00")])
        out = assign_speakers_by_word([_segment(0.2, 0.8)], diar)
        self.assertEqual(len(out[0]["words"]), 1)
        self.assertEqual(out[0]["speaker"], "SPEAKER_00")

    def test_turnos_fuera_del_segmento_no_interfieren(self):
        diar = _Turns([(0.0, 0.4, "SPEAKER_00"), (5.0, 6.0, "SPEAKER_01")])
        segs = [_segment(1.0, 2.0, [(1.1, 1.9, "a")])]
        out = assign_speakers_by_word(segs, diar)
        self.assertEqual(out[0]["speaker"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
