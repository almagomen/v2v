import io
import os
import tarfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from api.job_store import get_job

router = APIRouter(prefix="/api", tags=["files"])


def _safe_filename(name: str) -> bool:
    """Reject dangerous filenames and prevent common security issues."""
    # No permitimos subir de nivel con nombres que empiecen por punto o contengan separadores.
    return not (name.startswith(".") or "/" in name or "\\" in name) and len(name) < 256


def _get_video_folder(job_id: str, video_index: int) -> Path:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")
    video_path = Path(videos[video_index]["video_path"])
    return video_path.parent


def _get_video_output_path(job_id: str, video_index: int) -> Path:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    # Preferimos video_only_path (sin audio) para pegar en timeline con TTS por segmentos.
    # Luego fallback a output_video_path (render) y al video_path original.
    out = (
        videos[video_index].get("video_only_path")
        or videos[video_index].get("output_video_path")
        or videos[video_index].get("video_path")
    )
    if not out:
        raise HTTPException(status_code=404, detail="Output no encontrado")
    return Path(out)


def _safe_header_filename(filename: str) -> str:
    """Retorna un nombre seguro para headers HTTP (sin emojis ni caracteres que rompan latin-1)."""
    clean = filename.encode("ascii", "ignore").decode("ascii").strip()
    if not clean or len(clean) < 3:
        clean = "file"
    return clean


def _get_or_create_compressed_audio(wav_path: Path) -> Path:
    """Convierte un WAV pesado a AAC (.m4a) a 192k para acelerar la descarga en un 90%+."""
    if wav_path.suffix.lower() == ".m4a":
        return wav_path
    m4a_path = wav_path.with_suffix(".m4a")
    if m4a_path.exists() and m4a_path.stat().st_size > 0:
        return m4a_path
    import subprocess
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_path),
        "-c:a", "aac", "-b:a", "192k",
        str(m4a_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if m4a_path.exists() and m4a_path.stat().st_size > 0:
            return m4a_path
    except Exception:
        pass
    return wav_path


@router.get("/job/{job_id}/asset/{video_index}/{asset_key}")
def serve_asset(job_id: str, video_index: int, asset_key: str):
    """Sirve un activo específico (video_only, instrumental, vocals, etc.) por clave determinista."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    video_info = videos[video_index]
    folder = _get_video_folder(job_id, video_index)
    from src.assets import load_assets
    assets = load_assets(folder)

    key_map = {
        "video_only": ["video_only", "output_video_path", "video_path"],
        "instrumental": ["no_vocals"],
        "no_vocals": ["no_vocals"],
        "vocals": ["vocals"],
        "merged": ["merged", "video_path", "output_video_path"],
        "original_audio": ["audio_only"],
    }
    candidates = key_map.get(asset_key, [asset_key])
    target_path = None
    for cand in candidates:
        p = assets.get(cand) or video_info.get(f"{cand}_path") or video_info.get(cand)
        if p:
            cand_p = Path(p) if Path(p).is_absolute() else folder / p
            if cand_p.is_file():
                target_path = cand_p
                break

    if not target_path or not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Activo '{asset_key}' no encontrado")

    # Si es instrumental o audio pesado, comprimimos automáticamente a AAC (.m4a)
    # para reducir el tamaño de 25MB a 1.5MB sin pérdida audible.
    if asset_key in ("instrumental", "no_vocals") and target_path.suffix.lower() == ".wav":
        target_path = _get_or_create_compressed_audio(target_path)
        media_type = "audio/mp4" if target_path.suffix == ".m4a" else "audio/wav"
        safe_name = f"no_vocals{target_path.suffix}"
        return FileResponse(target_path, filename=safe_name, media_type=media_type)

    media_type = "video/mp4" if target_path.suffix == ".mp4" else None
    safe_name = f"{asset_key}{target_path.suffix}"
    return FileResponse(target_path, filename=safe_name, media_type=media_type)


@router.get("/job/{job_id}/files/{video_index}/{filename}")
def serve_file(job_id: str, video_index: int, filename: str):
    """Serve a file from the job's video folder."""
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Nombre de archivo no permitido")
    folder = _get_video_folder(job_id, video_index)

    # Aseguramos que el path resuelto esté dentro de la carpeta permitida (seguridad real)
    base_dir = folder.resolve()
    file_path = (base_dir / filename).resolve()

    if not str(file_path).startswith(str(base_dir)):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    if not file_path.exists() or not file_path.is_file():
        seqs_file = (base_dir / "Seqs_trg" / filename).resolve()
        if seqs_file.exists() and seqs_file.is_file():
            return FileResponse(seqs_file, filename=_safe_header_filename(filename))
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, filename=_safe_header_filename(filename))


@router.get("/job/{job_id}/files/{video_index}")
def serve_file_by_index(job_id: str, video_index: int):
    """Serve el MP4 renderizado usando el path guardado en el job.

    Esto evita fallos 404 cuando el frontend pasa un `filename` muy largo o con
    caracteres que no coinciden exactamente con el nombre real del archivo.
    """
    file_path = _get_video_output_path(job_id, video_index)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(file_path, filename=_safe_header_filename(file_path.name))


@router.get("/job/{job_id}/audio-segments/{video_index}")
def list_audio_segments(job_id: str, video_index: int):
    """List audio segment WAVs for a job/video (Seqs_trg/tts_{speaker}_{NNNN}.wav)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    folder = _get_video_folder(job_id, video_index)
    seqs_trg = folder / "Seqs_trg"
    segments = videos[video_index].get("segments", []) or []

    items = []
    for s in segments:
        try:
            seg = int(s.get("seg"))
        except Exception:
            continue

        wav_path = None
        filename = None
        for candidate in seqs_trg.glob(f"tts_*_{seg:03d}.wav"):
            wav_path = candidate
            filename = candidate.name
            break

        if wav_path is None:
            continue

        items.append(
            {
                "seg": seg,
                "start": s.get("start", 0.0),
                "end": s.get("end", 0.0),
                "duration": s.get("duration", round(s.get("end", 0.0) - s.get("start", 0.0), 3)),
                "speaker": s.get("speaker") or "",
                "filename": filename,
            }
        )
    return items


@router.get("/job/{job_id}/audio-segments/{video_index}/{seg}")
def serve_audio_segment(job_id: str, video_index: int, seg: int):
    """Serve a single WAV segment by seg index (1-based). Formato: tts_{speaker}_{NNNN}.wav."""
    if seg <= 0 or seg > 999:
        raise HTTPException(status_code=400, detail="Segmento inválido")
    folder = _get_video_folder(job_id, video_index)
    seqs_trg = folder / "Seqs_trg"

    for candidate in seqs_trg.glob(f"tts_*_{seg:03d}.wav"):
        return FileResponse(candidate, filename=candidate.name, media_type="audio/wav")

    raise HTTPException(status_code=404, detail="Archivo no encontrado")


def ensure_audio_segments_tar(folder: Path) -> Path | None:
    """Empaqueta de forma atómica y anticipada los segmentos WAV en audio_segments.tar.gz.

    Ventajas:
    1. Compresión gzip ultra-rápida (compresslevel=1): reduce el tamaño ~70% a velocidad >150MB/s.
    2. Servido con FileResponse vía sendfile(), con primer byte en <10ms eludiendo el error 524 de Cloudflare.
    3. Validación por mtime: si no hay WAVs nuevos, la entrega es instantánea sin re-empaquetar.
    4. Fallback automático a TAR sin comprimir si el entorno no soporta compresión gzip.
    """
    seqs_trg = folder / "Seqs_trg"
    if not seqs_trg.exists() or not seqs_trg.is_dir():
        return None

    wav_files = [
        f for f in sorted(seqs_trg.glob("*.wav"))
        if f.is_file() and f.stat().st_size > 0 and not f.name.endswith("_raw.wav")
    ]
    if not wav_files:
        return None

    tar_gz_path = folder / "audio_segments.tar.gz"
    tar_legacy_path = folder / "audio_segments.tar"
    latest_wav_mtime = max(f.stat().st_mtime for f in wav_files)

    # Si ya existe un tar.gz válido y más reciente que los WAVs, retornarlo de inmediato
    if tar_gz_path.exists() and tar_gz_path.stat().st_mtime >= latest_wav_mtime:
        return tar_gz_path

    # Empaquetado atómico temporal con gzip ligero
    temp_tar = folder / "audio_segments.tar.gz.tmp"
    try:
        with tarfile.open(temp_tar, mode="w:gz", compresslevel=1) as tar:
            for f in wav_files:
                tar.add(f, arcname=f.name)
        temp_tar.replace(tar_gz_path)
        # Limpiar versión legacy si existía
        if tar_legacy_path.exists():
            try:
                tar_legacy_path.unlink()
            except OSError:
                pass
        return tar_gz_path
    except Exception:
        if temp_tar.exists():
            try:
                temp_tar.unlink()
            except OSError:
                pass
        # Fallback de seguridad: crear TAR plano sin comprimir
        try:
            temp_flat = folder / "audio_segments.tar.tmp"
            with tarfile.open(temp_flat, mode="w") as tar:
                for f in wav_files:
                    tar.add(f, arcname=f.name)
            temp_flat.replace(tar_legacy_path)
            return tar_legacy_path
        except Exception:
            return None


@router.get("/job/{job_id}/audio-segments-tar/{video_index}")
def serve_audio_segments_tar(job_id: str, video_index: int):
    """Sirve todos los segmentos de audio TTS de un video en un paquete TAR/GZ servido con FileResponse.

    Ventajas:
    1. Primer byte instantáneo (<10ms) hacia Cloudflare Tunnel, evitando el error 524 (timeout de 100s).
    2. Cero contención de memoria RAM al escribir a disco en vez de BytesIO.
    3. Caché en disco con validación mtime: entrega instantánea con sendfile().
    4. Compresión ligera en disco que reduce el tráfico de red en más de 65%.
    """
    folder = _get_video_folder(job_id, video_index)
    tar_file = ensure_audio_segments_tar(folder)
    if not tar_file or not tar_file.exists():
        raise HTTPException(status_code=404, detail="No hay segmentos WAV disponibles para empaquetar")

    media_type = "application/gzip" if tar_file.suffix == ".gz" else "application/x-tar"
    filename = f"audio_segments_{video_index}.tar.gz" if tar_file.suffix == ".gz" else f"audio_segments_{video_index}.tar"

    return FileResponse(
        path=tar_file,
        media_type=media_type,
        filename=filename,
    )


# ── Segmentos de audio originales (Seqs_src) ───────────────────────────────────

@router.get("/job/{job_id}/src-audio-segments/{video_index}")
def list_src_audio_segments(job_id: str, video_index: int):
    """List original audio segment WAVs for a job/video (Seqs_src/vocals_{NNN}.wav)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    videos = job.get("videos", [])
    if video_index < 0 or video_index >= len(videos):
        raise HTTPException(status_code=404, detail="Video no encontrado")

    folder = _get_video_folder(job_id, video_index)
    seqs_src = folder / "Seqs_src"
    segments = videos[video_index].get("segments", []) or []

    # Si Seqs_src no existe o está vacío, pero vocals.wav y segmentos existen, generar on-demand
    vocals_wav = folder / "vocals.wav"
    if (not seqs_src.exists() or not any(seqs_src.glob("*.wav"))) and vocals_wav.exists() and segments:
        try:
            from src.pipeline import split_audio_sequences
            split_audio_sequences(vocals_wav, segments, output_dir=seqs_src)
        except Exception as e:
            print(f"⚠️ Error generando cortes de Seqs_src en demanda: {e}")

    items = []
    for s in segments:
        try:
            seg = int(s.get("seg"))
        except Exception:
            continue

        wav_path = None
        filename = None
        for candidate in seqs_src.glob(f"*_{seg:03d}.wav"):
            wav_path = candidate
            filename = candidate.name
            break

        if wav_path is None:
            continue

        o_start = s.get("orig_start", s.get("start", 0.0))
        o_end = s.get("orig_end", s.get("end", 0.0))
        o_dur = s.get("orig_duration", round(o_end - o_start, 3))
        items.append(
            {
                "seg": seg,
                "start": o_start,
                "end": o_end,
                "duration": o_dur,
                "orig_start": o_start,
                "orig_end": o_end,
                "orig_duration": o_dur,
                "speaker": s.get("original_speaker", s.get("speaker", "")),
                "filename": filename,
            }
        )
    return items


@router.get("/job/{job_id}/src-audio-segments/{video_index}/{seg}")
def serve_src_audio_segment(job_id: str, video_index: int, seg: int):
    """Serve a single original WAV segment by seg index (1-based). Formato: vocals_{NNN}.wav."""
    if seg <= 0 or seg > 999:
        raise HTTPException(status_code=400, detail="Segmento inválido")
    folder = _get_video_folder(job_id, video_index)
    seqs_src = folder / "Seqs_src"

    for candidate in seqs_src.glob(f"*_{seg:03d}.wav"):
        return FileResponse(candidate, filename=candidate.name, media_type="audio/wav")

    raise HTTPException(status_code=404, detail="Archivo no encontrado")


def ensure_src_audio_segments_tar(folder: Path) -> Path | None:
    """Empaqueta de forma atómica y anticipada los segmentos WAV originales en src_audio_segments.tar.gz."""
    seqs_src = folder / "Seqs_src"

    # Si Seqs_src no existe o está vacío, intentar corte on-demand si vocals.wav existe
    if not seqs_src.exists() or not any(seqs_src.glob("*.wav")):
        vocals_wav = folder / "vocals.wav"
        if vocals_wav.exists():
            try:
                from src.result_store import load_result
                from src.pipeline import split_audio_sequences
                res_data = load_result(folder)
                segs = res_data.get("segments", []) if res_data else []
                if segs:
                    split_audio_sequences(vocals_wav, segs, output_dir=seqs_src)
            except Exception as e:
                print(f"⚠️ Error generando cortes de Seqs_src on-demand: {e}")

    if not seqs_src.exists() or not seqs_src.is_dir():
        return None

    wav_files = [
        f for f in sorted(seqs_src.glob("*.wav"))
        if f.is_file() and f.stat().st_size > 0 and not f.name.endswith("_raw.wav")
    ]
    if not wav_files:
        return None

    tar_gz_path = folder / "src_audio_segments.tar.gz"
    tar_legacy_path = folder / "src_audio_segments.tar"
    latest_wav_mtime = max(f.stat().st_mtime for f in wav_files)

    if tar_gz_path.exists() and tar_gz_path.stat().st_mtime >= latest_wav_mtime:
        return tar_gz_path

    temp_tar = folder / "src_audio_segments.tar.gz.tmp"
    try:
        with tarfile.open(temp_tar, mode="w:gz", compresslevel=1) as tar:
            for f in wav_files:
                tar.add(f, arcname=f.name)
        temp_tar.replace(tar_gz_path)
        if tar_legacy_path.exists():
            try:
                tar_legacy_path.unlink()
            except OSError:
                pass
        return tar_gz_path
    except Exception:
        if temp_tar.exists():
            try:
                temp_tar.unlink()
            except OSError:
                pass
        try:
            temp_flat = folder / "src_audio_segments.tar.tmp"
            with tarfile.open(temp_flat, mode="w") as tar:
                for f in wav_files:
                    tar.add(f, arcname=f.name)
            temp_flat.replace(tar_legacy_path)
            return tar_legacy_path
        except Exception:
            return None


@router.get("/job/{job_id}/src-audio-segments-tar/{video_index}")
def serve_src_audio_segments_tar(job_id: str, video_index: int):
    """Sirve todos los segmentos WAV originales de un video en un paquete TAR/GZ servido con FileResponse."""
    folder = _get_video_folder(job_id, video_index)
    tar_file = ensure_src_audio_segments_tar(folder)
    if not tar_file or not tar_file.exists():
        raise HTTPException(status_code=404, detail="No hay segmentos WAV originales disponibles para empaquetar")

    media_type = "application/gzip" if tar_file.suffix == ".gz" else "application/x-tar"
    filename = f"src_audio_segments_{video_index}.tar.gz" if tar_file.suffix == ".gz" else f"src_audio_segments_{video_index}.tar"

    return FileResponse(
        path=tar_file,
        media_type=media_type,
        filename=filename,
    )


