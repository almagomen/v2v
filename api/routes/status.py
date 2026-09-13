"""
Endpoint WebSocket para streaming de logs en tiempo real.
"""
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from api.routes.pipeline import _get_job

router = APIRouter(prefix="/api", tags=["status"])


@router.websocket("/ws/logs/{job_id}")
async def websocket_logs(websocket: WebSocket, job_id: str):
    """Transmite logs en tiempo real para un job dado."""
    await websocket.accept()
    try:
        job = _get_job(job_id)
    except Exception:
        await websocket.send_json({"type": "error", "message": f"Job {job_id} no encontrado"})
        await websocket.close()
        return

    # Enviar logs iniciales acumulados
    for log_line in job.get("logs", []):
        await websocket.send_json({
            "type": "log",
            "line": log_line,
            "status": job.get("status"),
            "progress": job.get("progress", 0.0),
        })

    # Si ya finalizó
    if job.get("status") in ("completed", "failed"):
        await websocket.send_json({
            "type": "finished",
            "status": job.get("status"),
            "progress": job.get("progress", 1.0),
            "error": job.get("error"),
        })
        await websocket.close()
        return

    # Escuchar log_queue en loop asíncrono sin bloquear
    log_queue = job.get("log_queue")
    loop = asyncio.get_running_loop()

    try:
        while True:
            # Esperar nuevo mensaje de log en thread pool para no bloquear el event loop
            line = await loop.run_in_executor(None, log_queue.get)
            if line is None:
                # Señal de fin
                await websocket.send_json({
                    "type": "finished",
                    "status": job.get("status"),
                    "progress": job.get("progress", 1.0),
                    "error": job.get("error"),
                })
                break

            await websocket.send_json({
                "type": "log",
                "line": line,
                "status": job.get("status"),
                "progress": job.get("progress", 0.0),
                "step": job.get("current_step", ""),
            })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
