import subprocess
from pathlib import Path
from typing import Optional
import torch
import torchaudio


class RenderService:
    """Servicio de renderizado de video final con FFmpeg."""

    @staticmethod
    def merge_audio_segments(
        original_audio_path: Path,
        cloned_segments: list[Path],
        segment_times: list[int],
        sample_rate: int,
        output_path: Path,
    ) -> Path:
        """Combina segmentos de audio clonados en un solo archivo."""
        arr, org_sr = torchaudio.load(str(original_audio_path))
        fix_es = torchaudio.functional.resample(
            arr, orig_freq=org_sr, new_freq=sample_rate
        )
        fix_es[:, :] = 0

        for start_samples, audio_seg_path in zip(segment_times, cloned_segments):
            if not audio_seg_path or not audio_seg_path.exists():
                continue
            arr_es, _ = torchaudio.load(str(audio_seg_path))
            end_samples = start_samples + arr_es.shape[1]
            if end_samples <= fix_es.shape[1]:
                fix_es[:, start_samples:end_samples] = arr_es

        torchaudio.save(str(output_path), fix_es, sample_rate)
        return output_path

    @staticmethod
    def adjust_audio_duration(
        audio: torch.Tensor,
        target_duration_samples: int,
        sample_rate: int,
        min_tempo: float = 0.6,
    ) -> torch.Tensor:
        """Ajusta la duración del audio usando cambio de tempo."""
        if audio.shape[-1] == 0 or target_duration_samples <= 0:
            return audio

        tempo = audio.shape[-1] / target_duration_samples
        safe_tempo = max(tempo, min_tempo)

        try:
            effector = torchaudio.io.AudioEffector(f"atempo={safe_tempo}")
            adjusted = effector.apply(audio.T, sample_rate).T
            return adjusted[:, :target_duration_samples]
        except Exception:
            return audio[:, :target_duration_samples]

    @classmethod
    async def render_final_video(
        cls,
        project_id: str,
        video_path: Path,
        audio_segments: list[dict],
        project_dir: Path,
        output_name: str,
        ws_manager,
    ) -> Path:
        """
        Renderiza el video final combinando video y audio.

        Args:
            project_id: ID del proyecto
            video_path: Path al video original
            audio_segments: Lista de dicts con {start_timeline, end_timeline, audio_path}
            project_dir: Directorio del proyecto
            output_name: Nombre del archivo de salida
            ws_manager: WebSocket manager para进度

        Returns:
            Path al video renderizado
        """
        await ws_manager.send_progress(
            project_id, 0.8, "Preparando renderizado...", "rendering"
        )

        output_dir = project_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Mezclar todos los segmentos de audio en un solo archivo
        vocals_es_path = project_dir / "vocals_es.wav"
        no_vocals_path = project_dir.with_name("no_vocals.wav")

        # Obtener paths de audio válidos
        audio_paths = []
        audio_times = []

        for seg in audio_segments:
            if seg.get("audio_path"):
                p = Path(seg["audio_path"])
                if p.exists():
                    audio_paths.append(p)
                    # Usar el tiempo del timeline para posicionar el audio
                    start_sec = int(seg["start_timeline"] * 24000)  # Assuming 24kHz
                    audio_times.append(start_sec)

        if audio_paths:
            _, sr = torchaudio.load(str(audio_paths[0]))
            cls.merge_audio_segments(
                video_path.with_name("vocals.wav"),
                audio_paths,
                audio_times,
                sr,
                vocals_es_path,
            )
        else:
            # Si no hay segmentos, usar el audio original
            vocals_es_path = video_path.with_name("vocals.wav")

        # Comando FFmpeg para renderizar
        final_output_path = output_dir / f"{output_name}.mp4"

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
            "copy",
            str(final_output_path),
        ]

        await ws_manager.send_log(project_id, "Ejecutando FFmpeg...")

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            await ws_manager.send_error(project_id, f"Error en FFmpeg: {result.stderr}")
            raise RuntimeError(f"Error en FFmpeg: {result.stderr}")

        await ws_manager.send_progress(
            project_id, 1.0, "Renderizado completado", "complete"
        )
        await ws_manager.send_complete(project_id, str(final_output_path))

        return final_output_path

    @classmethod
    async def render_timeline_edits(
        cls,
        project_id: str,
        video_path: Path,
        video_clips: list[dict],
        audio_segments: list[dict],
        project_dir: Path,
        output_name: str,
        ws_manager,
    ) -> Path:
        """
        Renderiza el video basándose en las ediciones del timeline.
        Soporta múltiples clips de video y audio recortados.
        """
        await ws_manager.send_progress(
            project_id, 0.8, "Renderizando timeline...", "rendering"
        )

        output_dir = project_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        final_output_path = output_dir / f"{output_name}.mp4"

        # Filtrar clips válidos
        valid_video_clips = [
            c
            for c in video_clips
            if c.get("start_timeline", 0) < c.get("end_timeline", 0)
        ]
        valid_audio_segments = [s for s in audio_segments if s.get("audio_path")]

        if not valid_video_clips:
            raise ValueError("No hay clips de video válidos para renderizar")

        # Construir comando FFmpeg dinámico
        cmd = ["ffmpeg", "-y", "-v", "error"]

        # Inputs de video
        for i, clip in enumerate(valid_video_clips):
            cmd.extend(["-ss", str(clip["start_original"])])
            cmd.extend(["-t", str(clip["end_original"] - clip["start_original"])])
            cmd.extend(["-i", str(video_path)])

        # Input de audio original (para partes sin doblaje)
        vocals_original = video_path.with_name("vocals.wav")
        if vocals_original.exists():
            cmd.extend(["-i", str(vocals_original)])

        # Inputs de audio doblado
        for seg in valid_audio_segments:
            if Path(seg["audio_path"]).exists():
                cmd.extend(["-i", str(seg["audio_path"])])

        # Construir filter_complex
        # 1. Mezclar audios
        # 2. Concatenar videos
        # 3. Combinar video + audio final

        num_video_inputs = len(valid_video_clips)
        num_audio_inputs = len(valid_audio_segments)

        # Simplificado: usar el primer video y mezclar audios
        filter_parts = []

        # Ajustar volúmenes
        if vocals_original.exists():
            filter_parts.append("[0]volume=0.00[a_vocals]")
        else:
            filter_parts.append("[0]anull[a_vocals]")

        # Mezclar audios doblados
        audio_mix_inputs = "[a_vocals]"
        for i in range(num_audio_inputs):
            audio_idx = num_video_inputs + 1 + i
            filter_parts.append(f"[{audio_idx}]volume=3.5[a_{i}]")
            audio_mix_inputs += f"[a_{i}]"

        if num_audio_inputs > 0:
            filter_parts.append(
                f"{audio_mix_inputs}amix=inputs={num_audio_inputs + 1}[a_mixed]"
            )
        else:
            filter_parts.append(f"{audio_mix_inputs}anull[a_mixed]")

        # Filtrado final
        filter_complex = (
            ";".join(filter_parts) + f";[0:v][a_mixed]concat=n=1:v=1:a=0[outv]"
        )

        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-c:v",
                "copy",
                str(final_output_path),
            ]
        )

        await ws_manager.send_log(project_id, f"FFmpeg: {' '.join(cmd[:10])}...")

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            await ws_manager.send_error(project_id, f"FFmpeg error: {result.stderr}")
            # Fallback: video original con audio mezclado
            return await cls.render_final_video(
                project_id,
                video_path,
                audio_segments,
                project_dir,
                output_name,
                ws_manager,
            )

        await ws_manager.send_progress(
            project_id, 1.0, "Renderizado completado", "complete"
        )
        await ws_manager.send_complete(project_id, str(final_output_path))

        return final_output_path
