"""
Pipeline: cola de videos, transcripción, división en secuencias.
"""
import contextlib
import io
import pickle
from pathlib import Path
from typing import Union, Optional

import torchaudio

from src.download import yt
from src.stt import run_main
from src.config import QUEUE_DIR


def process_video_queue(
    urls: list[str],
    translate_lang: Union[bool, str] = False,
    on_stage: Optional[callable] = None,
) -> list[dict]:
    """
    Procesa una cola de videos: descarga, transcribe y traduce.
    Si ya existe un procesamiento previo completo, lo carga de caché.
    """
    results = []
    for idx, u in enumerate(urls, 1):
        print(f"⚙️ Procesando: {u}  [{idx}/{len(urls)}]")
        if on_stage:
            try:
                on_stage(u, "downloading", f"⚙️ Procesando: {u}  [{idx}/{len(urls)}]")
            except Exception:
                pass
        try:
            # --- Pre-verificación de Caché por URL ---
            found_in_cache = False
            # Escanear carpetas en Queue para ver si alguna tiene este link
            for folder in QUEUE_DIR.glob("*"):
                pkl_file = folder / "result.pkl"
                if pkl_file.exists():
                    try:
                        with open(pkl_file, "rb") as f:
                            cached_data = pickle.load(f)
                            # pkl: (translated_result, output_name, url, result, transcription, diarization)
                            if len(cached_data) >= 3 and cached_data[2] == u:
                                print(f"♻️ Link en caché: {folder.name}")
                                if on_stage:
                                    try:
                                        on_stage(u, "cached", f"En caché: {folder.name}")
                                    except Exception:
                                        pass
                                translated_result, output_name, url, result, transcription, diarization = cached_data
                                
                                # Encontrar el archivo de video original (.mp4) dentro de la carpeta
                                # yt-dlp lo guarda como folder_name.mp4 dentro de folder_name/
                                video_files = list(folder.glob("*.mp4"))
                                # Excluir el resultante si tiene el mismo nombre, preferimos el original
                                # pero si solo hay uno, usamos ese.
                                if video_files:
                                    path = video_files[0]
                                    results.append({
                                        "path": path,
                                        "output_name": output_name,
                                        "url": u,
                                        "texts": translated_result,
                                        "src_lang": transcription.language,
                                        "result": result,
                                        "transcription": transcription,
                                        "diarization": diarization,
                                        "cached": True
                                    })
                                    found_in_cache = True
                                    break
                    except: continue
            
            if found_in_cache:
                continue
            # ---------------------------------------

            path, info = yt(u, vocals_separation=True)
            output_file = path.with_name("result.pkl")
            
            # --- Lógica de Caché por Path (en caso de que el URL no se detectó antes pero el archivo sí existe) ---
            if output_file.exists():
                print(f"♻️ Cargando caché: {path.name}")
                with open(output_file, "rb") as f:
                    cached_data = pickle.load(f)
                    # El pkl guarda: (translated_result, output_name, url, result, transcription, diarization)
                    translated_result, output_name, url, result, transcription, diarization = cached_data
                
                results.append({
                    "path": path,
                    "output_name": output_name,
                    "url": u,
                    "info": info,
                    "texts": translated_result,
                    "src_lang": transcription.language,
                    "result": result,
                    "transcription": transcription,
                    "diarization": diarization,
                    "cached": True
                })
                print(f"✅ {output_name}")
                continue
            # -----------------------

            print("📝 Transcribiendo (Whisper + diarización)...")
            if on_stage:
                try:
                    on_stage(u, "transcribing", "📝 Transcribiendo (Whisper + diarización)...")
                except Exception:
                    pass
            translated_result, output_name, result, transcription, diarization = run_main(
                path, u, translate=translate_lang
            )
            if translate_lang:
                print("🔤 Traduciendo texto con Gemini...")
            
            with open(output_file, "wb") as f:
                pickle.dump(
                    (translated_result, output_name, u, result, transcription, diarization),
                    f,
                )
            
            print(f"✅ {output_name}  🚩  {len(translated_result)} segmentos")

            if on_stage:
                try:
                    on_stage(u, "ready", f"Listo: {output_name}")
                except Exception:
                    pass
            results.append({
                "path": path,
                "output_name": output_name,
                "url": u,
                "info": info,
                "texts": translated_result,
                "src_lang": transcription.language,
                "result": result,
                "transcription": transcription,
                "diarization": diarization,
                "cached": False
            })
        except Exception as e:
            print(f"❌ Error procesando {u}: {e}\n")
            if on_stage:
                try:
                    on_stage(u, "error", str(e))
                except Exception:
                    pass
            continue
    return results


def split_audio_sequences(
    audio_path: Path,
    texts: list[dict],
    output_dir: Optional[Path] = None,
    edit_indices: Optional[list[int]] = None,
) -> list[Path]:
    """Divide el audio en secuencias según los segmentos de texto."""
    if output_dir is None:
        output_dir = audio_path.parent / "Seqs_src"
    output_dir.mkdir(exist_ok=True)

    arr, org_sr = torchaudio.load(str(audio_path))
    generated_files = []

    texts_to_process = texts if edit_indices is None else [texts[i - 1] for i in edit_indices]

    for idx, text_dict in enumerate(texts_to_process):
        start = int(text_dict["start"] * org_sr)
        end = int(text_dict["end"] * org_sr)
        arr_split = arr[:, start:end]

        seq_num = edit_indices[idx] if edit_indices else texts.index(text_dict) + 1
        audio_filename = f"{audio_path.stem}_{seq_num:04d}.wav"
        audio_path_out = output_dir / audio_filename

        f_err = io.StringIO()
        with contextlib.redirect_stderr(f_err):
            torchaudio.save(str(audio_path_out), arr_split, sample_rate=org_sr)
        generated_files.append(audio_path_out)

    return generated_files


def split_all_sequences(video_paths: list[Path]) -> None:
    """Divide el audio de todos los videos en secuencias."""
    for path in video_paths:
        texts_file = path.with_name("result.pkl")
        if not texts_file.exists():
            print(f"⚠️ Saltando {path.stem}: no hay archivo de textos")
            continue
        with open(texts_file, "rb") as f:
            texts, output_name, url, result, transcription, diarization = pickle.load(f)
        split_audio_sequences(
            audio_path=path.with_name("vocals.wav"),
            texts=texts,
            output_dir=path.parent / "Seqs_src",
        )
