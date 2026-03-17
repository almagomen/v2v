"""In-memory job store for v2v processing."""
import threading
import uuid
from typing import Any

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


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
            "error": None,
        }
    return job_id


def update_job(job_id: str, **kwargs) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def append_log(job_id: str, text: str) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["log"] = (_jobs[job_id].get("log") or "") + text


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)
