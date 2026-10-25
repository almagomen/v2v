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


def sanitize_video_info(info: dict) -> dict:
    """Extrae únicamente los metadatos esenciales del video, reduciendo el JSON un 97%."""
    if not isinstance(info, dict):
        return {}

    # Obtenemos la mejor miniatura como URL simple
    thumb = info.get("thumbnail")
    if not thumb and isinstance(info.get("thumbnails"), list) and info["thumbnails"]:
        thumb = info["thumbnails"][-1].get("url")

    clean = {
        "id": info.get("id", ""),
        "title": info.get("title") or info.get("fulltitle") or "",
        "duration": info.get("duration", 0),
        "channel": info.get("channel") or info.get("uploader") or "",
        "webpage_url": info.get("webpage_url") or "",
        "thumbnail": thumb or "",
        "width": info.get("width"),
        "height": info.get("height"),
        "fps": info.get("fps"),
        "description": (info.get("description") or "")[:500],
        "_download_time": info.get("_download_time", 0.0),
        "_stems_time": info.get("_stems_time", 0.0),
    }
    return {k: v for k, v in clean.items() if v is not None}


# ─── result.json ────────────────────────────────────────────────────────────


def load_result(folder: Path) -> Optional[dict]:
    """Lee result.json de la carpeta del job. Retorna None si no existe."""
    json_path = folder / RESULT_FILENAME
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "info" in data and isinstance(data["info"], dict):
            # Limpieza transparente de claves masivas si aún estuvieran presentes
            for bloated in ("automatic_captions", "formats", "requested_formats", "thumbnails", "subtitles", "heatmap"):
                data["info"].pop(bloated, None)
        return data
    except Exception:
        return None


def is_complete_result(data: Optional[dict]) -> bool:
    """Verifica si los datos de result.json corresponden a un procesamiento completo (con segmentos e inferencia)."""
    if not isinstance(data, dict):
        return False
    segments = data.get("segments")
    return bool(segments and isinstance(segments, list) and len(segments) > 0 and data.get("output_name"))


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
    original_segments: Optional[list[dict]] = None,
    info: dict,
    timings: Optional[dict] = None,
    assets: Optional[dict] = None,
) -> dict:
    """Crea la estructura estándar unificada de result.json."""
    data = {
        "version": 2,
        "url": url,
        "output_name": output_name,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "segments": segments,
        "info": sanitize_video_info(info),
        "timings": timings or {},
        "assets": assets or {},
    }
    if original_segments is not None:
        data["original_segments"] = original_segments
    return data


def update_result_assets(folder: Path, assets: dict) -> None:
    """Actualiza la sección de activos dentro de result.json."""
    data = load_result(folder)
    if data is None:
        return
    data["assets"] = assets
    save_result(folder, data)



def update_result_segments(folder: Path, segments: list[dict]) -> None:
    """Actualiza solo los segmentos (texto TTS) en result.json."""
    data = load_result(folder)
    if data is None:
        return
    data["segments"] = segments
    save_result(folder, data)


def create_segment_entry(
    seg: int,
    start: float,
    end: float,
    text: str,
    original_text: Optional[str] = None,
    speaker: Optional[str] = None,
    original_speaker: Optional[str] = None,
    phonemes: Optional[dict[str, str]] = None,
    orig_start: Optional[float] = None,
    orig_end: Optional[float] = None,
    orig_duration: Optional[float] = None,
    syllable_count: Optional[int] = None,
    internal_pause_sec: Optional[float] = None,
    **extra,
) -> dict:
    """
    Construye de forma canónica y unificada la estructura de un segmento V2V.
    Preserva las coordenadas del audio original y el generado, sin duplicar texto ni almacenar métricas obsoletas.
    """
    import re
    s_val = round(float(start), 3)
    e_val = round(float(end), 3)
    dur = max(0.1, round(e_val - s_val, 3))

    o_start = round(float(orig_start), 3) if orig_start is not None else s_val
    o_end = round(float(orig_end), 3) if orig_end is not None else e_val
    o_dur = round(float(orig_duration), 3) if orig_duration is not None else max(0.1, round(o_end - o_start, 3))

    resolved_orig = original_text if original_text is not None else text
    clean_text = re.sub(r"\[.*?\]", "", str(text)).strip()

    if syllable_count is None:
        try:
            from src.diarization import count_syllables_approx
            syl_cnt = count_syllables_approx(clean_text)
        except Exception:
            syl_cnt = max(1, int(len(clean_text) / 3))
    else:
        syl_cnt = syllable_count

    clean_phonemes = (
        {str(k).strip(): str(v).strip() for k, v in phonemes.items() if k and v}
        if isinstance(phonemes, dict)
        else {}
    )

    entry = {
        "seg": int(seg),
        "text": str(text),
        "original_text": str(resolved_orig),
        "start": s_val,
        "end": e_val,
        "duration": dur,
        "orig_start": o_start,
        "orig_end": o_end,
        "orig_duration": o_dur,
        "speaker": speaker or "mrbeast",
        "original_speaker": original_speaker or speaker or "SPEAKER_00",
    }
    if syl_cnt:
        entry["syllable_count"] = syl_cnt
    if clean_phonemes:
        entry["phonemes"] = clean_phonemes
    if internal_pause_sec:
        entry["internal_pause_sec"] = float(internal_pause_sec)

    return entry


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
    """Retorna la lista de segmentos STT originales de result.json (reconstrucción unificada)."""
    data = load_result(folder)
    if data is None:
        return []
    if "original_segments" in data and data["original_segments"]:
        return data["original_segments"]
    origs = []
    for s in data.get("segments", []):
        origs.append({
            "seg": s.get("seg"),
            "start": s.get("orig_start", s.get("start", 0.0)),
            "end": s.get("orig_end", s.get("end", 0.0)),
            "duration": s.get("orig_duration", s.get("duration", 0.0)),
            "text": s.get("original_text", s.get("text", "")),
            "original_text": s.get("original_text", s.get("text", "")),
            "speaker": s.get("original_speaker", s.get("speaker", "")),
            "original_speaker": s.get("original_speaker", s.get("speaker", "")),
        })
    return origs


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
