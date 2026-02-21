"""
Interfaz Gradio para la pipeline Video2Video.
Uso: python app_gradio.py (local) o desde Colab con demo.launch(share=True).
"""
import io
import sys
from pathlib import Path

import gradio as gr

# Mapeo speaker: nombre en UI -> voice_id LMNT o nombre de voz
SPEAKER_OPTIONS = {
    "mrbeast_lmnt": "d47094be-9814-4323-9000-e735e04d8732",
    "Dionisio Schuyler": "Dionisio Schuyler",
    "en-US-AndrewMultilingualNeural": "en-US-AndrewMultilingualNeural",
    "Chatterbox": "Chatterbox",
}


def run_pipeline(
    url: str,
    translate_lang: str,
    speaker_name: str,
    progress_cb=None,
) -> tuple[str, str | None]:
    """
    Ejecuta la pipeline completa: descarga → STT → traducción → TTS → render.
    Returns: (log_text, path_del_video o None)
    """
    if not url or not url.strip():
        return "❌ Introduce una URL de YouTube.", None

    url = url.strip()
    translate = None if translate_lang == "None" or not translate_lang else translate_lang
    speaker_audio = SPEAKER_OPTIONS.get(speaker_name, speaker_name)

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    output_path = None

    try:
        from src.config import TEMP_DIR
        from src.pipeline import process_video_queue, split_all_sequences
        from src.audio_utils import clone_voice_segments, merge_cloned_audio
        from src.render import render_video
        from src.tts import model_tts

        import torchaudio

        print("📥 Descargando y transcribiendo...")
        results = process_video_queue([url], translate_lang=translate)
        if not results:
            return buf.getvalue() + "\n❌ No se pudo procesar el video.", None

        r = results[0]
        path = r["path"]
        texts = r["texts"]
        output_name = r["output_name"]
        transcription = r["transcription"]

        print("✂️ Dividiendo en secuencias...")
        split_all_sequences([path])

        print("🎙️ Clonando voz...")
        lang = translate if translate else transcription.language
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
            return buf.getvalue() + "\n❌ No se generaron segmentos de audio.", None

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
            return buf.getvalue() + "\n❌ No se encontró no_vocals.wav", None

        print("🎬 Renderizando video...")
        output_path = render_video(path, output_name, vocals_es_path, no_vocals_path)
        print(f"✅ Listo: {output_path}")

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return buf.getvalue() + f"\n❌ Error: {e}", None
    finally:
        sys.stdout = old_stdout

    return buf.getvalue(), str(output_path) if output_path else None


def build_demo():
    with gr.Blocks(title="Video2Video", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🎬 Video2Video – Traducción y doblaje con IA")

        with gr.Row():
            url_in = gr.Textbox(
                label="URL de YouTube",
                placeholder="https://www.youtube.com/watch?v=...",
                lines=1,
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

        def process(url: str, trans: str, speaker: str):
            log, path = run_pipeline(url, trans, speaker)
            if path and Path(path).exists():
                return log, path, path
            return log, None, None

        btn.click(
            fn=process,
            inputs=[url_in, translate_in, speaker_in],
            outputs=[log_out, video_out, file_out],
        )

    return demo


demo = build_demo()

if __name__ == "__main__":
    # En Colab usar demo.launch(share=True) para enlace público
    demo.launch(share=False)
