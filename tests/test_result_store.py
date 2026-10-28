"""Tests de integridad de caché y persistencia de QA en result.json.

Cubren la decisión de producto del gate QA: un build degradado sigue siendo caché
válida (reprocesar cuesta minutos), pero un result.json sin texto real no lo es.
"""

import tempfile
import unittest
from pathlib import Path

from src.result_store import (
    create_segment_entry,
    is_complete_result,
    load_result,
    save_result,
    update_result_qa,
)


def _valid_result() -> dict:
    return {
        "output_name": "video_doblado",
        "source_lang": "pt",
        "segments": [{"seg": 1, "text": "Hola mundo", "start": 0.0, "end": 1.2}],
    }


class TestIsCompleteResult(unittest.TestCase):
    def test_none_y_vacio(self):
        self.assertFalse(is_complete_result(None))
        self.assertFalse(is_complete_result({}))

    def test_sin_output_name(self):
        data = _valid_result()
        data.pop("output_name")
        self.assertFalse(is_complete_result(data))

    def test_sin_segmentos(self):
        data = _valid_result()
        data["segments"] = []
        self.assertFalse(is_complete_result(data))

    def test_segmentos_sin_texto(self):
        """Job que murió entre STT y TTS: estructura presente, contenido vacío."""
        data = _valid_result()
        data["segments"] = [{"seg": 1, "text": "", "start": 0.0, "end": 1.0}]
        self.assertFalse(is_complete_result(data))

    def test_segmento_no_dict_se_ignora(self):
        data = _valid_result()
        data["segments"] = ["basura", {"seg": 2, "text": "válido"}]
        self.assertTrue(is_complete_result(data))

    def test_valido(self):
        self.assertTrue(is_complete_result(_valid_result()))

    def test_qa_fallido_no_invalida_cache(self):
        """Decisión: un build degradado se sirve desde caché y se avisa, no se reprocesa."""
        data = _valid_result()
        data["qa"] = {"passed": False, "failures": [{"metric": "tempo_p95"}]}
        self.assertTrue(is_complete_result(data))


class TestPersistenciaQA(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_update_result_qa_conserva_resto(self):
        save_result(self.folder, _valid_result())
        update_result_qa(self.folder, {"version": 1, "passed": True, "failures": []})
        data = load_result(self.folder)
        self.assertEqual(data["qa"]["version"], 1)
        self.assertTrue(data["qa"]["passed"])
        self.assertEqual(data["output_name"], "video_doblado")
        self.assertEqual(len(data["segments"]), 1)

    def test_update_result_qa_sin_result_json_no_explota(self):
        update_result_qa(self.folder, {"passed": False})
        self.assertIsNone(load_result(self.folder))


class TestSegmentEntryEstados(unittest.TestCase):
    def test_estado_ok_no_se_persiste(self):
        entry = create_segment_entry(1, 0.0, 1.0, "texto", translation_status="ok")
        self.assertNotIn("translation_status", entry)

    def test_estado_fallido_se_persiste(self):
        entry = create_segment_entry(1, 0.0, 1.0, "texto", translation_status="entity_fail")
        self.assertEqual(entry["translation_status"], "entity_fail")

    def test_entity_fail_se_persiste(self):
        entry = create_segment_entry(1, 0.0, 1.0, "texto", entity_fail=["Ghidra"])
        self.assertEqual(entry["entity_fail"], ["Ghidra"])


if __name__ == "__main__":
    unittest.main()
