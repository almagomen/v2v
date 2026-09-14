"""
Construye un proyecto completo en formato OpenCut a partir de los resultados de V2V.
Genera pistas de:
- Video original (desde v2v_assets.json o primer .mp4 encontrado)
- Segmentos TTS individuales alineados por tiempo (Seqs_trg/)
- Instrumental / efectos (no_vocals.wav)
- Subtítulos / texto traducido con timestamps (desde result.pkl)
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


def _load_pkl(project_dir: Path):
    """
    Carga result.pkl con soporte para 6 campos (legacy) y 7 campos (con info de yt-dlp).
    Returns: (texts, output_name, url, result, transcription, diarization, info)
    """
    pkl_path = project_dir / "result.pkl"
    if not pkl_path.exists():
        raise FileNotFoundError(f"No se encontró result.pkl en {project_dir}")

    with open(pkl_path, "rb") as f:
        texts, output_name, url, result, transcription, diarization, *extra = pickle.load(f)

    info = extra[0] if extra and isinstance(extra[0], dict) else {}
    return texts, output_name, url, result, transcription, diarization, info


def _load_assets(project_dir: Path) -> dict:
    """Carga v2v_assets.json si existe."""
    assets_file = project_dir / "v2v_assets.json"
    if not assets_file.exists():
        return {}
    try:
        import json
        return json.loads(assets_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_opencut_project(
    project_dir: Path,
    base_api_url: str = "",
) -> OpenCutProject:
    """
    Construye un OpenCutProject a partir de la carpeta de un proyecto V2V procesado.
    `base_api_url` es el prefijo para servir los archivos (ej. 'http://localhost:8000').
    """
    project_id = project_dir.name
    now_iso = datetime.now(timezone.utc).isoformat()

    file_url_base = (
        f"{base_api_url.rstrip('/')}/api/projects/{project_id}/files"
        if base_api_url
        else f"/api/projects/{project_id}/files"
    )

    # --- Cargar datos del proyecto ---
    texts, output_name, url, result, transcription, diarization, yt_info = _load_pkl(project_dir)
    assets = _load_assets(project_dir)

    media_assets: list[OpenCutMediaAsset] = []
    tracks: list[OpenCutTrack] = []

    # --- 1. Video principal ---
    # Prioridad: v2v_assets.json["merged"] > primer .mp4 en la carpeta
    video_file = None
    if assets.get("merged"):
        video_file = Path(assets["merged"])
        if not video_file.exists():
            video_file = None

    if not video_file:
        mp4_files = [p for p in project_dir.glob("*.mp4") if not p.name.startswith("_")]
        if mp4_files:
            video_file = mp4_files[0]

    video_asset = None
    if video_file:
        video_asset = OpenCutMediaAsset(
            id=f"media_video_{uuid.uuid4().hex[:8]}",
            name=video_file.name,
            type="video",
            url=f"{file_url_base}/{video_file.name}",
        )
        media_assets.append(video_asset)

    # --- Calcular duración total del video ---
    total_duration = 0.0
    if yt_info and yt_info.get("duration"):
        total_duration = float(yt_info["duration"])

    if total_duration == 0.0 and texts:
        try:
            total_duration = float(texts[-1]["end"]) + 1.0
        except Exception:
            pass

    if total_duration == 0.0:
        total_duration = 60.0  # Fallback 1 min

    # --- 2. Audio: Voces clonadas (segmentos individuales de Seqs_trg/) ---
    seqs_trg = project_dir / "Seqs_trg"
    tts_segments = sorted(seqs_trg.glob("tts_*.wav")) if seqs_trg.exists() else []

    # Mapa de segmentos TTS desde el manifiesto de activos
    asset_segments = assets.get("segments", {})

    # Si hay segmentos TTS individuales, crear una pista por segmento (timeline preciso)
    if tts_segments and texts:
        tts_elements: list[OpenCutTimelineElement] = []

        for i, text_seg in enumerate(texts):
            seq_num = i + 1
            seg_start = float(text_seg.get("start", 0))
            seg_end = float(text_seg.get("end", seg_start + 1))
            seg_dur = max(0.1, seg_end - seg_start)

            # Buscar el archivo de segmento TTS correspondiente
            seg_file: Path | None = None

            # Primero buscar en manifiesto
            if str(seq_num) in asset_segments:
                candidate = Path(asset_segments[str(seq_num)])
                if candidate.exists():
                    seg_file = candidate

            # Fallback: buscar por patrón en Seqs_trg
            if not seg_file:
                patterns = [
                    f"tts_*_{seq_num:03d}.wav",
                    f"tts_*_{seq_num:04d}.wav",
                    f"vocals_{seq_num:03d}.wav",
                    f"vocals_{seq_num:04d}.wav",
                ]
                for pat in patterns:
                    found = list(seqs_trg.glob(pat))
                    if found:
                        seg_file = found[0]
                        break

            if seg_file:
                # Registrar como media asset
                seg_media_id = f"media_tts_{seq_num}_{uuid.uuid4().hex[:6]}"
                seg_rel_path = f"Seqs_trg/{seg_file.name}"
                seg_asset = OpenCutMediaAsset(
                    id=seg_media_id,
                    name=seg_file.name,
                    type="audio",
                    url=f"{file_url_base}/{seg_rel_path}",
                )
                media_assets.append(seg_asset)

                speaker = text_seg.get("speaker", "")
                tts_elements.append(
                    OpenCutTimelineElement(
                        id=f"elem_tts_{seq_num}_{uuid.uuid4().hex[:6]}",
                        mediaId=seg_media_id,
                        name=f"{speaker} – {text_seg.get('text', '')[:40]}",
                        type="audio",
                        startTime=seg_start,
                        duration=seg_dur,
                        volume=1.0,
                    )
                )

        if tts_elements:
            tracks.append(
                OpenCutTrack(
                    id=f"track_tts_{uuid.uuid4().hex[:6]}",
                    name="Voz Doblada (TTS por segmento)",
                    type="audio",
                    elements=tts_elements,
                )
            )
    else:
        # Fallback: vocals_es.wav como pista completa
        vocals_es_file = project_dir / "vocals_es.wav"
        if vocals_es_file.exists():
            vocals_asset = OpenCutMediaAsset(
                id=f"media_vocals_es_{uuid.uuid4().hex[:8]}",
                name="Voces Dobladas (ES)",
                type="audio",
                url=f"{file_url_base}/vocals_es.wav",
            )
            media_assets.append(vocals_asset)
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

    # --- 3. Pista de Video ---
    if video_asset:
        tracks.insert(
            0,
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
            ),
        )

    # --- 4. Instrumental / Background ---
    no_vocals_path = (
        Path(assets["no_vocals"])
        if assets.get("no_vocals")
        else project_dir / "no_vocals.wav"
    )
    if no_vocals_path.exists():
        no_vocals_asset = OpenCutMediaAsset(
            id=f"media_no_vocals_{uuid.uuid4().hex[:8]}",
            name="Música de Fondo / Instrumental",
            type="audio",
            url=f"{file_url_base}/no_vocals.wav",
        )
        media_assets.append(no_vocals_asset)
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

    # --- 5. Pista de Subtítulos ---
    if texts:
        text_elements = []
        for i, seg in enumerate(texts):
            start = float(seg.get("start", 0))
            end = float(seg.get("end", start + 1))
            text_content = str(seg.get("text", ""))
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

    return OpenCutProject(
        version=1,
        metadata=OpenCutMetadata(
            id=project_id,
            name=output_name or project_dir.name,
            duration=total_duration,
            createdAt=now_iso,
            updatedAt=now_iso,
        ),
        settings=OpenCutProjectSettings(),
        scenes=[main_scene],
        mediaAssets=media_assets,
    )
