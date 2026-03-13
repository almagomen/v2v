from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import create_db_and_tables
from app.api import projects, export


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="API para traducción y doblaje de videos con IA",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(export.router, prefix="/api", tags=["export"])


@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
