"""Persistent job store for v2v processing."""

import json
import threading
import uuid
from pathlib import Path
from typing import Any
from src.config import JOBS_DIR

try:
    from api.websocket_manager import ws_manager
except ImportError:
    ws_manager = None

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


# ─── Batched Log Writer ─────────────────────────────────────────────────────
# En vez de escribir a disco en cada línea de stdout, acumulamos en memoria
# y flusheamos periódicamente (cada 2s o cada 4KB).

class _LogBuffer:
    """Acumula logs en memoria y flushea a disco de forma eficiente."""

    _FLUSH_INTERVAL = 2.0   # segundos entre flushes automáticos
    _FLUSH_SIZE = 4096       # bytes antes de forzar flush

    def __init__(self):
        self._buffers: dict[str, str] = {}
        self._timer: threading.Timer | None = None
        self._buf_lock = threading.Lock()

    def append(self, job_id: str, text: str) -> None:
        if ws_manager:
            ws_manager.broadcast_to_job(job_id, {"type": "log_chunk", "chunk": text})

        with self._buf_lock:
            self._buffers[job_id] = self._buffers.get(job_id, "") + text
            buf_size = len(self._buffers.get(job_id, ""))

        # Flush inmediato si superó el umbral de tamaño
        if buf_size >= self._FLUSH_SIZE:
            self._flush_job(job_id)
        elif not self._timer:
            self._start_timer()

    def _start_timer(self) -> None:
        self._timer = threading.Timer(self._FLUSH_INTERVAL, self._flush_all)
        self._timer.daemon = True
        self._timer.start()

    def _flush_job(self, job_id: str) -> None:
        with self._buf_lock:
            pending = self._buffers.pop(job_id, "")
        if pending:
            with _lock:
                if job_id in _jobs:
                    _jobs[job_id]["log"] = (_jobs[job_id].get("log") or "") + pending
                    _save_job_to_disk(job_id)

    def _flush_all(self) -> None:
        self._timer = None
        with self._buf_lock:
            job_ids = list(self._buffers.keys())
        for jid in job_ids:
            self._flush_job(jid)

    def flush_sync(self, job_id: str) -> None:
        """Flush síncrono — llamar al final de un job para garantizar que todo se escribió."""
        self._flush_job(job_id)


_log_buffer = _LogBuffer()

# ─── Core Functions ──────────────────────────────────────────────────────────


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
    if ws_manager:
        ws_manager.broadcast_to_job(job_id, {"type": "job_update", "job_id": job_id, "data": kwargs})


def append_log(job_id: str, text: str) -> None:
    """Añade texto al log del job de forma eficiente (batched writes)."""
    _log_buffer.append(job_id, text)


def flush_log(job_id: str) -> None:
    """Flush síncrono del log — llamar al final de un pipeline."""
    _log_buffer.flush_sync(job_id)


def get_job(job_id: str) -> dict | None:
    # Flush pendiente antes de leer para que el log esté actualizado
    _log_buffer.flush_sync(job_id)
    with _lock:
        return _jobs.get(job_id)


# Cargar jobs al iniciar el módulo
_load_jobs_from_disk()
