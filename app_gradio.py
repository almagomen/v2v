"""
Interfaz Gradio para la pipeline Video2Video.
Uso: python app_gradio.py (local) o desde Colab con demo.launch(share=True).
"""
import io
import queue
import sys
import threading
from pathlib import Path

import gradio as gr

# Mapeo speaker: nombre en UI -> voice_id LMNT o nombre de voz
SPEAKER_OPTIONS = {
    "mrbeast_lmnt": "d47094be-9814-4323-9000-e735e04d8732",
    "Dionisio Schuyler": "Dionisio Schuyler",
    "en-US-AndrewMultilingualNeural": "en-US-AndrewMultilingualNeural",
    "Chatterbox": "Chatterbox",
}


class QueueWriter(io.TextIOBase):
    """Escribe en una cola para que el log se consuma en tiempo real."""
    def __init__(self, log_queue: queue.Queue):
        self._queue = log_queue

    def write(self, s: str) -> int:
        if s:
            self._queue.put(s)
        return len(s)

    def flush(self) -> None:
        pass


def _run_pipeline_core(
    urls: list[str],
    translate_lang: str | None,
    speaker_name: str,
) -> Path | None:
    """
    Lógica de la pipeline. Debe ejecutarse con sys.stdout ya reemplazado por QueueWriter.
    Returns: path del último video renderizado o None.
    """
    from src.config import TEMP_DIR
    from src.pipeline import process_video_queue, split_all_sequences
    from src.audio_utils import clone_voice_segments, merge_cloned_audio
    from src.render import render_video
    from src.tts import model_tts

    import torchaudio

    speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)

    print("📥 Descargando y transcribiendo...")
    results = process_video_queue(urls, translate_lang=translate_lang)
    if not results:
        print("❌ No se pudo procesar ningún video.")
        return None

    last_output_path: Path | None = None

    for idx, r in enumerate(results):
        path = r["path"]
        texts = r["texts"]
        output_name = r["output_name"]
        transcription = r["transcription"]
        lang = translate_lang if translate_lang else transcription.language

        print(f"\n✂️ [{idx + 1}/{len(results)}] Dividiendo en secuencias: {path.stem}")
        split_all_sequences([path])

        print("🎙️ Clonando voz...")
        paths_es, times, freq = clone_voice_segments(
            path,
            texts,
            lang,
            speaker_audio,
            model_tts,
            slowdown_range=(0.5, 0.8),
            stretch_target_ratio=0.85,
        )

        if not paths_es:
            print("❌ No se generaron segmentos de audio.")
            continue

        vocals_es_path = path.with_name("vocals_es.wav")
        merged = merge_cloned_audio(
            path.with_name("vocals.wav"),
            paths_es,
            times,
            freq,
        )
        torchaudio.save(str(vocals_es_path), merged, freq)

        no_vocals_path = path.with_name("no_vocals.wav")
        if not no_vocals_path.exists():
            print("❌ No se encontró no_vocals.wav")
            continue

        print("🎬 Renderizando video...")
        output_path = render_video(path, output_name, vocals_es_path, no_vocals_path)
        last_output_path = output_path
        print(f"✅ Listo: {output_path}")

    return last_output_path


def _worker(
    urls: list[str],
    translate_lang: str | None,
    speaker_name: str,
    log_queue: queue.Queue,
    result_queue: queue.Queue,
) -> None:
    old_stdout = sys.stdout
    try:
        sys.stdout = QueueWriter(log_queue)
        path = _run_pipeline_core(urls, translate_lang, speaker_name)
        result_queue.put((path,))
    except Exception as e:
        import traceback
        sys.stdout.write(traceback.format_exc() + f"\n❌ Error: {e}\n")
        result_queue.put((None,))
    finally:
        sys.stdout = old_stdout
        log_queue.put(None)


def process_streaming(
    url_input: str,
    translate_lang: str,
    speaker_name: str,
):
    """
    Handler generador: ejecuta la pipeline en un hilo y va devolviendo el log en vivo.
    """
    urls = [u.strip() for u in url_input.strip().splitlines() if u.strip()]
    if not urls:
        yield "❌ Introduce al menos una URL de YouTube (una por línea).", None, None
        return

    translate = None if translate_lang == "None" or not translate_lang else translate_lang

    log_queue: queue.Queue = queue.Queue()
    result_queue: queue.Queue = queue.Queue()

    thread = threading.Thread(
        target=_worker,
        args=(urls, translate, speaker_name, log_queue, result_queue),
    )
    thread.start()

    log_parts: list[str] = []
    while True:
        try:
            item = log_queue.get(timeout=0.05)
        except queue.Empty:
            if not thread.is_alive():
                break
            continue
        if item is None:
            break
        log_parts.append(item)
        current_log = "".join(log_parts)
        yield current_log, None, None

    try:
        output_path, = result_queue.get(timeout=1.0)
    except queue.Empty:
        output_path = None

    thread.join()
    final_log = "".join(log_parts)

    if output_path and Path(output_path).exists():
        yield final_log, str(output_path), str(output_path)
    else:
        yield final_log, None, None


def build_demo():
    with gr.Blocks(title="Video2Video", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🎬 Video2Video – Traducción y doblaje con IA")

        with gr.Row():
            url_in = gr.Textbox(
                label="URLs de YouTube (una por línea)",
                placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/watch?v=...",
                lines=5,
            )
        with gr.Row():
            translate_in = gr.Dropdown(
                label="Idioma de traducción",
                choices=["None", "es", "pt", "en", "fr", "de", "it"],
                value="es",
            )
            speaker_in = gr.Dropdown(
                label="Voz / Speaker",
                choices=list(SPEAKER_OPTIONS.keys()),
                value="mrbeast_lmnt",
            )
        btn = gr.Button("Procesar", variant="primary")

        log_out = gr.Textbox(label="Log", lines=12, interactive=False)
        video_out = gr.Video(label="Video resultante")
        file_out = gr.File(label="Descargar video")

        btn.click(
            fn=process_streaming,
            inputs=[url_in, translate_in, speaker_in],
            outputs=[log_out, video_out, file_out],
        )

    return demo


demo = build_demo()

if __name__ == "__main__":
    # En Colab usar demo.launch(share=True) para enlace público
    demo.launch(share=False)
