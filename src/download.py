"""
Descarga de videos YouTube (yt-dlp) y separación de voces (BS-RoFormer).
Los activos generados se registran en v2v_assets.json de la carpeta del job.
"""

import io
import time
import contextlib
from pathlib import Path

from src.config import (
    BASE_DIR,
    QUEUE_DIR,
    DRIVE_DIR,
    KAGGLE_INPUT_DIR,
    DEVICE_SECONDARY,
    google_drive,
    get_hf_token,
)
from src.models import get_or_load_model
from src.assets import update_assets

ROFORMER_DIR = DRIVE_DIR / "bs-roformer-revive3e" if DRIVE_DIR else None


def to_safe_name(text: str) -> str:
    """Genera un nombre de archivo seguro para el sistema operativo."""
    import re
    import unicodedata

    # Normalizar para quitar tildes y caracteres especiales
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # Eliminar hashtags (ej. #shorts)
    text = re.sub(r"#\S+", "", text)
    # Solo permitir letras, números, espacios, puntos, guiones y guiones bajos
    text = re.sub(r"[^\w\s.\-_]", "", text)
    # Reemplazar espacios y múltiples puntos/guiones por un solo guion bajo
    text = re.sub(r"[\s.\-_]+", "_", text)
    # Limitar longitud para evitar errores de path demasiado largo (Windows)
    return text.strip("_").strip()[:80] or "video"


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

    # Buscar carpeta de BS-RoFormer en Drive, Kaggle input o rutas locales
    candidates = []
    if ROFORMER_DIR:
        candidates.append(ROFORMER_DIR)
    if KAGGLE_INPUT_DIR and KAGGLE_INPUT_DIR.exists():
        candidates.extend([
            KAGGLE_INPUT_DIR / "bs-roformer-revive3e",
            KAGGLE_INPUT_DIR / "v2v-models" / "bs-roformer-revive3e",
            KAGGLE_INPUT_DIR / "bs-roformer" / "bs-roformer-revive3e",
            KAGGLE_INPUT_DIR / "bs_roformer_revive3e",
        ])
    candidates.extend([
        BASE_DIR / "bs-roformer-revive3e",
        BASE_DIR / "models" / "bs-roformer-revive3e",
        Path("bs-roformer-revive3e"),
        Path("models/bs-roformer-revive3e"),
    ])

    roformer_path = None
    for cand in candidates:
        if cand and cand.exists() and (cand / "bs_roformer_revive3e.ckpt").exists():
            roformer_path = cand
            break

    if not roformer_path:
        dest_dir = ROFORMER_DIR or (BASE_DIR / "models" / "bs-roformer-revive3e")
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"📥 Descargando modelo BS-RoFormer (Revive3e) desde Hugging Face hacia {dest_dir}...")
        try:
            from huggingface_hub import hf_hub_download
            token = get_hf_token()
            for fname in ("config.yaml", "bs_roformer_revive3e.ckpt"):
                hf_hub_download(
                    repo_id="pcunwa/BS-Roformer-Revive",
                    filename=fname,
                    local_dir=str(dest_dir),
                    token=token,
                )
            roformer_path = dest_dir
            print("✅ Modelo BS-RoFormer descargado correctamente.")
        except Exception as e:
            raise FileNotFoundError(
                f"No se encontró el modelo BS-RoFormer y falló la auto-descarga desde Hugging Face: {e}. "
                f"Asegúrate de colocar 'bs_roformer_revive3e.ckpt' y 'config.yaml' en {dest_dir}."
            ) from e

    model_path = roformer_path / "bs_roformer_revive3e.ckpt"
    config_path = roformer_path / "config.yaml"

    if not config_path.exists():
        try:
            from huggingface_hub import hf_hub_download
            hf_hub_download(
                repo_id="pcunwa/BS-Roformer-Revive",
                filename="config.yaml",
                local_dir=str(roformer_path),
                token=get_hf_token(),
            )
        except Exception:
            pass

    if not config_path.exists():
        raise FileNotFoundError(
            f"No se encontró 'config.yaml' de BS-RoFormer en {roformer_path}."
        )

    with open(config_path) as f:
        config = ConfigDict(yaml.load(f, Loader=SafeLoaderWithTuple))

    model = get_model_from_config("bs_roformer", config)
    state = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state)

    device = torch.device(DEVICE_SECONDARY if torch.cuda.is_available() else "cpu")
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
    Descarga un video de YouTube con yt-dlp (keepvideo=True).

    Registra en v2v_assets.json:
      - merged:     video resultante (video+audio mezclados por ffmpeg)
      - video_only: stream de video intermedio de yt-dlp (ej. f137.mp4)
      - audio_only: stream de audio intermedio de yt-dlp (ej. f251.webm)

    Returns: (merged_path, yt_dlp_info)
    """
    if output_dir is None:
        output_dir = QUEUE_DIR

    from yt_dlp import YoutubeDL

    cookies_file = (DRIVE_DIR / "cookies.txt") if DRIVE_DIR else None

    # Configuración de video/audio única
    video = "bv[vcodec^=avc1]"
    if resolution:
        video += f"[width<={resolution}]"
    audio = f"ba[language^={language}]" if language else "ba"

    opts = {
        "format": f"{video} + {audio}",
        "keepvideo": True,
        "logger": OneLineLogger(),
        "quiet": True,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://www.google.com/",
    }
    if cookies_file and cookies_file.exists():
        opts["cookiefile"] = str(cookies_file)

    t_start_dl = time.perf_counter()
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "video")
        safe_name = to_safe_name(title)
        
        # Ajustar outtmpl de forma compatible con yt-dlp (espera un dict o objeto con .get)
        ydl.params["outtmpl"] = {"default": str(output_dir / safe_name / f"{safe_name}.%(ext)s")}
        
        media = ydl.prepare_filename(info)
        print(f"✅ {title}") # Mostramos título real en log
        print_codecs(info)
        ydl.download([url])
        media_path = Path(media)

    dl_elapsed = time.perf_counter() - t_start_dl
    info["_download_time"] = dl_elapsed
    print(f"⏱️ [Etapa: Descarga] Completada en {dl_elapsed:.1f}s")

    # --- Registro determinista en manifiesto ---
    folder = media_path.parent
    asset_update: dict = {"merged": str(media_path)}

    requested = info.get("requested_formats") or []
    # yt-dlp requested_formats[0] suele ser el video y [1] el audio en modo dash.
    # Si bajó un solo archivo (ej format 18), 'requested' podría estar vacío.
    
    v_cand = None
    a_cand = None

    if requested:
        # Modo estándar: Video + Audio separados
        v_info = requested[0]
        a_info = requested[1]
        v_cand = folder / f"{media_path.stem}.f{v_info['format_id']}.{v_info['ext']}"
        a_cand = folder / f"{media_path.stem}.f{a_info['format_id']}.{a_info['ext']}"
    else:
        # Modo merged (ej. format 18): Hay que separar manualmente para el pipeline
        v_ext = info.get("ext", "mp4")
        acodec = info.get("acodec", "").lower()
        if "mp4a" in acodec or "aac" in acodec: a_ext = "m4a"
        elif "opus" in acodec: a_ext = "webm"
        else: a_ext = v_ext 
        
        v_cand = folder / f"{media_path.stem}.v{info.get('format_id', '18')}.{v_ext}"
        a_cand = folder / f"{media_path.stem}.a{info.get('format_id', '18')}.{a_ext}"
        
        if not v_cand.exists() or not a_cand.exists():
            import subprocess
            print(f"📦 Separando flujos del video merged (fallback ffmpeg -c copy)...")
            try:
                # Extraer video sin audio (copy)
                subprocess.run(["ffmpeg", "-y", "-i", str(media_path), "-map", "0:v", "-c:v", "copy", "-an", str(v_cand)], check=True, capture_output=True)
                # Extraer audio sin video (copy)
                subprocess.run(["ffmpeg", "-y", "-i", str(media_path), "-map", "0:a", "-c:a", "copy", "-vn", str(a_cand)], check=True, capture_output=True)
            except Exception as e:
                print(f"⚠️ Error en fallback de separación: {e}")

    if v_cand and v_cand.exists():
        asset_update["video_only"] = str(v_cand)
    if a_cand and a_cand.exists():
        asset_update["audio_only"] = str(a_cand)

    update_assets(folder, **asset_update)
    return media_path, info
    

def separate_vocals(
    video_path: Path, output_dir: Path | None = None
) -> tuple[Path, Path]:
    """
    Separa las voces del audio usando BS-RoFormer.

    Registra en v2v_assets.json:
      - vocals:    pista de voz extraída (vocals.wav)
      - no_vocals: pista instrumental sin voz (no_vocals.wav)

    Returns: (vocals_path, no_vocals_path)
    """
    import torch
    import torchaudio
    from bs_roformer.utils import demix_track

    if output_dir is None:
        output_dir = video_path.parent

    vocals_path = output_dir / "vocals.wav"
    no_vocals_path = output_dir / "no_vocals.wav"

    t_start_sep = time.perf_counter()
    if vocals_path.exists() and no_vocals_path.exists():
        sep_elapsed = time.perf_counter() - t_start_sep
        print(f"♻️ Audio de voz ya existe en caché ({sep_elapsed:.2f}s).")
        # Registrar aunque ya existan (recuperación de caché)
        update_assets(output_dir, vocals=str(vocals_path), no_vocals=str(no_vocals_path))
        return vocals_path, no_vocals_path

    # 1) Cargar modelo BS-RoFormer (cacheado con get_or_load_model)
    config, model, device = get_roformer_model()

    # 2) Leer audio directamente del video (con fallback robusto a FFmpeg)
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

    sep_elapsed = time.perf_counter() - t_start_sep
    print(f"⏱️ [Etapa: Separación Stems (BS-RoFormer)] Completada en {sep_elapsed:.1f}s")

    # --- Registro determinista en manifiesto ---
    update_assets(
        output_dir,
        vocals=str(vocals_path) if vocals_path.exists() else None,
        no_vocals=str(no_vocals_path) if no_vocals_path.exists() else None,
    )

    return vocals_path, no_vocals_path


def yt(url: str, vocals_separation: bool = True) -> tuple[Path, dict]:
    """Descarga video y opcionalmente separa voces. Returns (path, info)."""
    path, info = download_video(url)
    if vocals_separation:
        separate_vocals(path)
    return path, info
