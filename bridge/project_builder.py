"""
Construye un proyecto completo en formato OpenCut a partir de los resultados de V2V.
Genera pistas de:
- Video original
- Voz clonada (vocals_es) o segmentos individuales alineados
- Instrumental / efectos (no_vocals)
- Subtítulos / texto traducido con timestamps
"""
from datetime import datetime, timezone
from pathlib import Path
import pickle
import uuid

from bridge.opencut_schema import (
    OpenCutProject,
    OpenCutMetadata,
    OpenCutProjectSettings,
    OpenCutScene,
    OpenCutTrack,
    OpenCutTimelineElement,
    OpenCutMediaAsset,
)


def build_opencut_project(
    project_dir: Path,
    base_api_url: str = "",
) -> OpenCutProject:
    """
    Construye un OpenCutProject a partir de la carpeta de un proyecto V2V procesado.
    `base_api_url` es el prefijo para servir los archivos (ej. 'http://localhost:8000/api/projects/{id}/files').
    """
    project_id = project_dir.name
    now_iso = datetime.now(timezone.utc).isoformat()

    file_url_base = f"{base_api_url.rstrip('/')}/api/projects/{project_id}/files" if base_api_url else f"/api/projects/{project_id}/files"

    media_assets: list[OpenCutMediaAsset] = []
    tracks: list[OpenCutTrack] = []

    # 1. Buscar video (output renderizado o video original descargado)
    mp4_files = list(project_dir.glob("*.mp4"))
    video_asset = None
    video_file = None
    if mp4_files:
        # Preferir el video renderizado con el nombre del proyecto o el más reciente
        video_file = mp4_files[0]
        video_asset = OpenCutMediaAsset(
            id=f"media_video_{uuid.uuid4().hex[:8]}",
            name=video_file.name,
            type="video",
            url=f"{file_url_base}/{video_file.name}",
        )
        media_assets.append(video_asset)

    # 2. Buscar audios: vocals_es.wav y no_vocals.wav
    vocals_es_file = project_dir / "vocals_es.wav"
    vocals_asset = None
    if vocals_es_file.exists():
        vocals_asset = OpenCutMediaAsset(
            id=f"media_vocals_es_{uuid.uuid4().hex[:8]}",
            name="Voces Dobladas (ES)",
            type="audio",
            url=f"{file_url_base}/vocals_es.wav",
        )
        media_assets.append(vocals_asset)

    no_vocals_file = project_dir / "no_vocals.wav"
    no_vocals_asset = None
    if no_vocals_file.exists():
        no_vocals_asset = OpenCutMediaAsset(
            id=f"media_no_vocals_{uuid.uuid4().hex[:8]}",
            name="Música de Fondo / Instrumental",
            type="audio",
            url=f"{file_url_base}/no_vocals.wav",
        )
        media_assets.append(no_vocals_asset)

    # 3. Cargar textos/segmentos con timestamps si existen
    segments = []
    texts_pkl = project_dir / "texts.pkl"
    if texts_pkl.exists():
        try:
            with open(texts_pkl, "rb") as f:
                segments = pickle.load(f)
        except Exception:
            pass

    # Calcular duración total estimada
    total_duration = 0.0
    if segments:
        try:
            last_seg = segments[-1]
            total_duration = float(last_seg[1]) if isinstance(last_seg, (list, tuple)) and len(last_seg) > 1 else 0.0
        except Exception:
            pass

    if total_duration == 0.0:
        total_duration = 60.0  # Fallback 1 min

    # Pista 1: Video Track
    if video_asset:
        tracks.append(
            OpenCutTrack(
                id=f"track_video_{uuid.uuid4().hex[:6]}",
                name="Pista de Video",
                type="video",
                elements=[
                    OpenCutTimelineElement(
                        id=f"elem_video_{uuid.uuid4().hex[:8]}",
                        mediaId=video_asset.id,
                        name=video_asset.name,
                        type="video",
                        startTime=0.0,
                        duration=total_duration,
                    )
                ],
            )
        )

    # Pista 2: Audio Track - Voces Dobladas en Español
    if vocals_asset:
        tracks.append(
            OpenCutTrack(
                id=f"track_vocals_{uuid.uuid4().hex[:6]}",
                name="Voz Doblada (Español)",
                type="audio",
                elements=[
                    OpenCutTimelineElement(
                        id=f"elem_vocals_{uuid.uuid4().hex[:8]}",
                        mediaId=vocals_asset.id,
                        name=vocals_asset.name,
                        type="audio",
                        startTime=0.0,
                        duration=total_duration,
                        volume=1.0,
                    )
                ],
            )
        )

    # Pista 3: Audio Track - Background Instrumental
    if no_vocals_asset:
        tracks.append(
            OpenCutTrack(
                id=f"track_bg_{uuid.uuid4().hex[:6]}",
                name="Instrumental / Fondo",
                type="audio",
                elements=[
                    OpenCutTimelineElement(
                        id=f"elem_bg_{uuid.uuid4().hex[:8]}",
                        mediaId=no_vocals_asset.id,
                        name=no_vocals_asset.name,
                        type="audio",
                        startTime=0.0,
                        duration=total_duration,
                        volume=0.7,
                    )
                ],
            )
        )

    # Pista 4: Text / Subtitle Track con cada segmento traducido
    if segments:
        text_elements = []
        for i, seg in enumerate(segments):
            # Formato estándar de segment: [start, end, text, ...]
            if isinstance(seg, (list, tuple)) and len(seg) >= 3:
                start = float(seg[0])
                end = float(seg[1])
                text_content = str(seg[2])
                dur = max(0.1, end - start)

                text_elements.append(
                    OpenCutTimelineElement(
                        id=f"elem_sub_{i}_{uuid.uuid4().hex[:6]}",
                        name=f"Sub {i+1}",
                        type="text",
                        startTime=start,
                        duration=dur,
                        text=text_content,
                    )
                )

        if text_elements:
            tracks.append(
                OpenCutTrack(
                    id=f"track_subtitles_{uuid.uuid4().hex[:6]}",
                    name="Subtítulos / Diálogos",
                    type="text",
                    elements=text_elements,
                )
            )

    main_scene = OpenCutScene(
        id=f"scene_{uuid.uuid4().hex[:8]}",
        name="Main scene",
        isMain=True,
        tracks=tracks,
    )

    project_name = project_dir.name
    if video_file:
        project_name = video_file.stem

    return OpenCutProject(
        version=1,
        metadata=OpenCutMetadata(
            id=project_id,
            name=project_name,
            duration=total_duration,
            createdAt=now_iso,
            updatedAt=now_iso,
        ),
        settings=OpenCutProjectSettings(),
        scenes=[main_scene],
        mediaAssets=media_assets,
    )
