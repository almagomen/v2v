"""
Colab FFmpeg render endpoint.
Renders a timeline (single or batch) using ffmpeg server-side.
Includes Catbox upload for shareable links.
"""

import hashlib
import io
import json
import re
import time
import subprocess
import unicodedata
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from api.job_store import get_job
from src.config import QUEUE_DIR, TEMP_DIR, GPU_COUNT
from src.assets import load_assets, update_assets, register_segment
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

_NVENC_AVAILABLE: Optional[bool] = None


def _check_nvenc_available() -> bool:
    """Verifica si FFmpeg soporta h264_nvenc en la máquina actual."""
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    try:
        cmd = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "nullsrc=s=256x256:d=0.1",
            "-c:v", "h264_nvenc",
            "-f", "null",
            "-",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False)
        _NVENC_AVAILABLE = (res.returncode == 0)
    except Exception:
        _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE


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
    force_rerender: bool = False
    mode: Optional[str] = "auto"  # "auto" | "stream_copy" | "reencode"


class BatchRenderItem(BaseModel):
    job_id: str
    video_index: int
    clips: list[TimelineClip]
    output_name: str
    mode: Optional[str] = "auto"


class RenderBatchRequest(BaseModel):
    renders: list[BatchRenderItem]
    zip_name: str = "batch_export"
    upload_to_catbox: bool = False
    batch_id: Optional[str] = None
    force_rerender: bool = False
    mode: Optional[str] = "auto"


_batch_progress: dict[str, dict] = {}


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

    # Si es un segmento de audio (tts_*, gen_*, vocals_*), sincronizarlo también en Seqs_trg
    import re
    tts_match = re.search(r"(?:tts_|gen_|vocals_).*?_(\d+)\.wav$", safe_filename, re.I)
    if tts_match:
        seg_idx = int(tts_match.group(1))
        seqs_dir = folder / "Seqs_trg"
        seqs_dir.mkdir(parents=True, exist_ok=True)
        dest_seqs = seqs_dir / safe_filename
        dest_seqs.write_bytes(content)
        register_segment(folder, seg_idx, dest_seqs)

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
    gpu_id: int = 0,
    force_reencode: bool = False,
) -> list[str]:
    """
    Build an ffmpeg command that renders the timeline clips into a single MP4.
    Strategy:
     - Stream Copy (Zero re-encode): Si el timeline tiene 1 solo clip continuo de video desde el inicio y no se fuerza re-encode,
       se copia el flujo de video original con '-c:v copy' y solo se mezclan las pistas de audio.
     - Re-encode (NVENC GPU / CPU fallback): Si hay cortes/múltiples clips de video o se fuerza re-encode, se aplica
       recorte, concat y re-encode acelerado por GPU (h264_nvenc) o fallback a CPU (libx264).
    """
    video_clips = [c for c in clips if c.type == "video"]
    audio_clips = [c for c in clips if c.type == "audio"]

    if not video_clips and not audio_clips:
        raise HTTPException(status_code=400, detail="No hay clips en el timeline")

    # Detectar si podemos hacer Stream Copy del video (cero recodificación de video)
    can_stream_copy_video = (
        not force_reencode
        and len(video_clips) == 1
        and video_clips[0].start <= 0.05
        and video_clips[0].track_start <= 0.05
    )

    inputs: list[str] = []
    filter_parts: list[str] = []
    input_idx = 0
    video_labels: list[str] = []
    audio_labels: list[str] = []

    if can_stream_copy_video:
        # Modo Stream Copy: Input 0 es el video completo original sin filtros de video
        v_clip = video_clips[0]
        v_path = _resolve_media_path(folder, v_clip.media_name, job_id, video_index)
        v_duration = v_clip.end - v_clip.start
        inputs += ["-i", str(v_path)]
        input_idx = 1

        for i, clip in enumerate(audio_clips):
            path = _resolve_media_path(folder, clip.media_name, job_id, video_index)
            if not _has_audio(path):
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

        n_audio = len(audio_labels)
        cmd = ["ffmpeg", "-y", "-v", "error"] + inputs

        if n_audio > 1:
            mix_inputs = "".join(audio_labels)
            filter_parts.append(f"{mix_inputs}amix=inputs={n_audio}:normalize=0[aout]")
            cmd += ["-filter_complex", ";".join(filter_parts)]
            audio_map = "[aout]"
        elif n_audio == 1:
            cmd += ["-filter_complex", ";".join(filter_parts)]
            audio_map = audio_labels[0]
        else:
            audio_map = None

        cmd += ["-map", "0:v", "-c:v", "copy"]
        if audio_map:
            cmd += ["-map", audio_map, "-c:a", "aac", "-b:a", "192k"]
        elif _has_audio(v_path):
            cmd += ["-map", "0:a", "-c:a", "copy"]

        if v_duration > 0:
            cmd += ["-t", str(v_duration)]

        cmd.append(str(output_path))
        return cmd

    # Modo Re-encode (cuando hay cortes o múltiples clips de video)
    for i, clip in enumerate(video_clips):
        path = _resolve_media_path(folder, clip.media_name, job_id, video_index)
        duration = clip.end - clip.start
        inputs += ["-ss", str(clip.start), "-t", str(duration), "-i", str(path)]
        label_v = f"v{i}"
        label_a = f"av{i}"
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

    for i, clip in enumerate(audio_clips):
        path = _resolve_media_path(folder, clip.media_name, job_id, video_index)
        if not _has_audio(path):
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

    n_audio = len(audio_labels)
    n_video = len(video_labels)

    if n_video > 1:
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

    cmd = ["ffmpeg", "-y", "-v", "error", "-threads", "0"]
    cmd += inputs
    cmd += ["-filter_complex", filter_complex]

    if video_map:
        cmd += ["-map", video_map]

        assets = load_assets(folder)
        orig_path = assets.get("video_only") or assets.get("merged")
        orig_bitrate = get_video_bitrate(orig_path) if orig_path else 0

        target_k = (
            max(800, min(int(orig_bitrate / 1000), 8000)) if orig_bitrate > 0 else 2000
        )
        max_k = int(target_k * 1.1)
        buf_k = int(target_k * 2.0)

        if _check_nvenc_available():
            cmd += [
                "-gpu",
                str(gpu_id),
                "-c:v",
                "h264_nvenc",
                "-profile:v",
                "high",
                "-preset",
                "p4",  # Preset equilibrado y rápido de alta calidad (Turing NVENC)
                "-rc",
                "vbr",
                "-cq",
                "30",
                "-b:v",
                f"{target_k}k",
                "-maxrate:v",
                f"{max_k}k",
                "-bufsize:v",
                f"{buf_k}k",
                "-multipass",
                "1",  # Multipass quarter-res optimizado (evita cuello de botella de p7 fullres)
                "-spatial-aq",
                "1",  # Adaptive Quantization espacial
                "-temporal-aq",
                "1",  # Adaptive Quantization temporal
                "-pix_fmt",
                "yuv420p",
            ]
        else:
            cmd += [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-b:v",
                f"{target_k}k",
                "-maxrate:v",
                f"{max_k}k",
                "-bufsize:v",
                f"{buf_k}k",
                "-pix_fmt",
                "yuv420p",
            ]

    if audio_map:
        cmd += ["-map", audio_map]
        cmd += ["-c:a", "aac", "-b:a", "192k"]

    cmd.append(str(output_path))
    return cmd


def _compute_timeline_hash(clips: list[TimelineClip], mode: str = "auto") -> str:
    """Calcula un hash único a partir de la composición exacta de los clips del timeline y el modo de render."""
    data = {
        "mode": mode,
        "clips": [
            {
                "type": c.type,
                "media": Path(c.media_name).name,
                "start": round(float(c.start), 3),
                "end": round(float(c.end), 3),
                "track_start": round(float(c.track_start), 3),
                "vol": round(float(c.volume), 2),
            }
            for c in clips
        ],
    }
    raw = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _is_render_cache_valid(
    folder: Path,
    output_path: Path,
    clips: list[TimelineClip],
    job_id: str = None,
    video_index: int = None,
    mode: str = "auto",
) -> bool:
    """
    Verifica si un render previo existente sigue siendo 100% fiel al timeline actual y al modo de render solicitado.
    Retorna False (requiere re-render) si:
    1. El archivo MP4 no existe o pesa menos de 50 KB.
    2. Si existe un archivo .hash, y no coincide con la configuración actual de clips o modo (timeline editado o modo forzado).
    3. Si alguno de los archivos de audio/video involucrados fue modificado DESPUÉS del MP4.
    """
    if not output_path.exists() or output_path.stat().st_size < 50000:
        return False

    current_hash = _compute_timeline_hash(clips, mode=mode)
    hash_file = output_path.with_suffix(".hash")

    if hash_file.exists():
        try:
            saved_hash = hash_file.read_text(encoding="utf-8").strip()
            if saved_hash != current_hash:
                print(
                    f"🔄 [Render Cache] Timeline o modo modificado para {output_path.name} (hash mismatch). Re-renderizando..."
                )
                return False
        except Exception:
            return False

    # Comprobar si algún clip de entrada fue modificado después que el video exportado
    mp4_mtime = output_path.stat().st_mtime
    for clip in clips:
        try:
            resolved = _resolve_media_path(folder, clip.media_name, job_id, video_index)
            if resolved.exists() and resolved.is_file():
                if resolved.stat().st_mtime > mp4_mtime:
                    print(
                        f"🔄 [Render Cache] Clip '{resolved.name}' fue modificado después del render previo. Re-renderizando..."
                    )
                    return False
        except Exception:
            pass

    # Si llegó aquí y no tenía archivo .hash (render previo de sesión anterior de Colab), se lo creamos
    if not hash_file.exists():
        try:
            hash_file.write_text(current_hash, encoding="utf-8")
        except Exception:
            pass

    return True


def _save_render_cache_hash(output_path: Path, clips: list[TimelineClip], mode: str = "auto") -> None:
    """Guarda el hash del timeline y el modo tras un render exitoso."""
    try:
        h = _compute_timeline_hash(clips, mode=mode)
        output_path.with_suffix(".hash").write_text(h, encoding="utf-8")
    except Exception as e:
        print(f"⚠️ Error guardando hash de render: {e}")


@router.post("/render/timeline")
async def render_timeline(req: RenderTimelineRequest):
    """Render a single project timeline server-side with ffmpeg.

    If upload_to_catbox is True, uploads the result and returns a shareable URL.
    Otherwise, returns the MP4 file for direct download.
    """
    t_render_start = time.perf_counter()
    safe_name = to_safe_name(req.output_name)
    print(f"\n🎬 [Export Single] Iniciando render: {req.output_name}")

    folder = _job_folder(req.job_id, req.video_index)

    # Validar integridad del manifiesto antes de renderizar
    manifest_warnings = _validate_manifest_integrity(folder)
    if manifest_warnings:
        print(f"⚠️ Advertencias de manifiesto para {req.job_id}/{req.video_index}:")
        for w in manifest_warnings:
            print(f"  - {w}")

    output_path = folder / f"_export_{safe_name}.mp4"
    desired_mode = getattr(req, "mode", "auto") or "auto"
    force_reencode = (desired_mode == "reencode")

    # 1. Verificar si ya existe un render previo válido para el timeline actual (mismo nombre o nombre anterior)
    candidate: Optional[Path] = None
    for cand in [output_path, folder / f"_render_{safe_name}.mp4"]:
        if cand.exists() and cand.stat().st_size > 50000:
            if _is_render_cache_valid(folder, cand, req.clips, req.job_id, req.video_index, mode=desired_mode):
                candidate = cand
                break

    # Si no hay candidato con el nombre actual, buscar cualquier render previo en la carpeta con hash idéntico
    if not candidate and not req.force_rerender:
        all_renders = sorted(
            list(folder.glob("_export_*.mp4")) + list(folder.glob("_render_*.mp4")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for cand in all_renders:
            if cand.exists() and cand.stat().st_size > 50000:
                if _is_render_cache_valid(folder, cand, req.clips, req.job_id, req.video_index, mode=desired_mode):
                    candidate = cand
                    break

    cache_valid = bool(candidate and not req.force_rerender)

    t_ff = 0.0
    render_mode = "Caché (sin re-render)"
    if cache_valid and candidate:
        t_cache = time.perf_counter() - t_render_start
        if candidate.resolve() != output_path.resolve():
            import shutil
            try:
                shutil.copyfile(candidate, output_path)
                _save_render_cache_hash(output_path, req.clips, mode=desired_mode)
            except Exception:
                output_path = candidate
            print(f"⏩ [Caché] Timeline idéntico detectado ({desired_mode}). Reutilizando exportación previa para el nuevo título '{req.output_name}' ({output_path.stat().st_size / (1024*1024):.1f} MB en {t_cache:.2f}s)")
        else:
            print(f"⏩ [Caché] Timeline sin cambios ({desired_mode}) para {req.output_name}. Reutilizando {candidate.name} ({candidate.stat().st_size / (1024*1024):.1f} MB en {t_cache:.2f}s)")
            output_path = candidate
    else:
        t0_ff = time.perf_counter()
        cmd = _build_ffmpeg_cmd(
            req.clips,
            folder,
            output_path,
            req.job_id,
            req.video_index,
            gpu_id=1 if GPU_COUNT >= 2 else 0,
            force_reencode=force_reencode,
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Error en ffmpeg: {result.stderr[-500:]}",
            )
        _save_render_cache_hash(output_path, req.clips, mode=desired_mode)
        t_ff = time.perf_counter() - t0_ff
        cmd_str = " ".join(cmd)
        if "-c:v copy" in cmd_str:
            render_mode = "Stream Copy (sin re-encode)"
        elif "h264_nvenc" in cmd_str:
            render_mode = f"GPU {1 if GPU_COUNT >= 2 else 0} (NVENC)"
        else:
            render_mode = "CPU (libx264)"
        print(f"⏱️ [Etapa: FFmpeg Render] {render_mode} completado en {t_ff:.1f}s ({output_path.name})")

    t_cb = 0.0
    catbox_url = ""
    # Si se solicitó upload a Catbox, subir y retornar URL
    if req.upload_to_catbox:
        t0_cb = time.perf_counter()
        catbox_url = upload_to_catbox(output_path)
        t_cb = time.perf_counter() - t0_cb
        if catbox_url:
            print(f"⏱️ [Etapa: Catbox Upload] Subido en {t_cb:.1f}s -> {catbox_url}")
        else:
            raise HTTPException(
                status_code=500,
                detail="El render se completó pero falló la subida a Catbox.",
            )

    t_total = time.perf_counter() - t_render_start
    mins = int(t_total // 60)
    secs = int(t_total % 60)
    total_fmt = f"{t_total:.1f}s ({mins}m {secs:02d}s)" if mins > 0 else f"{t_total:.1f}s"
    print("=" * 60)
    print(f"🏁 RESUMEN EXPORTACIÓN VIDEO: {req.output_name}")
    print(f"• Modo Render: {render_mode}")
    print(f"• Renderizado FFmpeg: {t_ff:.1f}s" if not cache_valid else "• Renderizado: 0.0s (Caché)")
    if req.upload_to_catbox:
        print(f"• Subida Catbox: {t_cb:.1f}s")
    print(f"🏁 TIEMPO TOTAL VIDEO: {total_fmt}")
    print("=" * 60 + "\n")

    if req.upload_to_catbox:
        return {
            "status": "uploaded",
            "url": catbox_url,
            "filename": f"{safe_name}.mp4",
            "expires_in": "24h",
            "mode": render_mode,
            "timings": {
                "ffmpeg": round(t_ff, 2),
                "catbox": round(t_cb, 2),
                "total": round(t_total, 2),
                "mode": render_mode,
            },
            "log": f"Modo: {render_mode} | FFmpeg: {t_ff:.1f}s | Catbox: {t_cb:.1f}s | Total: {total_fmt}",
        }

    return FileResponse(
        str(output_path),
        filename=f"{safe_name}.mp4",
        media_type="video/mp4",
        headers={
            "X-Render-Time-Ffmpeg": str(round(t_ff, 2)),
            "X-Render-Time-Total": str(round(t_total, 2)),
            "X-Render-Cached": "1" if cache_valid else "0",
            "X-Render-Mode": render_mode,
            "Access-Control-Expose-Headers": "X-Render-Time-Ffmpeg, X-Render-Time-Total, X-Render-Cached, X-Render-Mode",
        },
    )


# ---------------------------------------------------------------------------
# Batch render (multi-project → ZIP)
# ---------------------------------------------------------------------------


@router.get("/render/batch/progress/{batch_id}")
async def get_batch_progress(batch_id: str):
    """Devuelve el progreso actual de un render por lotes."""
    return _batch_progress.get(
        batch_id,
        {"status": "idle", "current": 0, "total": 0, "percentage": 0, "step": "", "current_name": ""},
    )


@router.post("/render/batch")
async def render_batch(req: RenderBatchRequest):
    """Render multiple project timelines and return them as a ZIP.

    If upload_to_catbox is True, uploads each video individually and returns a list of URLs.
    Otherwise, returns a ZIP file for direct download.
    """
    batch_id = req.batch_id or "default"
    total = len(req.renders)
    t_batch_start = time.perf_counter()

    init_log = f"🚀 [Batch Render] Iniciando lote de {total} videos..."
    print(f"\n{init_log}")
    _batch_progress[batch_id] = {
        "status": "rendering",
        "current": 0,
        "total": total,
        "percentage": 0,
        "current_name": "",
        "step": f"Iniciando render de {total} proyectos...",
        "logs": [init_log],
    }

    import threading
    from concurrent.futures import ThreadPoolExecutor

    results: list[tuple[Path, str]] = []
    errors: list[str] = []
    catbox_urls: list[dict] = []
    completed_lock = threading.Lock()
    completed_count = 0

    max_workers = min(2, GPU_COUNT) if GPU_COUNT >= 2 else 1
    if max_workers > 1:
        print(f"⚡ [Multi-GPU Render] Renderizando batch en paralelo con {max_workers} GPUs...")

    def process_render_item(idx_item):
        nonlocal completed_count
        idx, item = idx_item
        t_item_start = time.perf_counter()
        gpu_id = idx % GPU_COUNT if GPU_COUNT > 0 else 0
        try:
            folder = _job_folder(item.job_id, item.video_index)
            safe_name = to_safe_name(item.output_name)
            zip_name = to_zip_name(item.output_name)
            desired_mode = getattr(item, "mode", None) or getattr(req, "mode", "auto") or "auto"
            force_reencode = (desired_mode == "reencode")

            existing_file: Optional[Path] = None
            for cand in [output_path, folder / f"_export_{safe_name}.mp4"]:
                if cand.exists() and cand.stat().st_size > 50000:
                    if _is_render_cache_valid(folder, cand, item.clips, item.job_id, item.video_index, mode=desired_mode):
                        existing_file = cand
                        break

            if not existing_file and not req.force_rerender:
                all_renders = sorted(
                    list(folder.glob("_render_*.mp4")) + list(folder.glob("_export_*.mp4")),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                for cand in all_renders:
                    if cand.exists() and cand.stat().st_size > 50000:
                        if _is_render_cache_valid(folder, cand, item.clips, item.job_id, item.video_index, mode=desired_mode):
                            existing_file = cand
                            break

            cache_valid = bool(existing_file and not req.force_rerender)

            t_ff = 0.0
            if cache_valid and existing_file:
                log_render = f"⏩ [{idx + 1}/{total}] {item.output_name}: Reutilizado de caché ({desired_mode}) (0.0s)"
                print(log_render)
                output_final = existing_file
            else:
                t0_ff = time.perf_counter()
                cmd = _build_ffmpeg_cmd(
                    item.clips,
                    folder,
                    output_path,
                    item.job_id,
                    item.video_index,
                    gpu_id=gpu_id,
                    force_reencode=force_reencode,
                )
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    with completed_lock:
                        err_msg = f"❌ [{idx + 1}/{total}] {item.output_name}: Error FFmpeg – {result.stderr[-300:]}"
                        errors.append(err_msg)
                        _batch_progress[batch_id]["logs"].append(err_msg)
                    return

                _save_render_cache_hash(output_path, item.clips, mode=desired_mode)
                t_ff = time.perf_counter() - t0_ff
                mode_str = "Stream Copy" if "-c:v copy" in " ".join(cmd) else f"GPU {gpu_id}"
                log_render = f"⏱️ [{idx + 1}/{total}] {item.output_name}: Renderizado FFmpeg en {t_ff:.1f}s ({mode_str})"
                print(log_render)
                output_final = output_path

            t_cb = 0.0
            catbox_url = ""
            if req.upload_to_catbox:
                t0_cb = time.perf_counter()
                catbox_url = upload_to_catbox(output_final)
                t_cb = time.perf_counter() - t0_cb
                log_cb = f"⏱️ [{idx + 1}/{total}] {item.output_name}: Subido a Catbox en {t_cb:.1f}s"
                print(log_cb)

            t_item_total = time.perf_counter() - t_item_start
            tot_log = f"🏁 [{idx + 1}/{total}] Video completado: {item.output_name} en {t_item_total:.1f}s (FFmpeg: {t_ff:.1f}s{f', Catbox: {t_cb:.1f}s' if req.upload_to_catbox else ''})"

            with completed_lock:
                results.append((output_final, zip_name))
                completed_count += 1
                pct = round((completed_count / max(1, total)) * 100)
                
                curr_logs = _batch_progress[batch_id].get("logs", [])
                curr_logs.append(log_render)
                if req.upload_to_catbox:
                    curr_logs.append(log_cb)
                curr_logs.append(tot_log)

                _batch_progress[batch_id] = {
                    "status": "rendering",
                    "current": completed_count,
                    "total": total,
                    "percentage": pct,
                    "current_name": item.output_name,
                    "step": f"Completado ({completed_count}/{total}): {item.output_name} ({t_item_total:.1f}s)",
                    "logs": curr_logs,
                }

                if req.upload_to_catbox:
                    catbox_urls.append(
                        {
                            "filename": f"{zip_name}.mp4",
                            "url": catbox_url or "",
                            "status": "uploaded" if catbox_url else "upload_failed",
                        }
                    )
        except Exception as e:
            with completed_lock:
                err_msg = f"❌ [{idx + 1}/{total}] {item.output_name}: {str(e)}"
                errors.append(err_msg)
                _batch_progress[batch_id].setdefault("logs", []).append(err_msg)

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(process_render_item, list(enumerate(req.renders))))

        t_batch_total = time.perf_counter() - t_batch_start
        mins = int(t_batch_total // 60)
        secs = int(t_batch_total % 60)
        fmt_batch = f"{t_batch_total:.1f}s ({mins}m {secs:02d}s)" if mins > 0 else f"{t_batch_total:.1f}s"
        batch_summary = (
            f"🏁 RESUMEN LOTE: {len(results)} de {total} videos exportados en {fmt_batch} "
            f"(Promedio: {(t_batch_total / max(1, len(results))):.1f}s/video)"
        )
        print("\n" + "=" * 60)
        print(batch_summary)
        print("=" * 60 + "\n")

        if not results:
            _batch_progress[batch_id] = {
                "status": "error",
                "current": total,
                "total": total,
                "percentage": 100,
                "current_name": "",
                "step": "Error al renderizar videos",
                "logs": _batch_progress[batch_id].get("logs", []) + [batch_summary],
            }
            raise HTTPException(
                status_code=500,
                detail=f"No se pudo renderizar ningún video. Errores: {'; '.join(errors)}",
            )

        # Si se solicitó upload a Catbox, retornar lista de URLs
        if req.upload_to_catbox:
            curr_logs = _batch_progress[batch_id].get("logs", [])
            curr_logs.append(batch_summary)
            _batch_progress[batch_id] = {
                "status": "done",
                "current": total,
                "total": total,
                "percentage": 100,
                "current_name": "",
                "step": f"¡{len(catbox_urls)} video(s) subido(s) a Catbox!",
                "logs": curr_logs,
                "total_time": round(t_batch_total, 2),
            }
            return {
                "status": "completed",
                "videos": catbox_urls,
                "errors": errors,
                "expires_in": "24h",
                "logs": curr_logs,
                "total_time": round(t_batch_total, 2),
            }

        curr_logs = _batch_progress[batch_id].get("logs", [])
        curr_logs.append("📦 Empaquetando archivo ZIP final...")
        curr_logs.append(batch_summary)
        _batch_progress[batch_id] = {
            "status": "packaging",
            "current": total,
            "total": total,
            "percentage": 95,
            "current_name": "",
            "step": "Empaquetando archivo ZIP final...",
            "logs": curr_logs,
            "total_time": round(t_batch_total, 2),
        }

        # Build ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for output_path, zip_display_name in results:
                zf.write(output_path, arcname=f"{zip_display_name}.mp4")
            if errors:
                zf.writestr("_errors.txt", "\n".join(errors))

        zip_buffer.seek(0)
        zip_name = to_zip_name(req.zip_name) or "batch_export"

        _batch_progress[batch_id] = {
            "status": "done",
            "current": total,
            "total": total,
            "percentage": 100,
            "current_name": "",
            "step": f"¡{len(results)} videos exportados con éxito!",
        }

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
        )
    finally:
        pass


# ---------------------------------------------------------------------------
# Gemini Models & Viral Title Regeneration Endpoints
# ---------------------------------------------------------------------------
from api.schemas import (
    RegenerateTitleRequest,
    RegenerateTitleResponse,
    GeminiModelsResponse,
    SetDefaultGeminiModelRequest,
)


@router.get("/render/gemini-models", response_model=GeminiModelsResponse)
async def get_gemini_models():
    """Obtiene la lista de modelos de Gemini y el modelo por defecto activo."""
    from src.translation import POPULAR_GEMINI_MODELS, get_default_gemini_model

    return GeminiModelsResponse(
        default_model=get_default_gemini_model(),
        models=POPULAR_GEMINI_MODELS,
    )


@router.post("/render/gemini-models/default")
async def set_gemini_default_model(req: SetDefaultGeminiModelRequest):
    """Establece el modelo de Gemini por defecto para la sesión."""
    from src.translation import set_default_gemini_model

    set_default_gemini_model(req.model_name)
    return {"status": "ok", "default_model": req.model_name}


@router.post("/render/regenerate-title", response_model=RegenerateTitleResponse)
async def regenerate_title(req: RegenerateTitleRequest):
    """
    Regenera el título viral usando Gemini o aplica un nombre manual.
    Actualiza v2v_assets.json, result.json, y el estado del job en memoria.
    """
    import re
    from src.assets import update_assets, load_assets
    from src.translation import generate_tiktok_title, get_default_gemini_model
    from src.result_store import load_result, update_result_output_name

    folder: Optional[Path] = None
    if req.job_id:
        try:
            folder = _job_folder(req.job_id, req.video_index)
        except Exception:
            pass

    if not folder and req.folder_name:
        cand_folder = (QUEUE_DIR / req.folder_name).resolve()
        if cand_folder.exists() and cand_folder.is_dir():
            folder = cand_folder
        else:
            for sub in QUEUE_DIR.glob("*"):
                if sub.is_dir() and (sub.name == req.folder_name or req.folder_name in sub.name):
                    folder = sub
                    break

    if not folder:
        raise HTTPException(
            status_code=404,
            detail="No se encontró la carpeta del video especificado.",
        )

    # Caso 1: Título manual definido por el usuario
    if req.custom_title and req.custom_title.strip():
        clean_name = re.sub(r'[/\\:*?"<>|\n]', " ", req.custom_title).strip()
        clean_name = re.sub(r" {2,}", " ", clean_name)
        if not clean_name:
            clean_name = "video_export"

        update_assets(folder, output_name=clean_name, viral_title=clean_name)
        update_result_output_name(folder, clean_name)

        if req.job_id:
            try:
                job = get_job(req.job_id)
                if job and "videos" in job and req.video_index < len(job["videos"]):
                    job["videos"][req.video_index]["output_name"] = clean_name
            except Exception:
                pass

        return RegenerateTitleResponse(
            status="ok",
            output_name=clean_name,
            model_used=None,
            message="Título manual actualizado con éxito",
        )

    # Caso 2: Regenerar con Gemini (IA)
    cached_url = ""
    fallback_text = ""
    original_title = ""

    result_data = load_result(folder)
    if result_data:
        cached_url = result_data.get("url", "")
        segments = result_data.get("segments", [])
        if segments:
            fallback_text = " ".join(t.get("text", "") for t in segments)
        info = result_data.get("info", {})
        original_title = info.get("title", "") if isinstance(info, dict) else ""

    # Fallback a v2v_assets.json si falta info
    assets = load_assets(folder)
    if not cached_url:
        cached_url = assets.get("url", "")
    if not fallback_text:
        fallback_text = assets.get("transcript_summary", "") or original_title

    model_to_use = req.model_name or get_default_gemini_model()
    try:
        new_title = generate_tiktok_title(
            youtube_url=cached_url or None,
            target_lang=req.target_lang or "es",
            model_name=model_to_use,
            fallback_text=fallback_text or original_title,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generando título con IA: {str(e)}",
        )

    if not new_title:
        raise HTTPException(
            status_code=500,
            detail="La IA no pudo generar un título. Intenta con otro modelo de Gemini o define el título manualmente.",
        )

    clean_title = re.sub(r'[/\\:*?"<>|\n]', " ", new_title).strip()
    clean_title = re.sub(r" {2,}", " ", clean_title)

    update_assets(folder, output_name=clean_title, viral_title=clean_title)
    update_result_output_name(folder, clean_title)

    if req.job_id:
        try:
            job = get_job(req.job_id)
            if job and "videos" in job and req.video_index < len(job["videos"]):
                job["videos"][req.video_index]["output_name"] = clean_title
        except Exception:
            pass

    return RegenerateTitleResponse(
        status="ok",
        output_name=clean_title,
        model_used=model_to_use,
        message="Título viral generado exitosamente",
    )


