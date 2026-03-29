"""
Utilidades de audio: ajuste de duración, clonado de segmentos, merge.
"""
from pathlib import Path
from typing import Optional, Tuple

import torch
import torchaudio

from src.assets import register_segment


def adjust_audio_duration(
    audio: torch.Tensor,
    target_duration_samples: int,
    sample_rate: int,
    min_tempo: float = 0.6,
) -> torch.Tensor:
    """
    Ajusta la duración del audio usando cambio de tempo.
    """
    if audio.shape[-1] == 0 or target_duration_samples <= 0:
        return audio

    tempo = audio.shape[-1] / target_duration_samples
    safe_tempo = max(tempo, min_tempo)

    try:
        effector = torchaudio.io.AudioEffector(f"atempo={safe_tempo}")
        adjusted = effector.apply(audio.T, sample_rate).T
        return adjusted[:, :target_duration_samples]
    except Exception as e:
        print(f"⚠️ Error al ajustar tempo: {e}")
        return audio[:, :target_duration_samples]


def clone_voice_segments(
    path: Path,
    texts: list[dict],
    language: str,
    audio_ref: str | Path,
    tts_fn: callable,
    only_indices: Optional[list[int]] = None,
    slowdown_range: Optional[Tuple[float, float]] = None,
    stretch_target_ratio: float = 1.0,
    **kwargs,
) -> Tuple[list[Path], list[int], int]:
    seqs_src_dir = path.parent / "Seqs_src"
    seqs_trg_dir = path.parent / "Seqs_trg"
    seqs_trg_dir.mkdir(exist_ok=True)

    texts_to_process = texts if only_indices is None else [texts[i - 1] for i in only_indices]
    start_idx = 1 if only_indices is None else only_indices[0]

    times: list[int] = []
    path_es: list[Path] = []

    for idx, text_dict in enumerate(texts_to_process):
        text = text_dict["text"]
        start_time = text_dict["start"]

        seq_num = only_indices[idx] if only_indices else texts.index(text_dict) + 1

        audio_en_path = seqs_src_dir / f"vocals_{seq_num:04d}.wav"
        if not audio_en_path.exists():
            print(f"⚠️ No se encontró: {audio_en_path}")
            continue

        arr_en, rate_en = torchaudio.load(str(audio_en_path))
        dur_en = arr_en.shape[-1] / rate_en

        arr, rate = tts_fn(text, language, audio_ref, **kwargs)
        if arr is None or rate is None:
            continue

        dur_es = arr.shape[-1] / rate
        duration_ratio = dur_es / dur_en if dur_en > 0 else 0
        print(f"{idx:2d}. ", end="")

        if slowdown_range and stretch_target_ratio != 1.0:
            if duration_ratio > 1.0:
                print(f"Fast: {dur_es:5.2f}s → {dur_en:5.2f}s", end=" ")
                target_samples = int(dur_en * rate)
                arr = adjust_audio_duration(arr, target_samples, rate)
            elif slowdown_range[0] < duration_ratio < slowdown_range[1]:
                target_dur_sec = dur_es + (dur_en - dur_es) * stretch_target_ratio
                print(f"Slow: {dur_es:5.2f}s → {target_dur_sec:5.2f}s", end=" ")
                target_samples = int(target_dur_sec * rate)
                arr = adjust_audio_duration(arr, target_samples, rate)
            else:
                print(f"Stay: {dur_es:5.2f}s → {dur_en:5.2f}s", end=" ")

        print(f" {text}")

        audio_es_path = seqs_trg_dir / f"{audio_en_path.stem}.wav"
        torchaudio.save(str(audio_es_path), arr, sample_rate=rate)
        path_es.append(audio_es_path)
        # Registrar ruta exacta del segmento en el manifiesto de activos
        register_segment(path.parent, seq_num, audio_es_path)
        start_samples = int(start_time * rate)
        times.append(start_samples)

    return path_es, times, rate


def merge_cloned_audio(
    original_audio_path: Path,
    cloned_segments: list[Path],
    segment_times: list[int],
    sample_rate: int,
) -> torch.Tensor:
    """Combina segmentos de audio clonados en un solo tensor."""
    arr, org_sr = torchaudio.load(str(original_audio_path))
    fix_es = torchaudio.functional.resample(arr, orig_freq=org_sr, new_freq=sample_rate)
    fix_es[:, :] = 0

    for start_samples, audio_seg_path in zip(segment_times, cloned_segments):
        arr_es, _ = torchaudio.load(str(audio_seg_path))
        end_samples = start_samples + arr_es.shape[1]
        if end_samples <= fix_es.shape[1]:
            fix_es[:, start_samples:end_samples] = arr_es

    return fix_es
