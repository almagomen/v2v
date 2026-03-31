"""
Renderizado de video final: ffmpeg, preview baja res, upload opcional.
"""

import json
import subprocess
from pathlib import Path
import re
import unicodedata

from src.config import TEMP_DIR


def _has_nvenc() -> bool:
    """Check if NVENC encoder is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "h264_nvenc" in result.stdout
    except Exception:
        return False


def _get_video_bitrate(path: Path) -> int:
    """Get video bitrate in bps from a media file."""
    try:
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-select_streams",
            "v:0",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            return int(streams[0].get("bit_rate", 0))
    except Exception:
        pass
    return 0


def render_video(
    video_path: Path,
    output_name: str,
    vocals_es_path: Path,
    no_vocals_path: Path,
    output_dir: Path | None = None,
) -> Path:
    """Renderiza el video final combinando video original con audio clonado.

    Usa NVENC si está disponible (mismo codec que ColabExport), con fallback a libx264.
    """
    if output_dir is None:
        output_dir = TEMP_DIR

    final_output_path = output_dir / f"{output_name}.mp4"
    temp_output_path = output_dir / f"temp_{output_name}.mp4"

    use_nvenc = _has_nvenc()

    # Obtener bitrate del video original para configuración dinámica
    orig_bitrate = _get_video_bitrate(video_path)
    target_k = (
        max(800, min(int(orig_bitrate / 1000), 8000)) if orig_bitrate > 0 else 2000
    )
    max_k = int(target_k * 1.1)
    buf_k = int(target_k * 2.0)

    if use_nvenc:
        # Mismo codec y configuración que ColabExport (api/routes/render.py)
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(vocals_es_path),
            "-i",
            str(no_vocals_path),
            "-filter_complex",
            "[0]volume=0.00[a0];[1]volume=3.5[a1];[2]volume=1.0[a2];[a0][a1][a2]amix=inputs=3[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "h264_nvenc",
            "-profile:v",
            "high",
            "-preset",
            "p7",
            "-rc",
            "vbr",
            "-cq",
            "28",
            "-b:v",
            f"{target_k}k",
            "-maxrate:v",
            f"{max_k}k",
            "-bufsize:v",
            f"{buf_k}k",
            "-multipass",
            "fullres",
            "-spatial-aq",
            "1",
            "-temporal-aq",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(temp_output_path),
        ]
    else:
        # Fallback a libx264 con buena calidad
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(vocals_es_path),
            "-i",
            str(no_vocals_path),
            "-filter_complex",
            "[0]volume=0.00[a0];[1]volume=3.5[a1];[2]volume=1.0[a2];[a0][a1][a2]amix=inputs=3[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(temp_output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        if final_output_path.exists():
            final_output_path.unlink()
        temp_output_path.rename(final_output_path)
        return final_output_path

    # Si falla NVENC, intentar fallback a libx264
    if use_nvenc:
        print(f"⚠️ NVENC falló, intentando libx264...")
        fallback_cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(vocals_es_path),
            "-i",
            str(no_vocals_path),
            "-filter_complex",
            "[0]volume=0.00[a0];[1]volume=3.5[a1];[2]volume=1.0[a2];[a0][a1][a2]amix=inputs=3[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(temp_output_path),
        ]
        result = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            if final_output_path.exists():
                final_output_path.unlink()
            temp_output_path.rename(final_output_path)
            return final_output_path

    print(f"❌ Error al renderizar: {result.stderr}")
    if temp_output_path.exists():
        temp_output_path.unlink()
    raise RuntimeError(f"Error en ffmpeg: {result.stderr}")


def get_video_metadata(video_path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)


def create_low_res_preview(input_path: Path, output_path: Path | None = None) -> Path:
    """Crea una versión de baja resolución para preview."""
    if output_path is None:
        output_path = input_path.parent / "low_preview.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-vf",
        "scale=360:-1",
        "-c:a",
        "copy",
        "-vcodec",
        "libx264",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    return output_path


def upload_to_catbox(file_path: Path) -> str:
    """Sube archivo a Catbox (24h). Returns URL o vacío."""
    # Catbox/litterbox a veces falla con filenames Unicode/emoji en multipart.
    # Forzamos un filename ASCII corto y estable.
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
    print(f"⚠️ Error al subir: {result.stderr}")
    return ""
