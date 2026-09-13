"""
Lanzador principal de Video2Video + OpenCut.
Inicia el backend FastAPI (puerto 8000) y el frontend OpenCut (puerto 5173).
En Google Colab, expone la ventana nativa mediante output.serve_kernel_port_as_window.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OPENCUT_WEB_DIR = BASE_DIR / "opencut" / "apps" / "web"


def is_colab() -> bool:
    return "google.colab" in sys.modules or os.path.exists("/content")


def start_api_server():
    """Inicia el servidor FastAPI con uvicorn."""
    print("🚀 Iniciando API Server V2V en http://localhost:8000...")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "api.server:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--log-level", "info",
    ]
    return subprocess.Popen(cmd, cwd=str(BASE_DIR))


def start_opencut_web():
    """Inicia el frontend de OpenCut con Vite."""
    print(f"🎬 Iniciando OpenCut Frontend en http://localhost:5173...")

    # Intentar bun primero, luego npm/npx
    has_bun = subprocess.run(["bun", "--version"], capture_output=True).returncode == 0
    if has_bun:
        cmd = ["bun", "run", "dev", "--host", "0.0.0.0", "--port", "5173"]
    else:
        cmd = ["npx", "-y", "vite", "--host", "0.0.0.0", "--port", "5173"]

    return subprocess.Popen(cmd, cwd=str(OPENCUT_WEB_DIR), shell=(sys.platform == "win32"))


def start_colab_window(port: int = 5173):
    """Expone el frontend OpenCut usando la utilidad nativa de Google Colab."""
    try:
        from google.colab import output
        print(f"\n🌐 Conectando túnel nativo de Google Colab en puerto {port}...")
        output.serve_kernel_port_as_window(port, anchor_text="🚀 Abrir Editor OpenCut + V2V")
        print("\n" + "=" * 60)
        print("🎉 ¡Túnel nativo de Google Colab listo!")
        print("👉 Haz clic en '🚀 Abrir Editor OpenCut + V2V' en la salida de la celda.")
        print("=" * 60 + "\n")
    except Exception as e:
        print(f"ℹ️ Entorno local (no Colab): abre http://localhost:{port}")


def main():
    print("=" * 60)
    print("   V2V Video2Video + OpenCut Launcher")
    print("=" * 60)

    # 1. Iniciar API Server
    api_proc = start_api_server()
    time.sleep(2)

    # 2. Iniciar OpenCut Frontend
    web_proc = start_opencut_web()
    time.sleep(3)

    # 3. Túnel nativo si es Google Colab
    if is_colab():
        start_colab_window(port=5173)
    else:
        print(f"\n👉 Abre http://localhost:5173 en tu navegador.\n")

    print("Presiona Ctrl+C para detener todos los servicios.\n")
    try:
        while True:
            time.sleep(1)
            if api_proc.poll() is not None:
                print("⚠️ API Server se detuvo inesperadamente.")
                break
            if web_proc.poll() is not None:
                print("⚠️ OpenCut Frontend se detuvo.")
                break
    except KeyboardInterrupt:
        print("\n👋 Deteniendo servidores...")
    finally:
        for proc in (api_proc, web_proc):
            if proc and proc.poll() is None:
                proc.terminate()


if __name__ == "__main__":
    main()
