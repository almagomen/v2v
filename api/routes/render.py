"""
Colab FFmpeg render endpoint.
Renders a timeline (single or batch) using ffmpeg server-side.
Includes Catbox upload for shareable links.
"""

import io
import re
import subprocess
import unicodedata
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from api.job_store import get_job
from src.config import QUEUE_DIR, TEMP_DIR
from src.assets import load_assets, update_assets
from src.download import to_safe_name
from src.edit_utils import get_video_bitrate

router = APIRouter(prefix="/api", tags=["render"])


def to_zip_name(text: str, max_len: int = 200) -> str:
    """
    Genera un nombre de archivo apto para ZIP y Windows preservando emojis,
    hashtags y caracteres Unicode.
    Solo elimina los caracteres realmente prohibidos: / \\ : * ? " < > | y controles.
    """
    import re
    # Eliminar caracteres de control (ASCII 0-31, 127)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    # Eliminar caracteres prohibidos en Windows/ZIP
    text = re.sub(r'[/\\:*?"<>|]', "_", text)
    # Colapsar espacios múltiples
    text = re.sub(r" {2,}", " ", text).strip()
    # Limitar longitud
    return text[:max_len].strip() or "video"


# ---------------------------------------------------------------------------
# Catbox upload
# ---------------------------------------------------------------------------


def upload_to_catbox(file_path: Path) -> str:
    """Sube archivo a Catbox (24h). Returns URL o vacío."""
    base = unicodedata.normalize("NFKD", file_path.stem)
    base = base.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-") or "video"
    base = base[:80]
    safe_name = f"{base}{file_path.suffix or '.mp4'}"

    cmd = [
        "curl",
        "-F",
        "reqtype=fileupload",
        "-F",
        "time=24h",
        "-F",
        f"fileToUpload=@{file_path};filename={safe_name}",
        "https://litterbox.catbox.moe/resources/internals/api.php",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    print(f"⚠️ Error al subir a Catbox: {result.stderr}")
    return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_audio(path: Path) -> bool:
    """Check if a media file has at least one audio stream using ffprobe."""
    import subprocess

    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return bool(result.stdout.strip())
    except Exception:
        return False


def _validate_manifest_integrity(folder: Path) -> list[str]:
    """
    Validates that critical assets exist in both manifest and disk.
    Returns list of warnings (missing files).
    """
    assets = load_assets(folder)
    warnings = []

    critical_keys = ["merged", "video_only", "vocals", "no_vocals"]
    for key in critical_keys:
        path_str = assets.get(key)
        if path_str:
            p = Path(path_str)
            if not p.exists():
                warnings.append(f"Asset crítico '{key}' no existe en disco: {path_str}")

    # Verificar segmentos TTS
    segments = assets.get("segments", {})
    if isinstance(segments, dict):
        for seg_idx, seg_path_str in segments.items():
            if seg_path_str:
                p = Path(seg_path_str)
                if not p.exists():
                    warnings.append(
                        f"Segmento TTS #{seg_idx} no existe: {seg_path_str}"
                    )

    return warnings


def _job_folders_from_refs(folder_refs: list[tuple[str, int]]) -> list[Path]:
    """Resolve folders from a list of (job_id, video_index) tuples."""
    folders = []
    for job_id, video_index in folder_refs:
        try:
            folders.append(_job_folder(job_id, video_index))
        except HTTPException:
            continue
    return folders


def _job_folder(job_id: str, video_index: int) -> Path:
    """Resolve the folder for a given job/video_index."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Job {job_id} no encontrado. Esto puede deberse a un reinicio del servidor. "
                "Por favor, reinicia el proceso de inferencia desde el panel V2V."
            ),
        )

    status = job.get("status", "")
    if status == "interrupted":
        raise HTTPException(
            status_code=410,
            detail=(
                f"El job {job_id} fue interrumpido por un reinicio del servidor. "
                "Por favor, reinicia el proceso desde el panel V2V."
            ),
        )

    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video index fuera de rango")
    return Path(videos[video_index]["video_path"]).parent


def _resolve_media_path(
    folder: Path, media_name: str, job_id: str = None, video_index: int = None
) -> Path:
    """
    Resolves a media_name to an absolute path.
    Prioritizes the v2v_assets.json manifest (New Logic).
    """
    # 0. Normalizar media_name para extraer solo el nombre base (el frontend manda Carpeta/Archivo.mp4)
    file_name = Path(media_name).name

    # 1. Cargar manifiesto
    assets = load_assets(folder)

    # 2. Mapeo de nombres genéricos a claves del manifiesto
    name_to_asset_key = {
        "video.mp4": "video_only",
        "instrumental.wav": "no_vocals",
        "audio.wav": "audio_only",
        "vocals.wav": "vocals",
    }

    # Intentar resolver vía manifiesto (usando file_name sanitizado)
    asset_key = name_to_asset_key.get(file_name)
    if asset_key and assets.get(asset_key):
        path = Path(assets[asset_key])
        if path.exists():
            return path
        if asset_key == "video_only" and assets.get("merged"):
            path = Path(assets["merged"])
            if path.exists():
                return path

    segments_map = assets.get("segments", {}) or {}

    # 2.5 Segmentos TTS/gen por índice (antes que búsqueda por basename: evita copias
    # obsoletas en claves sueltas del manifiesto tras upload o regeneración)
    import re

    tts_match = re.search(r"(?:tts_|gen_).*_(\d+)\.wav$", file_name, re.I)
    seg_idx = (
        str(int(tts_match.group(1)))
        if tts_match
        else (file_name if file_name.isdigit() else None)
    )
    if seg_idx:
        seg_path_str = segments_map.get(seg_idx)
        if seg_path_str:
            path = Path(seg_path_str)
            if not path.is_absolute():
                path = folder / path
            if path.exists():
                return path

    # 2.6 Búsqueda exhaustiva en el manifiesto por nombre de archivo
    for val in assets.values():
        if isinstance(val, str) and Path(val).name == file_name:
            p_cand = Path(val)
            if not p_cand.is_absolute():
                p_cand = folder / p_cand
            if p_cand.exists():
                return p_cand

    for seg_path in segments_map.values():
        if isinstance(seg_path, str) and Path(seg_path).name == file_name:
            p_cand = Path(seg_path)
            if not p_cand.is_absolute():
                p_cand = folder / p_cand
            if p_cand.exists():
                return p_cand

    # Fallback solo para rutas absolutas existentes
    p = Path(media_name)
    if p.is_absolute() and p.exists():
        return p

    raise HTTPException(
        status_code=404,
        detail=f"Archivo no encontrado en el manifiesto del job: {media_name}. Por favor, vuelve a procesar el video si es antiguo.",
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TimelineClip(BaseModel):
    type: str  # "video" | "audio"
    media_name: str  # relative path to media file
    start: float  # inPoint (trim start within file, seconds)
    end: float  # outPoint (trim end within file, seconds)
    track_start: float  # position on the timeline (seconds)
    volume: float = 1.0


class RenderTimelineRequest(BaseModel):
    job_id: str
    video_index: int
    clips: list[TimelineClip]
    output_name: str = "export"
    upload_to_catbox: bool = False


class BatchRenderItem(BaseModel):
    job_id: str
    video_index: int
    clips: list[TimelineClip]
    output_name: str


class RenderBatchRequest(BaseModel):
    renders: list[BatchRenderItem]
    zip_name: str = "batch_export"
    upload_to_catbox: bool = False


# ---------------------------------------------------------------------------
# Upload media (pre-upload local files before render)
# ---------------------------------------------------------------------------


@router.post("/render/upload-media/{job_id}/{video_index}")
async def upload_media(
    job_id: str,
    video_index: int,
    file: UploadFile = File(...),
    subfolder: str = Form(default=""),
):
    """Upload a local file into the job folder so it can be included in render."""
    folder = _job_folder(job_id, video_index)

    # Sanitizar subfolder para mantener la estética del sistema de archivos (save_name)
    subfolder_safe = to_safe_name(subfolder) if subfolder else ""
    target_dir = folder / subfolder_safe if subfolder_safe else folder
    target_dir.mkdir(parents=True, exist_ok=True)

    # Sanitizar también el nombre de archivo (preservando extensión)
    raw_name = Path(file.filename or "upload.bin")
    safe_stem = to_safe_name(raw_name.stem)
    safe_filename = f"{safe_stem}{raw_name.suffix}" if raw_name.suffix else safe_stem

    dest = target_dir / safe_filename
    content = await file.read()
    dest.write_bytes(content)

    # Registrar el archivo en el manifiesto para que el renderizador lo encuentre
    update_assets(folder, **{safe_filename: str(dest)})

    return {
        "media_name": f"{subfolder_safe}/{safe_filename}"
        if subfolder_safe
        else safe_filename
    }


@router.get("/render/manifest/{job_id}/{video_index}")
async def get_rendered_manifest(job_id: str, video_index: int):
    """Obtiene el manifiesto v2v_assets.json actual para un video específico."""
    folder = _job_folder(job_id, video_index)
    return load_assets(folder)


# ---------------------------------------------------------------------------
# Single timeline render
# ---------------------------------------------------------------------------


def _build_ffmpeg_cmd(
    clips: list[TimelineClip],
    folder: Path,
    output_path: Path,
    job_id: str = None,
    video_index: int = None,
) -> list[str]:
    """
    Build an ffmpeg command that renders the timeline clips into a single MP4.
    Strategy:
     - All input files are added with -i
     - Video clips are trimmed and set to proper pts offset, then concatenated
     - Audio clips are trimmed and delayed to their track_start, then mixed
    """
    import subprocess

    video_clips = [c for c in clips if c.type == "video"]
    audio_clips = [c for c in clips if c.type == "audio"]

    if not video_clips and not audio_clips:
        raise HTTPException(status_code=400, detail="No hay clips en el timeline")

    inputs: list[str] = []
    filter_parts: list[str] = []
    input_idx = 0
    video_labels: list[str] = []
    audio_labels: list[str] = []

    # Add video clips
    for i, clip in enumerate(video_clips):
        path = _resolve_media_path(folder, clip.media_name, job_id, video_index)
        duration = clip.end - clip.start
        # For video we trim source and then pad to place at track_start
        # We use -ss before -i for fast seek
        inputs += ["-ss", str(clip.start), "-t", str(duration), "-i", str(path)]
        # label for this video stream
        label_v = f"v{i}"
        label_a = f"av{i}"
        # setpts shifts to track_start
        pts_offset = clip.track_start
        filter_parts.append(
            f"[{input_idx}:v]setpts=PTS-STARTPTS+{pts_offset}/TB[{label_v}]"
        )
        if _has_audio(path):
            filter_parts.append(
                f"[{input_idx}:a]adelay={int(pts_offset * 1000)}|{int(pts_offset * 1000)},"
                f"volume={clip.volume}[{label_a}]"
            )
            audio_labels.append(f"[{label_a}]")
        video_labels.append(f"[{label_v}]")
        input_idx += 1

    # Add audio clips
    for i, clip in enumerate(audio_clips):
        path = _resolve_media_path(folder, clip.media_name, job_id, video_index)
        if not _has_audio(path):
            # No podemos añadir un clip de audio que no tiene audio... skip or error?
            # En este contexto de timeline, lo ignoramos para no romper el render.
            continue
        duration = clip.end - clip.start
        delay_ms = int(clip.track_start * 1000)
        inputs += ["-ss", str(clip.start), "-t", str(duration), "-i", str(path)]
        label_a = f"a{i}"
        filter_parts.append(
            f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume={clip.volume}[{label_a}]"
        )
        audio_labels.append(f"[{label_a}]")
        input_idx += 1

    # Build filter_complex
    n_audio = len(audio_labels)
    n_video = len(video_labels)

    if n_video > 1:
        # Concat video + its embedded audio
        concat_filter = "".join(video_labels) + f"concat=n={n_video}:v=1:a=0[vout]"
        filter_parts.append(concat_filter)
        video_map = "[vout]"
    elif n_video == 1:
        video_map = video_labels[0]
    else:
        video_map = None

    if n_audio > 1:
        mix_inputs = "".join(audio_labels)
        filter_parts.append(f"{mix_inputs}amix=inputs={n_audio}:normalize=0[aout]")
        audio_map = "[aout]"
    elif n_audio == 1:
        audio_map = audio_labels[0]
    else:
        audio_map = None

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y", "-v", "error"]
    cmd += inputs
    cmd += ["-filter_complex", filter_complex]

    if video_map:
        cmd += ["-map", video_map]

        # --- Lógica de Bitrate Dinámico ---
        # Intentamos obtener el bitrate del video original para ser fieles a la fuente
        assets = load_assets(folder)
        orig_path = assets.get("video_only") or assets.get("merged")
        orig_bitrate = get_video_bitrate(orig_path) if orig_path else 0

        # Convertimos a Kbps para FFmpeg. Límites: 800k min, 8000k max.
        # Si no se detecta (0), usamos 2000k como valor seguro por defecto.
        target_k = (
            max(800, min(int(orig_bitrate / 1000), 8000)) if orig_bitrate > 0 else 2000
        )
        max_k = int(target_k * 1.1)
        buf_k = int(target_k * 2.0)

        # Configuración optimizada para Peso/Calidad (NVENC):
        cmd += [
            "-c:v",
            "h264_nvenc",
            "-profile:v",
            "high",
            "-preset",
            "p7",  # Máximo análisis de calidad
            "-rc",
            "vbr",  # Variable Bit Rate
            "-cq",
            "28",  # Calidad constante balanceada para peso
            "-b:v",
            f"{target_k}k",  # Bitrate objetivo dinámico
            "-maxrate:v",
            f"{max_k}k",  # Límite máximo dinámico
            "-bufsize:v",
            f"{buf_k}k",  # Buffer dinámico (2x)
            "-multipass",
            "fullres",  # Análisis detallado multipass
            "-spatial-aq",
            "1",  # Adaptive Quantization espacial
            "-temporal-aq",
            "1",  # Adaptive Quantization temporal
            "-pix_fmt",
            "yuv420p",
        ]

    if audio_map:
        cmd += ["-map", audio_map]
        cmd += ["-c:a", "aac", "-b:a", "192k"]

    cmd.append(str(output_path))
    return cmd


@router.post("/render/timeline")
async def render_timeline(req: RenderTimelineRequest):
    """Render a single project timeline server-side with ffmpeg.

    If upload_to_catbox is True, uploads the result and returns a shareable URL.
    Otherwise, returns the MP4 file for direct download.
    """
    folder = _job_folder(req.job_id, req.video_index)

    # Validar integridad del manifiesto antes de renderizar
    manifest_warnings = _validate_manifest_integrity(folder)
    if manifest_warnings:
        print(f"⚠️ Advertencias de manifiesto para {req.job_id}/{req.video_index}:")
        for w in manifest_warnings:
            print(f"  - {w}")

    safe_name = to_safe_name(req.output_name)
    output_path = folder / f"_export_{safe_name}.mp4"

    cmd = _build_ffmpeg_cmd(req.clips, folder, output_path, req.job_id, req.video_index)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Error en ffmpeg: {result.stderr[-500:]}",
        )

    # Si se solicitó upload a Catbox, subir y retornar URL
    if req.upload_to_catbox:
        catbox_url = upload_to_catbox(output_path)
        if catbox_url:
            return {
                "status": "uploaded",
                "url": catbox_url,
                "filename": f"{safe_name}.mp4",
                "expires_in": "24h",
            }
        # Si falla el upload, retornar error con detalle
        raise HTTPException(
            status_code=500,
            detail="El render se completó pero falló la subida a Catbox.",
        )

    return FileResponse(
        str(output_path),
        filename=f"{safe_name}.mp4",
        media_type="video/mp4",
    )


# ---------------------------------------------------------------------------
# Batch render (multi-project → ZIP)
# ---------------------------------------------------------------------------


@router.post("/render/batch")
async def render_batch(req: RenderBatchRequest):
    """Render multiple project timelines and return them as a ZIP.

    If upload_to_catbox is True, uploads each video individually and returns a list of URLs.
    Otherwise, returns a ZIP file for direct download.
    """
    results: list[Path] = []
    errors: list[str] = []
    catbox_urls: list[dict] = []

    for item in req.renders:
        try:
            folder = _job_folder(item.job_id, item.video_index)
            safe_name = to_safe_name(item.output_name)  # para nombre de archivo en disco
            zip_name = to_zip_name(item.output_name)     # para arcname en ZIP (preserva emojis y hashtags)
            output_path = folder / f"_render_{safe_name}.mp4"

            cmd = _build_ffmpeg_cmd(
                item.clips, folder, output_path, item.job_id, item.video_index
            )
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                errors.append(
                    f"{item.output_name}: ffmpeg error – {result.stderr[-300:]}"
                )
                continue
            # Guardar también el zip_name para usarlo como arcname
            results.append((output_path, zip_name))

            # Upload individual to Catbox if requested
            if req.upload_to_catbox:
                catbox_url = upload_to_catbox(output_path)
                catbox_urls.append(
                    {
                        "filename": f"{zip_name}.mp4",
                        "url": catbox_url or "",
                        "status": "uploaded" if catbox_url else "upload_failed",
                    }
                )
        except HTTPException as e:
            errors.append(f"{item.output_name}: {e.detail}")
        except Exception as e:
            errors.append(f"{item.output_name}: {str(e)}")

    if not results:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo renderizar ningún video. Errores: {'; '.join(errors)}",
        )

    # Si se solicitó upload a Catbox, retornar lista de URLs
    if req.upload_to_catbox:
        return {
            "status": "completed",
            "videos": catbox_urls,
            "errors": errors,
            "expires_in": "24h",
        }

    # Build ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for output_path, zip_display_name in results:
            zf.write(output_path, arcname=f"{zip_display_name}.mp4")
        if errors:
            zf.writestr("_errors.txt", "\n".join(errors))

    zip_buffer.seek(0)
    zip_name = req.zip_name.replace("/", "_") or "batch_export"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )
