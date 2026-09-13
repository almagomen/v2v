"""
Servidor FastAPI principal de V2V.
Expone el pipeline como API REST para integración con OpenCut u otros frontends.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import HealthResponse
from api.routes.pipeline import router as pipeline_router
from api.routes.projects import router as projects_router
from api.routes.status import router as status_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Carga modelos pesados al iniciar el servidor."""
    print("🚀 V2V API Server iniciando...")
    try:
        from src.config import DEVICE
        print(f"   Device: {DEVICE}")
    except Exception as e:
        print(f"⚠️ Config no disponible: {e}")
    yield
    print("👋 V2V API Server cerrando...")


app = FastAPI(
    title="V2V Pipeline API",
    description="API REST para el pipeline Video2Video: descarga, transcripción, traducción, TTS y render.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — permitir acceso desde cualquier origen (necesario para OpenCut frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar routers
app.include_router(pipeline_router)
app.include_router(projects_router)
app.include_router(status_router)


@app.get("/", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check del servidor."""
    try:
        from src.config import DEVICE
        import torch
        return HealthResponse(
            status="ok",
            gpu_available=torch.cuda.is_available(),
            device=DEVICE,
        )
    except ImportError:
        return HealthResponse(status="ok", gpu_available=False, device="unknown")


# ── Punto de entrada para ejecución directa ────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
