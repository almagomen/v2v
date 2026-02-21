"""
Renderizado de video final: ffmpeg, preview baja res, upload opcional.
"""
import json
import subprocess
from pathlib import Path

from src.config import TEMP_DIR


def render_video(
    video_path: Path,
    output_name: str,
    vocals_es_path: Path,
    no_vocals_path: Path,
    output_dir: Path | None = None,
) -> Path:
    """Renderiza el video final combinando video original con audio clonado."""
    if output_dir is None:
        output_dir = TEMP_DIR
    output_path = output_dir / f"{output_name}.mp4"

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(video_path),
        "-i", str(vocals_es_path),
        "-i", str(no_vocals_path),
        "-filter_complex",
        "[0]volume=0.00[a0];[1]volume=3.5[a1];[2]volume=1.0[a2];[a0][a1][a2]amix=inputs=3[a]",
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return output_path
    print(f"❌ Error al renderizar: {result.stderr}")
    raise RuntimeError(f"Error en ffmpeg: {result.stderr}")


def get_video_metadata(video_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)


def create_low_res_preview(input_path: Path, output_path: Path | None = None) -> Path:
    """Crea una versión de baja resolución para preview."""
    if output_path is None:
        output_path = input_path.parent / "low_preview.mp4"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(input_path),
        "-vf", "scale=360:-1",
        "-c:a", "copy",
        "-vcodec", "libx264",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    return output_path


def upload_to_catbox(file_path: Path) -> str:
    """Sube archivo a Catbox (24h). Returns URL o vacío."""
    cmd = [
        "curl", "-F", "reqtype=fileupload",
        "-F", "time=24h",
        "-F", f"fileToUpload=@{file_path}",
        "https://litterbox.catbox.moe/resources/internals/api.php",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    print(f"⚠️ Error al subir: {result.stderr}")
    return ""
