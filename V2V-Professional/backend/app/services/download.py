import os
import re
import subprocess
import io
import contextlib
from pathlib import Path
from typing import Optional
import torch
import torchaudio


class DownloadService:
    """Servicio de descarga de videos de YouTube."""

    @staticmethod
    def download_video(url: str, output_dir: Path) -> tuple[Path, dict]:
        """Descarga un video de YouTube."""
        from yt_dlp import YoutubeDL

        video = "bv[vcodec^=avc1]"
        audio = "ba"

        opts = {
            "outtmpl": str(output_dir / "%(title)s" / "%(title)s.%(ext)s"),
            "format": f"{video} + {audio}",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
        }

        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            media = ydl.prepare_filename(info)
            ydl.download([url])
            return Path(media), info

    @staticmethod
    def separate_vocals(video_path: Path) -> tuple[Path, Path]:
        """Separa las voces del audio usando BS-RoFormer."""
        from bs_roformer.utils import demix_track
        import yaml
        from ml_collections import ConfigDict
        from bs_roformer.inference import SafeLoaderWithTuple

        output_dir = video_path.parent
        vocals_path = output_dir / "vocals.wav"
        no_vocals_path = output_dir / "no_vocals.wav"

        if vocals_path.exists() and no_vocals_path.exists():
            return vocals_path, no_vocals_path

        # Cargar modelo (simplificado - en producción usar caché)
        model_dir = Path(os.getenv("ROFORMER_DIR", "./models/bs-roformer"))
        model_path = model_dir / "bs_roformer_revive3e.ckpt"
        config_path = model_dir / "config.yaml"

        with open(config_path) as f:
            config = ConfigDict(yaml.load(f, Loader=SafeLoaderWithTuple))

        from src.models import get_or_load_model

        model = get_or_load_model(
            "bs_roformer",
            lambda: (
                config,
                torch.load(model_path, map_location="cpu"),
                torch.device("cuda" if torch.cuda.is_available() else "cpu"),
            ),
        )

        config, state_dict, device = model
        model = get_model_from_config("bs_roformer", config)
        model.load_state_dict(state_dict)
        model = model.to(device)
        model.eval()

        # Cargar audio del video
        mix, sr = torchaudio.load(str(video_path))
        if mix.shape[0] == 1:
            mix = torch.cat([mix, mix], dim=0)

        # Separar
        with torch.no_grad():
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result, _ = demix_track(config, model, mix.to(torch.float32), device)

        # Guardar stems
        for instrument, audio in result.items():
            output = torch.from_numpy(audio)
            if mix.shape[0] == 1:
                output = output[0:1, :]
            output_path = output_dir / f"{instrument}.wav"
            torchaudio.save(str(output_path), output, sr)

        # Calcular no_vocals
        if "vocals" in result:
            mix_cpu = mix.cpu()
            vocals_np = result["vocals"]
            vocals_tensor = torch.from_numpy(vocals_np).to(mix_cpu.dtype)
            instrumental = mix_cpu - vocals_tensor
            if mix.shape[0] == 1:
                instrumental = instrumental[0:1, :]
            torchaudio.save(str(no_vocals_path), instrumental, sr)

        return vocals_path, no_vocals_path

    @staticmethod
    async def process_video(url: str, project_id: str, output_dir: Path, ws_manager):
        """Procesa un video: descarga + separación de voces."""
        from app.core.database import Project, ProjectStatus
        from app.core.config import settings

        await ws_manager.send_progress(
            project_id, 0.1, "Descargando video...", "downloading"
        )
        await ws_manager.send_log(project_id, f"Iniciando descarga: {url}")

        try:
            video_path, info = DownloadService.download_video(url, output_dir)
            await ws_manager.send_progress(
                project_id, 0.3, "Separando audio...", "processing"
            )
            await ws_manager.send_log(project_id, "Audio separado correctamente")

            vocals_path, no_vocals_path = DownloadService.separate_vocals(video_path)

            await ws_manager.send_progress(
                project_id, 0.5, "Descarga completada", "processing"
            )

            return {
                "video_path": str(video_path),
                "vocals_path": str(vocals_path),
                "no_vocals_path": str(no_vocals_path),
                "title": info.get("title", "output"),
            }
        except Exception as e:
            await ws_manager.send_error(project_id, f"Error en descarga: {str(e)}")
            raise


def get_model_from_config(model_name: str, config):
    """Helper para cargar modelo desde config."""
    # Simplified - en producción usar la implementación completa
    import torch
    from bs_roformer.utils import get_model_from_config as original_get_model

    return original_get_model(model_name, config)
