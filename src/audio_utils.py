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
import re
import unicodedata


def _pad_visible_tag(tag: str, target_w: int = 20) -> str:
    """Calcula el ancho visible en terminal monoespaciada para alinear columnas tabulares."""
    w = 0
    for ch in tag:
        if ch == '\ufe0f':
            continue
        if ch in ('🔉', '✨', '⚡', '🎯', '🎛', '🔄', '🌐', '✂'):
            w += 2
        elif unicodedata.east_asian_width(ch) in ('F', 'W'):
            w += 2
        elif unicodedata.category(ch) == 'Mn':
            pass
        else:
            w += 1
    if w < target_w:
        return tag + " " * (target_w - w)
    return tag


def _extract_emotion_prefix(text: str) -> tuple[str, str]:
    """Extrae las etiquetas de emoción iniciales [tag] y el contenido limpio restante."""
    if not text:
        return "", ""
    match = re.match(r"^((?:\[[^\]]+\]\s*)+)(.*)$", text.strip())
    if match:
        tags = match.group(1).strip()
        rest = match.group(2).strip()
        return tags, rest
    return "", text.strip()


def _format_aligned_segment_texts(
    orig_text: str,
    final_text: str,
    short_text: Optional[str] = None,
    source_lang: str = "pt",
    indent: str = "      ",
) -> list[str]:
    """
    Formatea las líneas de texto del segmento con alineación de corchetes de emoción
    y adaptación dinámica de la etiqueta de idioma original ([ pt ]).
    """
    tag_final, cont_final = _extract_emotion_prefix(final_text)
    tag_short, cont_short = _extract_emotion_prefix(short_text) if short_text else ("", "")

    has_emotion = bool(tag_final or tag_short)

    lines = []
    clean_curr = re.sub(r"\[.*?\]", "", final_text).strip()
    clean_orig = re.sub(r"\[.*?\]", "", orig_text).strip()
    is_translation = bool(clean_orig and clean_orig.lower() != clean_curr.lower())

    if not is_translation:
        if short_text:
            lines.append(f"{indent}{short_text}")
        lines.append(f"{indent}{final_text}")
        return lines

    # Si la frase traducida no tiene expresión inicial, no colocar etiqueta [idioma]
    if not has_emotion:
        lines.append(f"{indent}{orig_text}")
        if short_text:
            lines.append(f"{indent}{short_text}")
        lines.append(f"{indent}{final_text}")
        return lines

    # Adaptar etiqueta de idioma original con espacios interiores (ej. [ pt ])
    sl = source_lang.strip().lower() if source_lang else "pt"
    tag_orig = f"[ {sl} ]" if len(sl) == 2 else f"[{sl}]"

    len_orig = len(tag_orig)
    len_short = len(tag_short) if (short_text and tag_short) else 0
    len_final = len(tag_final) if tag_final else 0

    max_w = max(len_orig, len_final, len_short)

    # Alinear a la derecha las etiquetas para que el corchete ']' concuerde en la misma columna
    pad_orig = " " * (max_w - len_orig)
    lines.append(f"{indent}{pad_orig}{tag_orig} {orig_text}")

    if short_text:
        if tag_short:
            pad_short = " " * (max_w - len_short)
            lines.append(f"{indent}{pad_short}{tag_short} {cont_short}")
        else:
            pad_short = " " * (max_w + 1)
            lines.append(f"{indent}{pad_short}{cont_short}")

    if tag_final:
        pad_final = " " * (max_w - len_final)
        lines.append(f"{indent}{pad_final}{tag_final} {cont_final}")
    else:
        pad_final = " " * (max_w + 1)
        lines.append(f"{indent}{pad_final}{cont_final}")

    return lines


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

    # Si la diferencia es imperceptible (<=4%), no alterar con atempo para no degradar el timbre:
    # aplicar micro-trim suave con fade-out o micro-pad de silencio
    if abs(safe_tempo - 1.0) <= 0.04:
        if audio.shape[-1] > target_duration_samples:
            trimmed = audio[:, :target_duration_samples].clone()
            fade_len = min(128, target_duration_samples)
            if torch is not None and fade_len > 0:
                fade = torch.linspace(1.0, 0.0, fade_len, device=trimmed.device)
                trimmed[:, -fade_len:] *= fade
            return trimmed
        elif audio.shape[-1] < target_duration_samples:
            pad_len = target_duration_samples - audio.shape[-1]
            if torch is not None:
                return torch.nn.functional.pad(audio, (0, pad_len))
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


def distribute_silence_padding(arr: Any, target_samples: int, rate: int) -> Any:
    """
    Distribuye el padding de silencio necesario entre los valles de silencio internos (respiros/[break])
    y el final del audio, evitando dejar un hueco muerto gigante al final del clip.
    Soporta tensores de PyTorch y arrays de NumPy.
    """
    needed_pad = target_samples - arr.shape[-1]
    if needed_pad <= 0:
        return arr

    is_torch = hasattr(arr, "device") and hasattr(arr, "cpu")
    arr_np = arr.detach().cpu().numpy() if is_torch else arr

    # Si el padding necesario es muy pequeño (<= 0.15s), agregarlo directamente al final
    if needed_pad < int(0.15 * rate):
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    window_size = int(0.04 * rate)
    hop_size = int(0.02 * rate)
    total_samples = arr_np.shape[-1]

    if total_samples < window_size:
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    mono = np.mean(arr_np, axis=0) if arr_np.shape[0] > 1 else arr_np[0]
    num_frames = (total_samples - window_size) // hop_size + 1
    if num_frames <= 0:
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    frame_rms = np.zeros(num_frames, dtype=np.float32)
    for f in range(num_frames):
        start = f * hop_size
        chunk = mono[start:start + window_size]
        frame_rms[f] = np.sqrt(np.mean(chunk ** 2))

    max_rms = float(np.max(frame_rms))
    if max_rms < 1e-4:
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    silence_threshold = max(0.005, max_rms * 0.08)
    is_silent = frame_rms < silence_threshold

    min_silence_frames = max(3, int(0.12 / 0.02))
    valleys = []
    start_f = None
    for f_idx, silent in enumerate(is_silent):
        if silent:
            if start_f is None:
                start_f = f_idx
        else:
            if start_f is not None:
                dur_frames = f_idx - start_f
                if dur_frames >= min_silence_frames:
                    mid_frame = start_f + dur_frames // 2
                    valleys.append(mid_frame * hop_size)
                start_f = None

    min_edge = int(0.35 * rate)
    valleys = [v for v in valleys if v > min_edge and v < (total_samples - min_edge)]

    if not valleys:
        pad = np.zeros((arr_np.shape[0], needed_pad), dtype=arr_np.dtype)
        res_np = np.concatenate([arr_np, pad], axis=-1)
        return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np

    num_points = len(valleys) + 1
    max_per_valley = int(0.80 * rate)
    valley_share = min(max_per_valley, needed_pad // num_points)
    allocated_to_valleys = valley_share * len(valleys)
    end_share = needed_pad - allocated_to_valleys

    parts = []
    prev_idx = 0
    silence_chunk = np.zeros((arr_np.shape[0], valley_share), dtype=arr_np.dtype)
    for v_idx in valleys:
        parts.append(arr_np[:, prev_idx:v_idx])
        parts.append(silence_chunk)
        prev_idx = v_idx

    parts.append(arr_np[:, prev_idx:])
    if end_share > 0:
        parts.append(np.zeros((arr_np.shape[0], end_share), dtype=arr_np.dtype))

    res_np = np.concatenate(parts, axis=-1)
    if res_np.shape[-1] < target_samples:
        extra = np.zeros((arr_np.shape[0], target_samples - res_np.shape[-1]), dtype=arr_np.dtype)
        res_np = np.concatenate([res_np, extra], axis=-1)
    elif res_np.shape[-1] > target_samples:
        res_np = res_np[:, :target_samples]

    return torch.from_numpy(res_np).to(arr.device) if is_torch else res_np


def get_audio_file_duration(file_path: Path | str, fallback: Optional[float] = None) -> Optional[float]:
    """
    Obtiene la duración en segundos de un archivo de audio de forma robusta y rápida.
    Prueba sucesivamente: wave (estándar, 0 dependencias), soundfile, torchaudio.info y torchaudio.load.
    """
    p_str = str(file_path)
    # 1. wave (módulo estándar de Python, ultrarrápido para archivos WAV)
    try:
        import wave
        with wave.open(p_str, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0 and frames > 0:
                return frames / float(rate)
    except Exception:
        pass

    # 2. soundfile (muy confiable en entornos Linux/Kaggle)
    try:
        import soundfile as sf
        info = sf.info(p_str)
        if info.duration > 0:
            return float(info.duration)
    except Exception:
        pass

    # 3. torchaudio.info (si está disponible y soportado en el build de PyTorch)
    try:
        if torchaudio is not None and hasattr(torchaudio, "info"):
            v_info = torchaudio.info(p_str)
            if getattr(v_info, "sample_rate", 0) > 0:
                return v_info.num_frames / float(v_info.sample_rate)
    except Exception:
        pass

    # 4. torchaudio.load (fallback leyendo cabecera/datos)
    try:
        if torchaudio is not None:
            arr, sr = torchaudio.load(p_str)
            if sr > 0:
                return arr.shape[-1] / float(sr)
    except Exception:
        pass

    return fallback


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
    source_lang: Optional[str] = None,
    **kwargs,
) -> Tuple[list[Path], list[int], int]:
    seqs_src_dir = path.parent / "Seqs_src"
    seqs_trg_dir = path.parent / "Seqs_trg"
    seqs_trg_dir.mkdir(exist_ok=True)

    texts_to_process = (
        texts if only_indices is None else [texts[i - 1] for i in only_indices]
    )

    # Determinar idioma fuente (origen)
    src_lang = source_lang or kwargs.get("source_lang")
    if not src_lang and texts_to_process:
        src_lang = texts_to_process[0].get("source_lang") or texts_to_process[0].get("src_lang")
    if not src_lang:
        try:
            from src.result_store import load_result
            r_data = load_result(path.parent)
            if r_data:
                src_lang = r_data.get("source_lang")
        except Exception:
            pass
    if not src_lang:
        src_lang = "pt"

    times: list[int] = []
    path_es: list[Path] = []

    # Obtener duración total del video de forma exhaustiva y precisa
    video_total_duration: Optional[float] = None
    for cand_name in ["no_vocals.wav", "no_vocals.m4a", "vocals.wav"]:
        cand_p = path.with_name(cand_name)
        if cand_p.exists():
            d = get_audio_file_duration(cand_p)
            if d is not None and d > 0:
                video_total_duration = d
                break

    if video_total_duration is None and path.exists():
        video_total_duration = get_audio_file_duration(path)

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

        # --- AUTO-HEALER SELECTIVO: Identificar anomalías severas de sub-duración (< 0.65x) ---
        underflow_items = []
        for idx, text_dict in enumerate(texts_to_process):
            seq_num = only_indices[idx] if only_indices else idx + 1
            audio_en_path = seqs_src_dir / f"vocals_{seq_num:03d}.wav"
            if not audio_en_path.exists() or idx not in tts_results:
                continue
            arr_cand, rate_cand = tts_results[idx]
            if arr_cand is None or rate_cand is None:
                continue
            meta_fallback = float(text_dict.get("duration") or max(0.1, float(text_dict.get("end", 0)) - float(text_dict.get("start", 0))))
            dur_en_cand = get_audio_file_duration(audio_en_path, fallback=meta_fallback) or meta_fallback
            dur_es_cand = arr_cand.shape[-1] / rate_cand
            clean_txt = re.sub(r"\[.*?\]", "", text_dict.get("text", "")).strip()
            # Si el clip dura >= 3.5s y la voz quedó en menos del 65% de la duración en un texto sustancial:
            if dur_en_cand >= 3.5 and (dur_es_cand / dur_en_cand) < 0.65 and len(clean_txt) >= 20:
                underflow_items.append({
                    "idx": idx,
                    "seq_num": seq_num,
                    "text_dict": text_dict,
                    "dur_en": dur_en_cand,
                    "dur_es": dur_es_cand,
                })

        healed_records: dict[int, dict] = {}
        if underflow_items:
            try:
                from src.translation import auto_heal_short_segments
                healed_map = auto_heal_short_segments(underflow_items, target_lang=language)
                for item in underflow_items:
                    idx = item["idx"]
                    if idx in healed_map:
                        new_txt = healed_map[idx]
                        seq_num = item["seq_num"]
                        seg_audio_ref = tts_tasks[idx][2]
                        new_arr, new_rate = tts_fn(new_txt, language, seg_audio_ref, **kwargs)
                        if new_arr is not None and new_rate is not None:
                            new_dur = new_arr.shape[-1] / new_rate
                            old_dur = item["dur_es"]
                            dur_en_c = item["dur_en"]
                            if abs(dur_en_c - new_dur) < abs(dur_en_c - old_dur):
                                healed_records[idx] = {
                                    "old_dur": old_dur,
                                    "new_dur": new_dur,
                                    "target_dur": dur_en_c,
                                    "old_text": item["text_dict"].get("text", ""),
                                }
                                tts_results[idx] = (new_arr, new_rate)
                                texts_to_process[idx]["text"] = new_txt
            except Exception as e_heal:
                print(f"\n⚠️ [Auto-Heal] Excepción en re-inferencia selectiva: {e_heal}", flush=True)

    if only_indices is None or len(only_indices) > 1:
        header = f"{' #':<5}{'MODO':<20}{'DURACIONES [ORIG | FISH]'}"
        print("-" * 52)
        print(header)
        print("-" * 52)

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
        raw_dur_es = dur_es

        # ─── BÚSQUEDA DEL PRÓXIMO SEGMENTO CRONOLÓGICO Y LÍMITE DE PAUSA ───
        # Buscar el inicio del siguiente segmento cronológico (de cualquier interlocutor)
        next_starts = [
            float(t["start"])
            for t in texts
            if float(t["start"]) > start_time + 0.01
        ]
        next_seg_start = min(next_starts) if next_starts else None

        # Determinar el límite máximo disponible evitando invadir silencios largos de escena
        if next_seg_start is not None:
            hard_limit = max(0.2, next_seg_start - start_time - 0.08)
            natural_limit = dur_en + max(0.35, min(0.85, dur_en * 0.20))
            max_allowed_dur = min(hard_limit, max(dur_en, natural_limit))
        elif video_total_duration is not None:
            hard_limit = max(0.2, video_total_duration - start_time - 0.05)
            natural_limit = dur_en + max(0.35, min(0.85, dur_en * 0.20))
            max_allowed_dur = min(hard_limit, max(dur_en, natural_limit))
        else:
            max_allowed_dur = dur_en * 1.15

        mode_tag = "✨ 1.00x (natural)"

        if slowdown_range:
            if max_allowed_dur is not None and dur_es > max_allowed_dur:
                ratio_needed = dur_es / max_allowed_dur
                if ratio_needed <= 1.03:
                    mode_tag = "✨ 1.00x (natural)"
                else:
                    # Aceleración suave con FFmpeg hasta un tope seguro de 1.25x para sincronía exacta
                    safe_ratio = min(ratio_needed, 1.25)
                    mode_tag = f"⚡ {safe_ratio:.2f}x (sync)"
                    target_samples = int(arr.shape[-1] / safe_ratio)
                    arr = adjust_audio_duration(arr, target_samples, rate)
            elif dur_es < dur_en:
                # El audio traducido es más corto que el original:
                # Expandir con atempo hasta cubrir dur_en y eliminar el silencio muerto entre segmentos
                ratio_slow = dur_es / dur_en
                if ratio_slow >= 0.96:
                    pad_pct = int(round((1.0 - ratio_slow) * 100))
                    mode_tag = f"✨ 1.00x (+pad {pad_pct}%)" if pad_pct > 0 else "✨ 1.00x (natural)"
                    pad_samples = int((dur_en - dur_es) * rate)
                    if pad_samples > 0 and torch is not None:
                        arr = distribute_silence_padding(arr, int(dur_en * rate), rate)
                else:
                    # Estirar con atempo para equiparar la duración del segmento original
                    # Piso seguro de velocidad de 0.75x para preservar naturalidad; el remanente se distribuye orgánicamente
                    min_allowed_speed = 0.75
                    if ratio_slow < min_allowed_speed:
                        effective_speed = min_allowed_speed
                        mode_tag = f"🔉 {effective_speed:.2f}x (+pad)"
                        stretch_samples = int(arr.shape[-1] / effective_speed)
                        arr = adjust_audio_duration(arr, stretch_samples, rate)
                        target_samples = int(dur_en * rate)
                        if target_samples > arr.shape[-1] and torch is not None:
                            arr = distribute_silence_padding(arr, target_samples, rate)
                    else:
                        mode_tag = f"🔉 {ratio_slow:.2f}x (expand)"
                        target_samples = int(dur_en * rate)
                        arr = adjust_audio_duration(arr, target_samples, rate)
            else:
                mode_tag = "✨ 1.00x (natural)"

        # Micro-fade out suave (256 muestras) al final del audio para eliminar ruidos de corte abrupto
        if arr.shape[-1] > 256 and torch is not None:
            fade_len = min(256, arr.shape[-1])
            fade = torch.linspace(1.0, 0.0, fade_len, device=arr.device)
            arr[:, -fade_len:] *= fade

        # Aplicar target_duration (modo 's') si está presente
        if target_duration is not None and target_duration > 0:
            raw_speed = dur_es / target_duration if target_duration > 0 else 1.0
            effective_speed = max(0.5, min(raw_speed, 2.0))
            mode_tag = f"🎯 {effective_speed:.2f}x (target)"
            target_samples = int(target_duration * rate)
            arr = adjust_audio_duration(arr, target_samples, rate)
        # Aplicar speed manual del usuario si es distinto de 1.0 y no se aplicó target_duration
        elif speed != 1.0:
            target_samples = int(arr.shape[-1] / speed)
            mode_tag = f"🎛️ {speed:.2f}x (manual)"
            arr = adjust_audio_duration(arr, target_samples, rate)

        # Tope final estricto: ningún segmento puede exceder la duración total del video
        if video_total_duration is not None:
            max_end = video_total_duration - 0.05
            curr_dur = arr.shape[-1] / rate
            if start_time + curr_dur > max_end:
                allowed_sec = max(0.1, max_end - start_time)
                target_samples = int(allowed_sec * rate)
                arr = adjust_audio_duration(arr, target_samples, rate)
                mode_tag = "✂️ clamp (fin video)"

        # Actualizar metadatos de duración y fin real del segmento
        final_dur = arr.shape[-1] / rate
        text_dict["end"] = round(start_time + final_dur, 3)
        text_dict["duration"] = round(final_dur, 3)

        # Formateo estricto de columnas alineadas (Línea métrica)
        seq_col = f"{seq_num:>3d}. "
        mode_col = _pad_visible_tag(mode_tag, 20)

        # Si hubo auto-heal, incluir short en la caja de duraciones
        h = healed_records.get(idx)
        short_part = f" | short: {h['old_dur']:5.2f}s" if h else ""

        # Solo si la duración final difiere sustancialmente tanto de orig como de fish (ej. clamp final de video)
        extra_fin = ""
        if abs(final_dur - dur_en) > 0.08 and abs(final_dur - raw_dur_es) > 0.08:
            extra_fin = f" ➔ fin: {final_dur:5.2f}s"

        dur_col = f"[orig: {dur_en:5.2f}s{short_part} | fish: {raw_dur_es:5.2f}s{extra_fin}]"
        print(f"{seq_col}{mode_col}{dur_col}")

        indent = "      "

        orig_text = str(text_dict.get("orig_text") or text_dict.get("original_text") or "").strip()
        short_text = h.get("old_text") if h else None

        aligned_lines = _format_aligned_segment_texts(
            orig_text=orig_text,
            final_text=text,
            short_text=short_text,
            source_lang=src_lang,
            indent=indent,
        )
        for line in aligned_lines:
            print(line)
        print()

        # Generar nombre con formato consistente: tts_{speaker}_{NNNN}.wav
        # Esto permite al frontend identificar el segmento y su speaker
        audio_es_path = seqs_trg_dir / f"tts_{safe_speaker}_{seq_num:03d}.wav"
        torchaudio.save(str(audio_es_path), arr, sample_rate=rate)
        path_es.append(audio_es_path)
        start_samples = int(start_time * rate)
        times.append(start_samples)

    if healed_records:
        print(f"\n✨ [Auto-Heal] {len(healed_records)} segmentos re-expandidos exitosamente en el flujo de doblaje.", flush=True)

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
