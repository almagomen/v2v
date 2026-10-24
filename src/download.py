"""
Descarga de videos YouTube (yt-dlp) y separación de voces (BS-RoFormer).
Los activos generados se registran en result.json ('assets') de la carpeta del job.
"""

import io
import sys
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
    is_kaggle,
)
from src.models import get_or_load_model
from src.assets import update_assets

ROFORMER_DIR = DRIVE_DIR / "bs-roformer-revive3e" if DRIVE_DIR else None
_COOKIES_LOGGED: bool = False


def find_youtube_cookies_file() -> Path | None:
    """Busca cookies.txt en datasets de Kaggle o en Google Drive (Colab)."""
    # 1. Dataset en Kaggle
    cand_found = None
    kaggle_specific = Path("/kaggle/input/datasets/manuelarvelaez/upload/cookies.txt")
    if kaggle_specific.is_file() and kaggle_specific.stat().st_size > 0:
        cand_found = kaggle_specific
    elif is_kaggle() and Path("/kaggle/input").exists():
        try:
            for cand in Path("/kaggle/input").glob("**/cookies.txt"):
                if cand.is_file() and cand.stat().st_size > 0:
                    cand_found = cand
                    break
        except Exception:
            pass

    if cand_found:
        # En Kaggle, /kaggle/input es Read-Only. Al cerrar, yt-dlp intenta guardar
        # la sesión actualizada de cookies con save_cookies() (open 'w'), fallando si es solo lectura.
        # Copiamos a BASE_DIR (directorio escribible) para evitar el error.
        import shutil
        writable_cookies = BASE_DIR / "cookies.txt"
        try:
            shutil.copyfile(cand_found, writable_cookies)
            return writable_cookies
        except Exception:
            return cand_found

    # 2. Google Drive (Colab)
    if DRIVE_DIR:
        cand = DRIVE_DIR / "cookies.txt"
        if cand.is_file() and cand.stat().st_size > 0:
            return cand
    cand_drive = Path("/content/drive/MyDrive/cookies.txt")
    if cand_drive.is_file() and cand_drive.stat().st_size > 0:
        return cand_drive

    return None


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
    state = torch.load(model_path, map_location="cpu", weights_only=True)
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


def _get_roformer_gpu0(config, primary_model):
    """Crea una réplica del modelo BS-RoFormer en cuda:0 para modo Dual-GPU."""
    from bs_roformer.utils import get_model_from_config
    model_0 = get_model_from_config("bs_roformer", config)
    model_0.load_state_dict(primary_model.state_dict())
    model_0 = model_0.to("cuda:0")
    model_0.eval()
    return model_0


def preload_roformer_models():
    """
    Precarga los modelos de BS-RoFormer en GPU.
    Si hay >= 2 GPUs, precarga tanto el primario (cuda:1) como la réplica bs_roformer_gpu0 (cuda:0).
    """
    import torch
    config, model, device = get_roformer_model()
    if torch.cuda.is_available() and torch.cuda.device_count() >= 2:
        get_or_load_model("bs_roformer_gpu0", _get_roformer_gpu0, config, model)
    return config, model, device


# Solapamiento fijo de 2.0 segundos con crossfade entre GPU 0 y GPU 1:
# Imprescindible para eliminar el "tic" o discontinuidad de fase/borde en la STFT de BS-RoFormer.
DUAL_GPU_OVERLAP_SEC: float = 2.0


def _demix_dual_gpu(
    config,
    model_0,
    model_1,
    mixture,
    sr: int,
) -> dict:
    """
    Divide el audio en 2 bloques solapados (2.0s) y ejecuta la inferencia en paralelo
    en GPU 0 y GPU 1 usando ThreadPoolExecutor.
    Aplica crossfade suave en la unión para eliminar cualquier artefacto de borde ("tic").
    """
    import numpy as np
    import torch
    import concurrent.futures
    from bs_roformer.utils import demix_track

    total_samples = mixture.shape[1]
    overlap_samples = min(int(DUAL_GPU_OVERLAP_SEC * sr), total_samples // 4)
    mid = total_samples // 2

    if overlap_samples > 0:
        chunk_0 = mixture[:, : mid + overlap_samples]
        chunk_1 = mixture[:, mid - overlap_samples :]
    else:
        chunk_0 = mixture[:, :mid]
        chunk_1 = mixture[:, mid:]

    def _infer_chunk(m, chunk, dev):
        with torch.no_grad():
            res, _ = demix_track(config, m, chunk, dev)
            return res

    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    try:
        sys.stdout = io.StringIO()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f0 = executor.submit(_infer_chunk, model_0, chunk_0, torch.device("cuda:0"))
            f1 = executor.submit(_infer_chunk, model_1, chunk_1, torch.device("cuda:1"))
            res_0 = f0.result()
            res_1 = f1.result()
    finally:
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr

    merged_results = {}
    if overlap_samples > 0:
        fade_len = 2 * overlap_samples
        fade_in = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
        fade_out = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)

        for stem in res_0.keys():
            out_0 = res_0[stem]
            out_1 = res_1[stem]

            part_a = out_0[:, : mid - overlap_samples]
            overlap_a = out_0[:, mid - overlap_samples : mid + overlap_samples]
            overlap_b = out_1[:, :fade_len]
            blended = overlap_a * fade_out + overlap_b * fade_in
            part_b = out_1[:, fade_len:]

            merged = np.concatenate([part_a, blended, part_b], axis=1)
            if merged.shape[1] > total_samples:
                merged = merged[:, :total_samples]
            elif merged.shape[1] < total_samples:
                pad = np.zeros((merged.shape[0], total_samples - merged.shape[1]), dtype=merged.dtype)
                merged = np.concatenate([merged, pad], axis=1)
            merged_results[stem] = merged
    else:
        for stem in res_0.keys():
            merged = np.concatenate([res_0[stem], res_1[stem]], axis=1)
            if merged.shape[1] > total_samples:
                merged = merged[:, :total_samples]
            elif merged.shape[1] < total_samples:
                pad = np.zeros((merged.shape[0], total_samples - merged.shape[1]), dtype=merged.dtype)
                merged = np.concatenate([merged, pad], axis=1)
            merged_results[stem] = merged

    return merged_results


class OneLineLogger:
    """Silencia los logs verbosos de progreso de yt-dlp."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        print(f"\n⚠️ {msg}")

    def error(self, msg):
        pass


def print_codecs(info):
    v = info.get("requested_formats", [])[0]
    a = info.get("requested_formats", [])[1]

    dur = info.get("duration")
    dur_text = ""
    if dur:
        m, s = divmod(int(dur), 60)
        dur_text = f" | {m}m {s:02d}s" if m > 0 else f" | {s}s"
    elif info.get("duration_string"):
        dur_text = f" | {info.get('duration_string')}"

    print(
        f"Video: itag {v['format_id']} | {v.get('ext')} | {v.get('vcodec')} | {v.get('height')}p | {v.get('fps')}fps{dur_text}"
    )
    print(
        f"Audio: itag {a['format_id']} | {a.get('ext')} | {a.get('acodec')} | {a.get('asr')}Hz | {a.get('abr')}kbps"
    )


def download_video(
    url: str,
    output_dir: Path | None = None,
    resolution: int | None = None,
    language: str | None = None,
    force_new: bool = False,
) -> tuple[Path, dict]:
    """
    Descarga un video de YouTube con yt-dlp (keepvideo=True).

    Registra en result.json ('assets'):
      - merged:     video resultante (video+audio mezclados por ffmpeg)
      - video_only: stream de video intermedio de yt-dlp (ej. f137.mp4)
      - audio_only: stream de audio intermedio de yt-dlp (ej. f251.webm)

    Returns: (merged_path, yt_dlp_info)
    """
    if output_dir is None:
        output_dir = QUEUE_DIR

    from yt_dlp import YoutubeDL

    global _COOKIES_LOGGED
    cookies_file = find_youtube_cookies_file()

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
        if not _COOKIES_LOGGED:
            print(f"🍪 [yt-dlp] Cookies de YouTube: {cookies_file}", flush=True)
            _COOKIES_LOGGED = True
        opts["cookiefile"] = str(cookies_file)

    t_start_dl = time.perf_counter()
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "video")
        base_name = to_safe_name(title)

        target_name = base_name
        if force_new and (output_dir / base_name).exists():
            counter = 2
            candidate = f"{base_name}_v{counter}"
            while (output_dir / candidate).exists():
                counter += 1
                candidate = f"{base_name}_v{counter}"
            target_name = candidate
            print(f"📁 [Versión Nueva] Creando carpeta no destructiva: {target_name} (proyecto original protegido)")

        info["safe_name"] = target_name
        info["output_name"] = target_name

        # Ajustar outtmpl de forma compatible con yt-dlp (espera un dict o objeto con .get)
        ydl.params["outtmpl"] = {"default": str(output_dir / target_name / f"{target_name}.%(ext)s")}

        media = ydl.prepare_filename(info)
        print(f"✅ {title}")
        ydl.download([url])
        media_path = Path(media)

    dl_elapsed = time.perf_counter() - t_start_dl
    info["_download_time"] = dl_elapsed

    # --- Registro determinista en manifiesto ---
    folder = media_path.parent
    asset_update: dict = {"merged": media_path.name}

    requested = info.get("requested_formats") or []
    
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
                subprocess.run(["ffmpeg", "-y", "-i", str(media_path), "-map", "0:v", "-c:v", "copy", "-an", str(v_cand)], check=True, capture_output=True)
                subprocess.run(["ffmpeg", "-y", "-i", str(media_path), "-map", "0:a", "-c:a", "copy", "-vn", str(a_cand)], check=True, capture_output=True)
            except Exception as e:
                print(f"⚠️ Error en fallback de separación: {e}")

    # Mostrar información formateada de video y audio con sus tamaños reales
    def _fmt_size(p: Path | None, fallback_bytes: int | float | None = None) -> str:
        sz = 0
        if p and p.exists():
            try:
                sz = p.stat().st_size
            except Exception:
                pass
        if sz <= 0 and fallback_bytes:
            sz = fallback_bytes
        return f"{sz / (1024 * 1024):.2f}MiB" if sz > 0 else "0.00MiB"

    v_size_str = _fmt_size(v_cand, v_info.get("filesize") or v_info.get("filesize_approx") if requested else None)
    a_size_str = _fmt_size(a_cand, a_info.get("filesize") or a_info.get("filesize_approx") if requested else None)

    dur = info.get("duration")
    dur_text = ""
    if dur:
        m, s = divmod(int(dur), 60)
        dur_text = f"| {m}m {s:02d}s" if m > 0 else f" | {s}s"
    elif info.get("duration_string"):
        dur_text = f"| {info.get('duration_string')}"

    if requested:
        v_ext = v_info.get("ext", "mp4")
        v_cod = v_info.get("vcodec", "avc1")
        v_h = v_info.get("height", "1080")
        v_fps = v_info.get("fps", 30)
        print(f"📹 {v_ext} {v_cod} | {v_h}p {v_fps}fps {dur_text} {v_size_str}")

        a_ext = a_info.get("ext", "webm")
        a_cod = a_info.get("acodec", "opus")
        a_asr = a_info.get("asr", 48000)
        a_abr = a_info.get("abr", 128)
        print(f"🎵 {a_ext} {a_cod} | {a_asr}Hz {a_abr}kbps | {a_size_str}")

    tot_bytes = 0
    if v_cand and v_cand.exists(): tot_bytes += v_cand.stat().st_size
    if a_cand and a_cand.exists(): tot_bytes += a_cand.stat().st_size
    dl_speed = (tot_bytes / (1024 * 1024)) / dl_elapsed if dl_elapsed > 0 else 0
    print(f"⏱️ [Descarga] Completada en {dl_elapsed:.1f}s ({dl_speed:.1f}MiB/s)")

    if v_cand and v_cand.exists():
        asset_update["video_only"] = v_cand.name
    if a_cand and a_cand.exists():
        asset_update["audio_only"] = a_cand.name

    update_assets(folder, **asset_update)
    return media_path, info
    

def separate_vocals(
    video_path: Path,
    output_dir: Path | None = None,
    force_dual_gpu: bool | None = None,
) -> tuple[Path, Path]:
    """
    Separa las voces del audio usando BS-RoFormer.

    Parámetros:
      - force_dual_gpu: True para forzar 2 GPUs, False para 1 GPU, None para auto-detección.
        (El solapamiento Dual-GPU se fija internamente en 2.0s con crossfade para garantizar
        que no exista ningún 'tic' o discontinuidad en el punto de corte).

    Registra en result.json ('assets'):
      - vocals:    pista de voz extraída (vocals.wav)
      - no_vocals: pista instrumental sin voz (no_vocals.wav)

    Returns: (vocals_path, no_vocals_path)
    """
    import os
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

    total_duration_sec = mixture.shape[1] / sr
    gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 0

    # Determinar si se activa Dual-GPU
    if force_dual_gpu is None:
        env_dg = os.environ.get("ROFORMER_DUAL_GPU", "auto").lower()
        if env_dg in ("false", "0", "no"):
            enable_dual = False
        elif env_dg in ("true", "1", "yes"):
            enable_dual = (gpu_count >= 2)
        else:
            enable_dual = (gpu_count >= 2 and total_duration_sec > 20.0)
    else:
        enable_dual = bool(force_dual_gpu and gpu_count >= 2)

    # 3) Separar stems: Dual-GPU o Single-GPU
    if enable_dual:
        model_0 = get_or_load_model("bs_roformer_gpu0", _get_roformer_gpu0, config, model)
        result = _demix_dual_gpu(config, model_0, model, mixture, sr)
    else:
        saved_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            with torch.no_grad():
                result, _ = demix_track(config, model, mixture, device)
        finally:
            sys.stdout = saved_stdout

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
    print(f"⏱️ [Separación BS-RoFormer | {'Dual-GPU' if enable_dual else 'Single-GPU'}] Completada en {sep_elapsed:.1f}s")

    # --- Registro determinista en manifiesto ---
    update_assets(
        output_dir,
        vocals=vocals_path.name if vocals_path.exists() else None,
        no_vocals=no_vocals_path.name if no_vocals_path.exists() else None,
    )

    return vocals_path, no_vocals_path


def yt(url: str, vocals_separation: bool = True, force_new: bool = False) -> tuple[Path, dict]:
    """Descarga video y opcionalmente separa voces. Returns (path, info)."""
    path, info = download_video(url, force_new=force_new)
    if vocals_separation:
        t0_sep = time.perf_counter()
        separate_vocals(path)
        info["_stems_time"] = time.perf_counter() - t0_sep
    return path, info
