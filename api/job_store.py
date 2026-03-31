"""Persistent job store for v2v processing."""

import json
import threading
import uuid
from pathlib import Path
from typing import Any
from src.config import JOBS_DIR

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _job_file(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _save_job_to_disk(job_id: str) -> None:
    """Sincroniza el estado del job con el archivo en disco."""
    if job_id in _jobs:
        try:
            with open(_job_file(job_id), "w", encoding="utf-8") as f:
                json.dump(_jobs[job_id], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error al guardar job {job_id} en disco: {e}")


def _load_jobs_from_disk() -> None:
    """Carga todos los jobs existentes al arrancar y reconcilia estados."""
    if not JOBS_DIR.exists():
        return
    for f in JOBS_DIR.glob("*.json"):
        try:
            job_id = f.stem
            with open(f, "r", encoding="utf-8") as j:
                job_data = json.load(j)

            # Reconciliación de estado: si el job estaba "processing" o "downloading"
            # o "tts" cuando se reinició el servidor, marcarlo como "interrupted"
            status = job_data.get("status", "")
            if status in ("processing", "downloading", "tts", "transcribing"):
                job_data["status"] = "interrupted"
                job_data["message"] = (
                    "El servidor se reinició mientras se procesaba este job. "
                    "Por favor, reinicia el proceso desde el panel V2V."
                )
                # Guardar el estado reconciliado
                with open(f, "w", encoding="utf-8") as j2:
                    json.dump(job_data, j2, indent=2, ensure_ascii=False)

            _jobs[job_id] = job_data
        except Exception:
            pass


def create_job() -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "status": "pending",
            "message": "",
            "progress": 0.0,
            "log": "",
            "output_paths": [],
            "videos": [],
            "url_states": [],
            "error": None,
        }
        _save_job_to_disk(job_id)
    return job_id


def update_job(job_id: str, **kwargs) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)
            _save_job_to_disk(job_id)


def append_log(job_id: str, text: str) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["log"] = (_jobs[job_id].get("log") or "") + text
            _save_job_to_disk(job_id)


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


# Cargar jobs al iniciar el módulo
_load_jobs_from_disk()
