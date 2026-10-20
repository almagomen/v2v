"""
Utilidades de audio: ajuste de duración, clonado de segmentos, merge.
"""

from pathlib import Path
from typing import Optional, Tuple, Any

try:
    import torch
    import torchaudio
except ImportError:
    torch = None
    torchaudio = None



def _build_atempo_filter(tempo: float) -> str:
    """Construye cadena de filtros atempo encadenados para valores fuera de [0.5, 2.0]."""
    factors = []
    curr = float(tempo)
    while curr > 2.0:
        factors.append("atempo=2.0")
        curr /= 2.0
    while curr < 0.5:
        factors.append("atempo=0.5")
        curr /= 0.5
    factors.append(f"atempo={curr:.4f}")
    return ",".join(factors)


import subprocess
import tempfile
import os


def _adjust_audio_duration_ffmpeg(
    audio: Any,
    filter_str: str,
    sample_rate: int,
    target_duration_samples: int,
) -> Any:
    """Ajusta el tempo del tensor de audio usando FFmpeg de forma nativa y robusta."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_in, \
         tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_out:
        in_path = f_in.name
        out_path = f_out.name

    try:
        torchaudio.save(in_path, audio, sample_rate=sample_rate)
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-i", in_path,
            "-filter:a", filter_str,
            out_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 44:
            adjusted, _ = torchaudio.load(out_path)
            if adjusted.shape[-1] > target_duration_samples:
                return adjusted[:, :target_duration_samples]
            return adjusted
        else:
            raise RuntimeError(res.stderr.strip() or "FFmpeg falló al procesar el audio")
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


def adjust_audio_duration(
    audio: Any,
    target_duration_samples: int,
    sample_rate: int,
    min_tempo: float = 0.5,
    max_tempo: float = 4.0,
) -> Any:
    """
    Ajusta la duración del audio usando cambio de tempo (time-stretching sin alterar tono).
    """
    if audio is None or audio.shape[-1] == 0 or target_duration_samples <= 0:
        return audio

    tempo = audio.shape[-1] / target_duration_samples
    safe_tempo = max(min(tempo, max_tempo), min_tempo)

    # Si la diferencia es imperceptible (<1%), solo recortar si excede
    if abs(safe_tempo - 1.0) < 0.01:
        if audio.shape[-1] > target_duration_samples:
            return audio[:, :target_duration_samples]
        return audio

    filter_str = _build_atempo_filter(safe_tempo)

    # 1. Intentar torchaudio.io.AudioEffector si está disponible en la versión instalada
    try:
        import torchaudio.io
        if hasattr(torchaudio.io, "AudioEffector"):
            effector = torchaudio.io.AudioEffector(filter_str)
            adjusted = effector.apply(audio.T, sample_rate).T
            if adjusted.shape[-1] > target_duration_samples:
                return adjusted[:, :target_duration_samples]
            return adjusted
    except Exception:
        pass

    # 2. Método estándar y confiable con FFmpeg nativo
    try:
        return _adjust_audio_duration_ffmpeg(audio, filter_str, sample_rate, target_duration_samples)
    except Exception as e:
        print(f"⚠️ Error al ajustar tempo ({safe_tempo:.2f}x): {e}")
        if audio.shape[-1] > target_duration_samples:
            return audio[:, :target_duration_samples]
        return audio


def clone_voice_segments(
    path: Path,
    texts: list[dict],
    language: str,
    audio_ref: str | Path,
    tts_fn: callable,
    only_indices: Optional[list[int]] = None,
    slowdown_range: Optional[Tuple[float, float]] = None,
    stretch_target_ratio: float = 1.0,
    speed: float = 1.0,
    target_duration: Optional[float] = None,
    register: bool = True,
    speaker_map: Optional[dict[str, str]] = None,
    **kwargs,
) -> Tuple[list[Path], list[int], int]:
    seqs_src_dir = path.parent / "Seqs_src"
    seqs_trg_dir = path.parent / "Seqs_trg"
    seqs_trg_dir.mkdir(exist_ok=True)

    texts_to_process = (
        texts if only_indices is None else [texts[i - 1] for i in only_indices]
    )

    times: list[int] = []
    path_es: list[Path] = []

    # Obtener duración total del video de forma exhaustiva y precisa
    video_total_duration: Optional[float] = None
    for cand_name in ["no_vocals.wav", "no_vocals.m4a", "vocals.wav"]:
        cand_p = path.with_name(cand_name)
        if cand_p.exists():
            try:
                v_info = torchaudio.info(str(cand_p))
                if v_info.sample_rate > 0:
                    video_total_duration = v_info.num_frames / v_info.sample_rate
                    break
            except Exception:
                pass

    if video_total_duration is None and path.exists():
        try:
            v_info = torchaudio.info(str(path))
            if v_info.sample_rate > 0:
                video_total_duration = v_info.num_frames / v_info.sample_rate
        except Exception:
            pass

    from concurrent.futures import ThreadPoolExecutor

    # Preparamos las tareas de TTS para ejecución concurrente
    tts_tasks = []
    for idx, text_dict in enumerate(texts_to_process):
        text = text_dict["text"]
        speaker = text_dict.get("speaker", "SPEAKER_00")
        orig_spk = text_dict.get("original_speaker") or speaker
        target_spk = (speaker_map.get(orig_spk) if speaker_map else None) or speaker

        from api.service import SPEAKER_OPTIONS
        seg_audio_ref = SPEAKER_OPTIONS.get(target_spk, target_spk) if target_spk else audio_ref
        if not seg_audio_ref:
            seg_audio_ref = audio_ref

        seq_num = only_indices[idx] if only_indices else idx + 1
        tts_tasks.append((idx, text, seg_audio_ref, seq_num))

    # Si hay múltiples segmentos, paralelizamos las solicitudes HTTP (hasta 5 hilos)
    tts_results: dict[int, tuple] = {}
    if len(tts_tasks) > 1:
        max_workers = min(5, len(tts_tasks))
        def _fetch_tts(item):
            i, txt, voice_ref, s_num = item
            try:
                res = tts_fn(txt, language, voice_ref, **kwargs)
                return i, res
            except Exception as ex:
                print(f"\n⚠️ Error en síntesis TTS #{s_num}: {ex}")
                return i, (None, None)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i, res in executor.map(_fetch_tts, tts_tasks):
                tts_results[i] = res

    for idx, text_dict in enumerate(texts_to_process):
        text = text_dict["text"]
        start_time = text_dict["start"]
        speaker = text_dict.get("speaker", "SPEAKER_00")
        orig_spk = text_dict.get("original_speaker") or speaker
        target_spk = (speaker_map.get(orig_spk) if speaker_map else None) or speaker

        # Resolver voz específica del segmento si difiere de audio_ref
        from api.service import SPEAKER_OPTIONS
        seg_audio_ref = SPEAKER_OPTIONS.get(target_spk, target_spk) if target_spk else audio_ref
        if not seg_audio_ref:
            seg_audio_ref = audio_ref

        safe_speaker = str(target_spk).replace(" ", "_").replace("/", "_").replace("\\", "_")

        seq_num = only_indices[idx] if only_indices else idx + 1

        audio_en_path = seqs_src_dir / f"vocals_{seq_num:03d}.wav"
        if not audio_en_path.exists():
            print(f"⚠️ No se encontró: {audio_en_path}")
            continue

        arr_en, rate_en = torchaudio.load(str(audio_en_path))
        dur_en = arr_en.shape[-1] / rate_en

        if idx in tts_results:
            arr, rate = tts_results[idx]
        else:
            arr, rate = tts_fn(text, language, seg_audio_ref, **kwargs)

        if arr is None or rate is None:
            continue

        # --- GUARDAR COPIA RAW INTACTA PARA "APPLY SPEED" FUTURO ---
        raw_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{seq_num:03d}_raw.wav"
        torchaudio.save(str(raw_es_path), arr, sample_rate=rate)
        # --------------------------------------------------------

        dur_es = arr.shape[-1] / rate
        duration_ratio = dur_es / dur_en if dur_en > 0 else 0
        print(f"{idx+1:2d}. ", end="")

        # ─── BÚSQUEDA DEL PRÓXIMO SEGMENTO DEL MISMO HABLANTE ───
        # Buscar en la lista global 'texts' el siguiente inicio para este speaker
        next_same_speaker_starts = [
            t["start"]
            for t in texts
            if t.get("speaker", "SPEAKER_00") == speaker and t["start"] > start_time + 0.01
        ]
        next_speaker_start = min(next_same_speaker_starts) if next_same_speaker_starts else None

        # Determinar el límite máximo disponible sin colisionar
        if next_speaker_start is not None:
            available_space = next_speaker_start - start_time
            original_gap = available_space - dur_en
            # Gap dinámico de respiro: entre 0.05s y 0.15s según el espacio libre
            safety_gap = min(0.15, max(0.05, original_gap * 0.1)) if original_gap > 0.1 else min(0.05, max(0.0, original_gap))
            max_allowed_dur = max(dur_en, available_space - safety_gap)
        elif video_total_duration is not None:
            # Es el último segmento: tope absoluto para no superar el final del video
            available_space = max(0.1, video_total_duration - start_time - 0.05)
            max_allowed_dur = available_space
        else:
            max_allowed_dur = None

        if slowdown_range:
            if duration_ratio > 1.0:
                if max_allowed_dur is not None and dur_es > max_allowed_dur:
                    # Choca con el siguiente segmento: acelerar a max_allowed_dur
                    ratio_needed = dur_es / max_allowed_dur
                    print(
                        f"⚠️ {ratio_needed:.2f}x: {max_allowed_dur:5.2f}s → {dur_en:5.2f}s",
                        end=" ",
                    )
                    target_samples = int(max_allowed_dur * rate)
                    arr = adjust_audio_duration(arr, target_samples, rate)
                else:
                    # Cabe en la pausa natural sin chocar (1.00x)
                    print(
                        f"✨ 1.00x: {dur_es:5.2f}s ← {dur_en:5.2f}s",
                        end=" ",
                    )
            elif slowdown_range[0] < duration_ratio < slowdown_range[1]:
                # Estiramiento para cubrir el espacio original (isocronía sin huecos de silencio)
                desired_dur = dur_es + (dur_en - dur_es) * stretch_target_ratio
                min_slow_speed = 0.85  # Piso de seguridad de doblaje profesional: evita arrastre o voz ebria
                max_slow_dur = dur_es / min_slow_speed
                target_dur_sec = min(desired_dur, max_slow_dur, dur_en)
                effective_slow_speed = dur_es / target_dur_sec if target_dur_sec > 0 else 1.0

                print(
                    f"🔉 {effective_slow_speed:.2f}x: {target_dur_sec:5.2f}s ← {dur_en:5.2f}s",
                    end=" ",
                )
                target_samples = int(target_dur_sec * rate)
                arr = adjust_audio_duration(arr, target_samples, rate)
            else:
                print(
                    f"✨ 1.00x: {dur_es:5.2f}s ← {dur_en:5.2f}s",
                    end=" ",
                )

        # Aplicar target_duration (modo 's') si está presente
        if target_duration is not None and target_duration > 0:
            raw_speed = dur_es / target_duration if target_duration > 0 else 1.0
            if raw_speed < 0.5:
                effective_speed = 0.5
                print(
                    f"Target duration: {target_duration:.2f}s -> speed={raw_speed:.2f}x CLAMPED a 0.5x",
                    end=" ",
                )
            elif raw_speed > 2.0:
                effective_speed = 2.0
                print(
                    f"Target duration: {target_duration:.2f}s -> speed={raw_speed:.2f}x CLAMPED a 2.0x",
                    end=" ",
                )
            else:
                effective_speed = raw_speed
                print(
                    f"Target duration: {target_duration:.2f}s -> speed={effective_speed:.2f}x",
                    end=" ",
                )
            target_samples = int(target_duration * rate)
            arr = adjust_audio_duration(arr, target_samples, rate)
        # Aplicar speed manual del usuario si es distinto de 1.0 y no se aplicó target_duration
        elif speed != 1.0:
            target_samples = int(arr.shape[-1] / speed)
            print(f"Speed manual: {speed}x -> {target_samples} samples", end=" ")
            arr = adjust_audio_duration(arr, target_samples, rate)

        # Tope final estricto: ningún segmento puede exceder la duración total del video
        if video_total_duration is not None:
            max_end = video_total_duration - 0.05
            curr_dur = arr.shape[-1] / rate
            if start_time + curr_dur > max_end:
                allowed_sec = max(0.1, max_end - start_time)
                target_samples = int(allowed_sec * rate)
                arr = adjust_audio_duration(arr, target_samples, rate)

        # Actualizar metadatos de duración y fin real del segmento
        final_dur = arr.shape[-1] / rate
        text_dict["end"] = round(start_time + final_dur, 3)
        text_dict["duration"] = round(final_dur, 3)

        print(f" {text}")

        # Generar nombre con formato consistente: tts_{speaker}_{NNNN}.wav
        # Esto permite al frontend identificar el segmento y su speaker
        audio_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{seq_num:03d}.wav"
        torchaudio.save(str(audio_es_path), arr, sample_rate=rate)
        path_es.append(audio_es_path)
        start_samples = int(start_time * rate)
        times.append(start_samples)

    return path_es, times, rate


def merge_cloned_audio(
    original_audio_path: Path,
    cloned_segments: list[Path],
    segment_times: list[int],
    sample_rate: int,
) -> Any:
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
