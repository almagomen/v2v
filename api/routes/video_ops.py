from fastapi import APIRouter, HTTPException
from pathlib import Path
import shutil
from src.config import QUEUE_DIR

router = APIRouter(prefix="/api", tags=["video"])

@router.delete("/video/{folder_name}")
def delete_video_folder(folder_name: str):
    """Borra físicamente la carpeta de un vídeo en QUEUE_DIR."""
    # Seguridad básica para evitar borrar carpetas fuera de QUEUE_DIR
    if ".." in folder_name or folder_name.startswith("/") or folder_name.startswith("\\"):
        raise HTTPException(status_code=400, detail="Nombre de carpeta inválido")

    folder = QUEUE_DIR / folder_name
    if not folder.exists():
        # Si no existe, lo damos por borrado exitosamente (idempotencia)
        return {"status": "ok", "message": "Carpeta ya no existía"}
    
    try:
        shutil.rmtree(folder)
        return {"status": "ok", "message": f"Carpeta {folder_name} borrada correctamente."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo borrar la carpeta: {str(e)}")
