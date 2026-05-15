"""
v2v FastAPI backend for OpenReel integration.
Serves the API and optionally static files (OpenReel build).
"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import process, files, regenerate, speakers, share, transcribe_audio, render, video_ops, segments

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

app.include_router(process.router)
app.include_router(files.router)
app.include_router(regenerate.router)
app.include_router(speakers.router)
app.include_router(share.router)
app.include_router(transcribe_audio.router)
app.include_router(render.router)
app.include_router(video_ops.router)
app.include_router(segments.router)


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
