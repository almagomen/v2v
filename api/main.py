"""
v2v FastAPI backend for OpenReel integration.
Serves the API and optionally static files (OpenReel build).
"""
import os
from pathlib import Path

# Parche de compatibilidad para anyio/typing_extensions en entornos como Kaggle/Colab
try:
    import typing_extensions
    if not hasattr(typing_extensions, "sentinel"):
        typing_extensions.sentinel = getattr(typing_extensions, "Sentinel", object())
except Exception:
    pass

import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import process, files, regenerate, speakers, share, transcribe_audio, render, video_ops, segments
from api.websocket_manager import ws_manager
from api.job_store import get_job

app = FastAPI(
    title="v2v API",
    description="Video2Video pipeline API for OpenReel",
    version="0.1.0",
)

# CORS for frontend (Colab ngrok, localhost, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_running_loop()
    ws_manager.set_event_loop(loop)

app.include_router(process.router)
app.include_router(files.router)
app.include_router(regenerate.router)
app.include_router(speakers.router)
app.include_router(share.router)
app.include_router(transcribe_audio.router)
app.include_router(render.router)
app.include_router(video_ops.router)
app.include_router(segments.router)


@app.websocket("/ws/job/{job_id}")
async def websocket_job_endpoint(websocket: WebSocket, job_id: str):
    """Canal WebSocket para streaming bidireccional de logs y estado en tiempo real."""
    await ws_manager.connect(websocket, job_id)
    current_job = get_job(job_id)
    if current_job:
        try:
            await websocket.send_json({
                "type": "job_snapshot",
                "job_id": job_id,
                "data": current_job,
            })
        except Exception:
            pass

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, job_id)
    except Exception:
        ws_manager.disconnect(websocket, job_id)


@app.get("/health")
def health():
    return {"status": "ok"}


# Mount OpenReel static files if dist exists (must be last - catch-all)
_openreel_dist = Path(__file__).resolve().parent.parent / "openreel" / "apps" / "web" / "dist"
if _openreel_dist.exists():
    app.mount("/", StaticFiles(directory=str(_openreel_dist), html=True), name="openreel")
else:
    @app.get("/")
    def root():
        return {"message": "v2v API", "docs": "/docs"}
