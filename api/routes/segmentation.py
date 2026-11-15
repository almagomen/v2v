"""Banco de cortes: simular una variación de segmentación y aplicarla al video."""

from fastapi import APIRouter, HTTPException

from api.routes.files import _get_video_folder
from api.schemas import (
    SegmentationApplyRequest,
    SegmentationApplyResponse,
    SegmentationPreviewRequest,
    SegmentationPreviewResponse,
)
from src.segmentation_apply import apply_segmentation
from src.segmentation_preview import simulate

router = APIRouter(prefix="/api", tags=["segmentation"])


@router.post(
    "/job/{job_id}/segmentation/preview/{video_index}",
    response_model=SegmentationPreviewResponse,
)
def preview_segmentation(
    job_id: str,
    video_index: int,
    req: SegmentationPreviewRequest,
):
    """
    Re-agrupa las palabras ya transcritas con los parámetros pedidos y devuelve
    la segmentación propuesta, el diff contra la actual y las métricas de ambas.

    Es read-only: no escribe `result.json`, no corta audio y no llama a ningún
    modelo. Mover un slider y volver a pedirlo cuesta milisegundos.
    """
    folder = _get_video_folder(job_id, video_index)
    try:
        return simulate(folder, req.params)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/job/{job_id}/segmentation/apply/{video_index}",
    response_model=SegmentationApplyResponse,
)
def apply_segmentation_route(
    job_id: str,
    video_index: int,
    req: SegmentationApplyRequest,
):
    """
    Aplica la variación al video abierto: re-corta `Seqs_src`, re-sincroniza o
    re-sintetiza `Seqs_trg`, reescribe `result.json` y recalcula el QA.

    Solo toca la carpeta de ese video. El timeline lo reconstruye el frontend a
    partir de los `segments` devueltos.
    """
    folder = _get_video_folder(job_id, video_index)
    try:
        return apply_segmentation(folder, req.params, req.mode)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
