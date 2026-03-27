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
            if "100%" in msg:
                print(msg)

    def info(self, msg):
        print(f"\nℹ️ {msg}")

    def warning(self, msg):
        print(f"\n⚠️ {msg}")

    def error(self, msg):
        pass


def print_codecs(info):
    v = info.get("requested_formats", [])[0]
    a = info.get("requested_formats", [])[1]

    print(
        f"Video: itag {v['format_id']} | {v.get('ext')} | {v.get('vcodec')} | {v.get('height')}p | {v.get('fps')}fps"
    )
    print(
        f"Audio: itag {a['format_id']} | {a.get('ext')} | {a.get('acodec')} | {a.get('asr')}Hz | {a.get('abr')}kbps"
    )


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
        # Mantener los archivos intermedios (bestvideo/bestaudio) para poder
        # reutilizar el video-only sin un paso extra de ffmpeg (-an).
        "keepvideo": True,
        "logger": OneLineLogger(),
        "quiet": True,
        "js_runtimes": {"node": {}},
        "remote_components": ["ejs:github"],
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://www.google.com/",
    }
    if cookies_file and cookies_file.exists():
        opts["cookiefile"] = str(cookies_file)

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            media = ydl.prepare_filename(info)
            print(f"✅ {Path(media).name}")
            print_codecs(info)
            ydl.download([url])
            media_path = Path(media)

            # Guardar paths útiles en info para el resto del pipeline:
            # - merged (media_path)
            # - video-only descargado por yt-dlp (requested_formats[0])
            try:
                info["_v2v_paths"] = info.get("_v2v_paths") or {}
                info["_v2v_paths"]["merged"] = str(media_path)

                requested = info.get("requested_formats") or []
                if len(requested) >= 1:
                    v = requested[0] or {}
                    # yt-dlp suele dejar `filepath` tras la descarga; si no, intentamos `filename`.
                    vpath = v.get("filepath") or v.get("filename")
                    if vpath:
                        info["_v2v_paths"]["video_only"] = str(Path(vpath))
                if len(requested) >= 2:
                    a = requested[1] or {}
                    apath = a.get("filepath") or a.get("filename")
                    if apath:
                        info["_v2v_paths"]["audio_only"] = str(Path(apath))
            except Exception as e:
                print(f"⚠️ No se pudieron registrar paths de descarga: {e}")

            # Fallback: buscar archivos intermedios de yt-dlp (f137.mp4, f251.webm, etc.)
            # o generar *_video.mp4 / *_audio.m4a solo si faltan.
            try:
                v2v_paths = info.get("_v2v_paths") if isinstance(info, dict) else {}
                existing_vonly = (
                    Path(v2v_paths.get("video_only"))
                    if isinstance(v2v_paths, dict) and v2v_paths.get("video_only")
                    else None
                )
                existing_aonly = (
                    Path(v2v_paths.get("audio_only"))
                    if isinstance(v2v_paths, dict) and v2v_paths.get("audio_only")
                    else None
                )

                # Buscar archivos intermedios de yt-dlp que coincidan con el patrón
                # yt-dlp nombra: titulo.f137.mp4 (video), titulo.f251.webm (audio)
                video_pattern = f"{media_path.stem}.f*.mp4"
                audio_pattern = f"{media_path.stem}.f*.webm"

                yt_video_files = list(media_path.parent.glob(video_pattern))
                yt_audio_files = list(media_path.parent.glob(audio_pattern))

                # Si yt-dlp ya generó los archivos intermedios, usarlos
                if not existing_vonly or not existing_vonly.exists():
                    if yt_video_files:
                        existing_vonly = yt_video_files[0]
                        if isinstance(info, dict):
                            info.setdefault("_v2v_paths", {})
                            info["_v2v_paths"]["video_only"] = str(existing_vonly)

                if not existing_aonly or not existing_aonly.exists():
                    if yt_audio_files:
                        existing_aonly = yt_audio_files[0]
                        if isinstance(info, dict):
                            info.setdefault("_v2v_paths", {})
                            info["_v2v_paths"]["audio_only"] = str(existing_aonly)

                # Solo generar fallbacks si NO hay archivos de yt-dlp ni paths registrados
                if not existing_vonly or not existing_vonly.exists():
                    video_only_path = media_path.with_name(
                        f"{media_path.stem}_video{media_path.suffix}"
                    )
                    if not video_only_path.exists():
                        cmd = [
                            "ffmpeg",
                            "-y",
                            "-v",
                            "error",
                            "-i",
                            str(media_path),
                            "-c",
                            "copy",
                            "-an",
                            str(video_only_path),
                        ]
                        subprocess.run(cmd, capture_output=True, text=True, check=False)
                        existing_vonly = video_only_path

                    if isinstance(info, dict):
                        info.setdefault("_v2v_paths", {})
                        info["_v2v_paths"]["video_only"] = str(video_only_path)

                if not existing_aonly or not existing_aonly.exists():
                    audio_only_path = media_path.with_name(
                        f"{media_path.stem}_audio.m4a"
                    )
                    if not audio_only_path.exists():
                        cmd_a = [
                            "ffmpeg",
                            "-y",
                            "-v",
                            "error",
                            "-i",
                            str(media_path),
                            "-vn",
                            "-c",
                            "copy",
                            str(audio_only_path),
                        ]
                        subprocess.run(
                            cmd_a, capture_output=True, text=True, check=False
                        )
                        existing_aonly = audio_only_path

                    if isinstance(info, dict):
                        info.setdefault("_v2v_paths", {})
                        info["_v2v_paths"]["audio_only"] = str(audio_only_path)
            except Exception as e:
                print(f"⚠️ No se pudo generar/registrar video_only fallback: {e}")

            return media_path, info
    except Exception as e:
        print(f"❌ Error al descargar video: {e}")
        raise


def separate_vocals(
    video_path: Path, output_dir: Path | None = None
) -> tuple[Path, Path]:
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

    mix, sr = torchaudio.load(str(video_path))
    original_channels = mix.shape[0]
    if original_channels == 1:
        mix = torch.cat([mix, mix], dim=0)
    mixture = mix.to(torch.float32)

    # 3) Separar stems con BS-RoFormer, ocultando logs internos de la librería
    with torch.no_grad():
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
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
        print(f"🎧 Audio separado correctamente")

    return vocals_path, no_vocals_path


def yt(url: str, vocals_separation: bool = True) -> tuple[Path, dict]:
    """Descarga video y opcionalmente separa voces. Returns (path, info)."""
    path, info = download_video(url)
    if vocals_separation:
        separate_vocals(path)
    return path, info
