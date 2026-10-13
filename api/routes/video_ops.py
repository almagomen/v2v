from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import pickle
import shutil
from src.config import QUEUE_DIR
from api.job_store import _jobs, _lock, _save_job_to_disk

router = APIRouter(prefix="/api", tags=["video"])


def _find_folder_to_delete(folder_name: str | None, url: str | None) -> tuple[Path | None, list[str]]:
    """
    Localiza la carpeta física en QUEUE_DIR por URL o por nombre de carpeta.
    Retorna la ruta de la carpeta si existe y los job_ids afectados.
    """
    affected_job_ids: list[str] = []

    # 1. Buscar en jobs activos en memoria por URL
    if url:
        with _lock:
            for j_id, j_data in _jobs.items():
                videos = j_data.get("videos", [])
                matching_vids = [v for v in videos if v.get("url") == url]
                if matching_vids:
                    affected_job_ids.append(j_id)
                    for v in matching_vids:
                        v_path = v.get("video_path")
                        if v_path:
                            cand = Path(v_path).parent
                            if cand.exists() and cand.is_dir() and QUEUE_DIR.resolve() in cand.resolve().parents:
                                return cand, affected_job_ids

    # 2. Buscar en QUEUE_DIR escaneando result.pkl si hay url
    if url:
        for cand in QUEUE_DIR.glob("*"):
            if not cand.is_dir():
                continue
            pkl = cand / "result.pkl"
            if pkl.exists():
                try:
                    with open(pkl, "rb") as f:
                        data = pickle.load(f)
                        # data[2] es cached_url en la tupla guardada por pipeline.py
                        if len(data) >= 3 and data[2] == url:
                            return cand, affected_job_ids
                except Exception:
                    pass

    # 3. Si se pasó folder_name, sanitizar y buscar
    if folder_name:
        clean = Path(folder_name).name.strip()
        clean = clean.replace("..", "").replace("/", "").replace("\\", "").strip()
        if clean:
            direct = QUEUE_DIR / clean
            if direct.exists() and direct.is_dir():
                return direct, affected_job_ids
            # Búsqueda insensible a mayúsculas/minúsculas
            clean_lower = clean.lower()
            for cand in QUEUE_DIR.glob("*"):
                if cand.is_dir() and cand.name.lower() == clean_lower:
                    return cand, affected_job_ids

    return None, affected_job_ids


@router.delete("/video")
@router.delete("/video/{folder_name:path}")
def delete_video_folder(
    folder_name: str | None = None,
    url: str | None = Query(None),
):
    """
    Borra físicamente la carpeta de un vídeo en QUEUE_DIR y limpia su estado en los jobs.
    Acepta folder_name, url o ambos. Es idempotente: si no existe, devuelve OK.
    """
    # Si folder_name parece una URL (ej. "https:..." o contiene "youtube.com"), usarla como URL
    if folder_name and ("http://" in folder_name or "https://" in folder_name or "youtube.com" in folder_name):
        if not url:
            url = folder_name
        folder_name = None

    folder, affected_job_ids = _find_folder_to_delete(folder_name, url)

    # Limpiar el video de los jobs en memoria para que no vuelva a aparecer en polling
    if url:
        with _lock:
            for j_id, j_data in _jobs.items():
                changed = False
                if "videos" in j_data:
                    old_len = len(j_data["videos"])
                    j_data["videos"] = [v for v in j_data["videos"] if v.get("url") != url]
                    if len(j_data["videos"]) != old_len:
                        changed = True
                if "url_states" in j_data:
                    old_len = len(j_data["url_states"])
                    j_data["url_states"] = [s for s in j_data["url_states"] if s.get("url") != url]
                    if len(j_data["url_states"]) != old_len:
                        changed = True
                if changed:
                    _save_job_to_disk(j_id)

    if not folder or not folder.exists():
        return {
            "status": "ok",
            "message": "Carpeta eliminada o no existía en disco.",
        }

    # Seguridad: asegurar que la carpeta resuelta esté estrictamente dentro de QUEUE_DIR
    try:
        resolved = folder.resolve()
        if QUEUE_DIR.resolve() not in resolved.parents:
            raise HTTPException(status_code=400, detail="Ruta de carpeta no permitida")
        shutil.rmtree(resolved)
        return {
            "status": "ok",
            "message": f"Carpeta '{resolved.name}' eliminada correctamente del disco.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo borrar la carpeta: {str(e)}")
