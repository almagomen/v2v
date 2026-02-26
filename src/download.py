"""
Descarga de videos YouTube (yt-dlp) y separación de voces (BS-RoFormer).
"""
import os
import re
import subprocess
import io
import contextlib
from pathlib import Path

from src.config import BASE_DIR, QUEUE_DIR, DRIVE_DIR, google_drive
from src.models import get_or_load_model

ROFORMER_DIR = DRIVE_DIR / "bs-roformer-revive3e" if DRIVE_DIR else None


def _load_bs_roformer():
    """
    Loader puro de BS-RoFormer. Devuelve (config, model, device).
    Se cachea vía get_or_load_model.
    """
    import torch
    import yaml
    from ml_collections import ConfigDict
    from bs_roformer.utils import get_model_from_config
    from bs_roformer.inference import SafeLoaderWithTuple

    if not ROFORMER_DIR or not ROFORMER_DIR.exists():
        raise FileNotFoundError(
            "No se encontró el directorio de BS-RoFormer. "
            "Asegúrate de montar Drive y crear la carpeta 'bs-roformer-revive3e' en "
            f"{DRIVE_DIR} con los archivos del modelo."
        )

    model_path = ROFORMER_DIR / "bs_roformer_revive3e.ckpt"
    config_path = ROFORMER_DIR / "config.yaml"

    if not model_path.exists() or not config_path.exists():
        raise FileNotFoundError(
            "No se encontraron los archivos de BS-RoFormer en "
            f"{ROFORMER_DIR}. Esperado: bs_roformer_revive3e.ckpt y config.yaml."
        )

    with open(config_path) as f:
        config = ConfigDict(yaml.load(f, Loader=SafeLoaderWithTuple))

    model = get_model_from_config("bs_roformer", config)
    state = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    model.eval()

    return config, model, device


def get_roformer_model():
    """
    Helper para Colab y para separación: usa caché global de modelos.
    """
    return get_or_load_model("bs_roformer", _load_bs_roformer)

class OneLineLogger:
    """Solo imprime una línea por descarga (al 100%%) para no saturar el log."""
    def debug(self, msg):
        if msg.startswith("[download]"):
            if "100%" in msg: print(msg)

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
    if output_dir is None: output_dir = QUEUE_DIR

    from yt_dlp import YoutubeDL

    cookies_file = (DRIVE_DIR / "cookies.txt") if DRIVE_DIR else None

    video = "bv[vcodec^=avc1]"
    if resolution: video += f"[width<={resolution}]"
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
    if cookies_file and cookies_file.exists(): opts["cookiefile"] = str(cookies_file)

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            media = info["requested_downloads"][0]["filepath"]
            vcodec = info.get("vcodec", "N/A")
            acodec = info.get("acodec", "N/A")
            fmt = info.get("format", "N/A")
            fps = info.get("fps", "N/A")
            print(f"✅ {Path(media).name}  🚩  {vcodec}  ||  {acodec}  ||  {fmt}  ||  {fps}")
            return Path(media), info
    except Exception as e:
        print(f"❌ Error al descargar video: {e}")
        raise



def separate_vocals(video_path: Path, output_dir: Path | None = None) -> tuple[Path, Path]:
    """
    Separa las voces del audio usando BS-RoFormer.
    Returns: (vocals_path, no_vocals_path)
    """
    import torch
    import torchaudio
    from bs_roformer.utils import demix_track

    if output_dir is None:
        output_dir = video_path.parent

    vocals_path = output_dir / "vocals.wav"
    no_vocals_path = output_dir / "no_vocals.wav"

    if vocals_path.exists() and no_vocals_path.exists():
        print("✅ Audio de voz ya existe.")
        return vocals_path, no_vocals_path

    # 1) Cargar modelo BS-RoFormer (cacheado con get_or_load_model)
    config, model, device = get_roformer_model()

    # 2) Leer audio directamente del video con torchaudio (backend ffmpeg)
    print(f"🎧 Separando audio (BS-RoFormer): {video_path.stem}")
    mix, sr = torchaudio.load(str(video_path))
    original_channels = mix.shape[0]
    if original_channels == 1:
        mix = torch.cat([mix, mix], dim=0)
    mixture = mix.to(torch.float32)

    # 3) Separar stems con BS-RoFormer, ocultando logs internos de la librería
    with torch.no_grad():
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result, _ = demix_track(config, model, mixture, device)

    # Guardar stems individuales (vocals, drums, bass, etc.)
    for instrument, audio in result.items():
        output = torch.from_numpy(audio)
        if original_channels == 1:
            output = output[0:1, :]
        output_path = output_dir / f"{instrument}.wav"
        torchaudio.save(str(output_path), output, sr)

    # Calcular pista sin voz (no_vocals.wav) a partir del mix original
    if "vocals" in result:
        mix_cpu = mixture.cpu()
        vocals_np = result["vocals"]
        vocals_tensor = torch.from_numpy(vocals_np).to(mix_cpu.dtype)
        instrumental = mix_cpu - vocals_tensor

        if original_channels == 1:
            instrumental = instrumental[0:1, :]

        torchaudio.save(str(no_vocals_path), instrumental, sr)
        print(f"Saved: {no_vocals_path}")

    return vocals_path, no_vocals_path


def yt(url: str, vocals_separation: bool = True) -> tuple[Path, dict]:
    """Descarga video y opcionalmente separa voces. Returns (path, info)."""
    path, info = download_video(url)
    if vocals_separation:
        separate_vocals(path)
    return path, info
