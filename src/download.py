"""
Descarga de videos YouTube (yt-dlp) y separación de voces (Demucs).
"""
import os
import subprocess
from pathlib import Path

from src.config import BASE_DIR, QUEUE_DIR, DRIVE_DIR, google_drive


class OneLineLogger:
    """Solo imprime una línea por descarga (al 100%%) para no saturar el log."""
    def debug(self, msg):
        if msg.startswith("[download]"):
            if "100%" in msg:
                print(msg)

    def info(self, msg): print(f"\nℹ️ {msg}")
    def warning(self, msg): print(f"\n⚠️ {msg}")
    def error(self, msg): pass


def download_video(
    url: str,
    output_dir: Path | None = None,
    resolution: int | None = None,
    language: str | None = None,
) -> tuple[Path, dict]:
    """
    Descarga un video de YouTube y extrae información.
    Returns: (path, info)
    """
    if output_dir is None:
        output_dir = QUEUE_DIR

    from yt_dlp import YoutubeDL

    cookies_file = (DRIVE_DIR / "cookies.txt") if DRIVE_DIR else None

    video = "bv[vcodec^=avc1]"
    if resolution:
        video += f"[width<={resolution}]"
    audio = f"ba[language^={language}]" if language else "ba"

    opts = {
        "outtmpl": str(output_dir / "%(title)s" / "%(title)s.%(ext)s"),
        "format": f"{video} + {audio}",
        "merge_output_format": "mp4",
        "logger": OneLineLogger(),
        "quiet": True,
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://www.google.com/",
    }
    if cookies_file and cookies_file.exists():
        opts["cookiefile"] = str(cookies_file)

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            media = info["requested_downloads"][0]["filepath"]
            vcodec = info.get("vcodec", "N/A")
            acodec = info.get("acodec", "N/A")
            fmt = info.get("format", "N/A")
            fps = info.get("fps", "N/A")
            print(f"✅ {Path(media).name}  =>  {vcodec}  ||  {acodec}  ||  {fmt}  ||  {fps}")
            return Path(media), info
    except Exception as e:
        print(f"❌ Error al descargar video: {e}")
        raise


def separate_vocals(video_path: Path, output_dir: Path | None = None) -> tuple[Path, Path]:
    """
    Separa las voces del audio usando Demucs.
    Returns: (vocals_path, no_vocals_path)
    """
    from src.config import DEMUCS_DIR

    if output_dir is None:
        output_dir = video_path.parent

    vocals_path = output_dir / "vocals.wav"
    no_vocals_path = output_dir / "no_vocals.wav"

    if vocals_path.exists() and no_vocals_path.exists():
        print("✅ Audio de voz ya existe.")
        return vocals_path, no_vocals_path

    if not DEMUCS_DIR.exists():
        raise FileNotFoundError(
            f"Demucs no encontrado en {DEMUCS_DIR}. "
            "En Colab ejecuta el script de setup o clona: git clone https://github.com/adefossez/demucs.git /content/demucs"
        )

    original_dir = os.getcwd()
    try:
        os.chdir(DEMUCS_DIR)
        cmd = f'python -m demucs.separate "{video_path}" --two-stems vocals -o "{output_dir}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"⚠️ Advertencia en separación: {result.stderr}")

        demucs_output = output_dir / "htdemucs" / video_path.stem
        if demucs_output.exists():
            vocals_temp = demucs_output / "vocals.wav"
            no_vocals_temp = demucs_output / "no_vocals.wav"
            if vocals_temp.exists():
                vocals_temp.rename(vocals_path)
            if no_vocals_temp.exists():
                no_vocals_temp.rename(no_vocals_path)
            subprocess.run(f'rm -rf "{demucs_output.parent}"', shell=True)

        return vocals_path, no_vocals_path
    finally:
        os.chdir(original_dir)


def yt(url: str, demucs: bool = True) -> tuple[Path, dict]:
    """Descarga video y opcionalmente separa voces. Returns (path, info)."""
    path, info = download_video(url)
    if demucs:
        separate_vocals(path)
    return path, info
