"""
Módulo centralizado de persistencia de resultados V2V.

Reemplaza completamente el uso de pickle en el proyecto.
Todas las lecturas/escrituras de datos de resultado pasan por aquí.

Archivos gestionados:
  - result.json   → Datos serializables del pipeline (segmentos, info, timings)
  - url_index.json → Índice URL → carpeta para búsqueda O(1) de caché
"""

import json
from pathlib import Path
from typing import Any, Optional

from src.config import QUEUE_DIR

RESULT_FILENAME = "result.json"
URL_INDEX_FILENAME = "url_index.json"


def _serialize_safe(obj: Any) -> Any:
    """Convierte a tipo JSON-serializable cualquier valor problemático."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _serialize_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_safe(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    # Para cualquier otro objeto, intentar convertir a str
    return str(obj)


# ─── result.json ────────────────────────────────────────────────────────────


def load_result(folder: Path) -> Optional[dict]:
    """Lee result.json de la carpeta del job. Retorna None si no existe."""
    json_path = folder / RESULT_FILENAME
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_result(folder: Path, data: dict) -> None:
    """Guarda result.json en la carpeta del job."""
    json_path = folder / RESULT_FILENAME
    folder.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(_serialize_safe(data), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def create_result(
    *,
    url: str,
    output_name: str,
    source_lang: str,
    target_lang: Optional[str],
    segments: list[dict],
    original_segments: list[dict],
    info: dict,
    timings: Optional[dict] = None,
) -> dict:
    """Crea la estructura estándar de result.json."""
    return {
        "version": 2,
        "url": url,
        "output_name": output_name,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "segments": segments,
        "original_segments": original_segments,
        "info": _serialize_safe(info),
        "timings": timings or {},
    }


def update_result_segments(folder: Path, segments: list[dict]) -> None:
    """Actualiza solo los segmentos (texto TTS) en result.json."""
    data = load_result(folder)
    if data is None:
        return
    data["segments"] = segments
    save_result(folder, data)


def update_result_output_name(folder: Path, output_name: str) -> None:
    """Actualiza el output_name (título viral) en result.json."""
    data = load_result(folder)
    if data is None:
        return
    data["output_name"] = output_name
    save_result(folder, data)


def get_result_segments(folder: Path) -> list[dict]:
    """Retorna la lista de segmentos TTS de result.json."""
    data = load_result(folder)
    if data is None:
        return []
    return data.get("segments", [])


def get_result_original_segments(folder: Path) -> list[dict]:
    """Retorna la lista de segmentos STT originales de result.json."""
    data = load_result(folder)
    if data is None:
        return []
    return data.get("original_segments", [])


def get_result_source_lang(folder: Path) -> Optional[str]:
    """Retorna el idioma fuente detectado."""
    data = load_result(folder)
    if data is None:
        return None
    return data.get("source_lang")


# ─── url_index.json ─────────────────────────────────────────────────────────


def _url_index_path() -> Path:
    return QUEUE_DIR / URL_INDEX_FILENAME


def load_url_index() -> dict[str, str]:
    """Carga el índice URL → carpeta. Retorna {} si no existe."""
    idx_path = _url_index_path()
    if not idx_path.exists():
        return {}
    try:
        return json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_url_index(index: dict[str, str]) -> None:
    """Guarda el índice URL → carpeta."""
    idx_path = _url_index_path()
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def register_url(url: str, folder_name: str) -> None:
    """Registra un mapeo URL → nombre_carpeta en el índice."""
    index = load_url_index()
    index[url] = folder_name
    save_url_index(index)


def unregister_url(url: str) -> None:
    """Elimina un mapeo URL del índice."""
    index = load_url_index()
    if url in index:
        del index[url]
        save_url_index(index)


def lookup_folder_by_url(url: str) -> Optional[str]:
    """Busca la carpeta asociada a una URL. Retorna None si no existe."""
    index = load_url_index()
    return index.get(url)
