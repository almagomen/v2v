"""WebSocket manager for real-time job progress and streaming logs."""

import asyncio
import json
import logging
import threading
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger("v2v.websocket")


class ConnectionManager:
    """Administra conexiones WebSocket por job_id con soporte thread-safe."""

    def __init__(self):
        self._active_connections: dict[str, set[WebSocket]] = {}
        self._lock = threading.Lock()
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Registra el loop principal de FastAPI para permitir dispatch desde hilos secundarios."""
        self._main_loop = loop

    async def connect(self, websocket: WebSocket, job_id: str) -> None:
        await websocket.accept()
        with self._lock:
            if job_id not in self._active_connections:
                self._active_connections[job_id] = set()
            self._active_connections[job_id].add(websocket)
        logger.info(f"WebSocket conectado al job {job_id} (total: {len(self._active_connections[job_id])})")

    def disconnect(self, websocket: WebSocket, job_id: str) -> None:
        with self._lock:
            if job_id in self._active_connections:
                self._active_connections[job_id].discard(websocket)
                if not self._active_connections[job_id]:
                    del self._active_connections[job_id]
        logger.info(f"WebSocket desconectado del job {job_id}")

    async def _send_to_sockets(self, sockets: list[WebSocket], job_id: str, payload_text: str) -> None:
        dead_sockets: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(payload_text)
            except Exception:
                dead_sockets.append(ws)

        if dead_sockets:
            with self._lock:
                if job_id in self._active_connections:
                    for ws in dead_sockets:
                        self._active_connections[job_id].discard(ws)

    def broadcast_to_job(self, job_id: str, message: dict[str, Any]) -> None:
        """Envío thread-safe llamado desde cualquier hilo de ejecución (síncrono o worker thread)."""
        with self._lock:
            sockets = list(self._active_connections.get(job_id, set()))

        if not sockets:
            return

        payload_text = json.dumps(message, ensure_ascii=False)

        # Si tenemos loop principal de asyncio registrado, usamos run_coroutine_threadsafe
        if self._main_loop and self._main_loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_to_sockets(sockets, job_id, payload_text),
                    self._main_loop,
                )
            except Exception as e:
                logger.warning(f"Error al enviar mensaje por WebSocket: {e}")
        else:
            # Fallback en caso de estar en el hilo principal
            try:
                current_loop = asyncio.get_event_loop()
                if current_loop.is_running():
                    current_loop.create_task(self._send_to_sockets(sockets, job_id, payload_text))
            except Exception:
                pass


ws_manager = ConnectionManager()
