"""
Colab FFmpeg render endpoint.
Renders a timeline (single or batch) using ffmpeg server-side.
"""
import io
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from api.job_store import get_job
from src.config import QUEUE_DIR

router = APIRouter(prefix="/api", tags=["render"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_audio(path: Path) -> bool:
    """Check if a media file has at least one audio stream using ffprobe."""
    import subprocess
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", str(path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return bool(result.stdout.strip())
    except Exception:
        return False

def _job_folder(job_id: str, video_index: int) -> Path:
    """Resolve the folder for a given job/video_index."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video index fuera de rango")
    return Path(videos[video_index]["video_path"]).parent


def _resolve_media_path(folder: Path, media_name: str, job_id: str = None, video_index: int = None) -> Path:
    """
    Resolves a media_name (e.g. 'folder/video.mp4' or 'folder/tts_spk_0001.wav')
    to an absolute path inside the job folder.
    The media_name may include a leading subfolder that matches the folder name;
    we strip it if needed.
    """
    # Try as absolute first
    p = Path(media_name)
    if p.is_absolute() and p.exists():
        return p

    # Fallback to the original source video if frontend requests "video.mp4"
    if p.name == "video.mp4" and job_id is not None and video_index is not None:
        job = get_job(job_id)
        if job:
            videos = job.get("videos", [])
            if 0 <= video_index < len(videos):
                v_only = videos[video_index].get("video_only_path")
                v_path = videos[video_index].get("video_path")
                # Priorizar video_only (silencioso) para evitar solapamientos
                resolved = v_only if v_only and Path(v_only).exists() else v_path
                if resolved and Path(resolved).exists():
                    return Path(resolved)

    # Fallback to the original TTS segments if frontend requests renamed "tts_..._XXXX.wav"
    import re
    match = re.search(r'tts_.*_(\d{4})\.wav$', p.name)
    if match:
        seg_num = match.group(1)
        seg_path = folder / "Seqs_trg" / f"vocals_{seg_num}.wav"
        if seg_path.exists():
            return seg_path

    # Try to strip the leading folder name if it matches the job folder name
    if p.parts and p.parts[0] == folder.name:
        rel_path = Path(*p.parts[1:])
    else:
        rel_path = p

    candidate3 = folder / rel_path
    if candidate3.exists():
        return candidate3

    # Fallback to pure filename just in case
    candidate = folder / p.name
    if candidate.exists():
        return candidate

    # Try relative to QUEUE_DIR root (e.g. 'My_Video/video.mp4')
    candidate2 = QUEUE_DIR / p
    if candidate2.exists():
        return candidate2

    raise HTTPException(
        status_code=404,
        detail=f"Archivo no encontrado en el servidor: {media_name}",
    )


def _get_video_bitrate(path: Path) -> int:
    """Intenta extraer la tasa de bits (kbps) del archivo original con ffprobe."""
    import subprocess
    import json
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate:stream=bit_rate", "-of", "json", str(path)]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        
        streams = data.get("streams", [])
        if streams and "bit_rate" in streams[0] and streams[0]["bit_rate"] != "N/A":
            return int(streams[0]["bit_rate"])
            
        fmt = data.get("format", {})
        if "bit_rate" in fmt and fmt["bit_rate"] != "N/A":
            return int(fmt["bit_rate"])
    except Exception as e:
        print(f"Error extracting bitrate for {path}: {e}")
    return 0


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TimelineClip(BaseModel):
    type: str           # "video" | "audio"
    media_name: str     # relative path to media file
    start: float        # inPoint (trim start within file, seconds)
    end: float          # outPoint (trim end within file, seconds)
    track_start: float  # position on the timeline (seconds)
    volume: float = 1.0


class RenderTimelineRequest(BaseModel):
    job_id: str
    video_index: int
    clips: list[TimelineClip]
    output_name: str = "export"


class BatchRenderItem(BaseModel):
    job_id: str
    video_index: int
    clips: list[TimelineClip]
    output_name: str


class RenderBatchRequest(BaseModel):
    renders: list[BatchRenderItem]
    zip_name: str = "batch_export"


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
    target_dir = folder / subfolder if subfolder else folder
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename or "upload.bin").name
    dest = target_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {"media_name": f"{subfolder}/{safe_name}" if subfolder else safe_name}


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
        
        # Buscar el bitrate del primer clip activo
        target_bitrate = 0
        if video_clips:
            first_vp = _resolve_media_path(folder, video_clips[0].media_name, job_id, video_index)
            target_bitrate = _get_video_bitrate(first_vp)
            
        if target_bitrate > 0:
            br_kbps = min(int((target_bitrate * 1.05) / 1000), 10000) # Máximo 10Mbps
            max_kbps = br_kbps + 500
            cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", f"{br_kbps}k", "-maxrate:v", f"{max_kbps}k", "-bufsize:v", f"{max_kbps*2}k"]
        else:
            cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "31", "-b:v", "0"]
    if audio_map:
        cmd += ["-map", audio_map]
        cmd += ["-c:a", "aac", "-b:a", "192k"]

    cmd.append(str(output_path))
    return cmd


@router.post("/render/timeline")
async def render_timeline(req: RenderTimelineRequest):
    """Render a single project timeline server-side with ffmpeg."""
    import subprocess

    folder = _job_folder(req.job_id, req.video_index)
    safe_name = req.output_name.replace("/", "_").replace("\\", "_")
    output_path = folder / f"_export_{safe_name}.mp4"

    cmd = _build_ffmpeg_cmd(req.clips, folder, output_path, req.job_id, req.video_index)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Error en ffmpeg: {result.stderr[-500:]}",
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
    """Render multiple project timelines and return them as a ZIP."""
    import subprocess

    results: list[Path] = []
    errors: list[str] = []

    for item in req.renders:
        try:
            folder = _job_folder(item.job_id, item.video_index)
            safe_name = item.output_name.replace("/", "_").replace("\\", "_")
            output_path = folder / f"_export_{safe_name}.mp4"

            cmd = _build_ffmpeg_cmd(item.clips, folder, output_path, item.job_id, item.video_index)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                errors.append(f"{item.output_name}: ffmpeg error – {result.stderr[-300:]}")
                continue
            results.append(output_path)
        except HTTPException as e:
            errors.append(f"{item.output_name}: {e.detail}")
        except Exception as e:
            errors.append(f"{item.output_name}: {str(e)}")

    if not results:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo renderizar ningún video. Errores: {'; '.join(errors)}",
        )

    # Build ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in results:
            zf.write(path, arcname=path.name)
        if errors:
            zf.writestr("_errors.txt", "\n".join(errors))

    zip_buffer.seek(0)
    zip_name = req.zip_name.replace("/", "_") or "batch_export"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )
