"""
Lanzador principal de Video2Video + OpenCut.
Inicia el backend FastAPI (puerto 8000) y el frontend OpenCut (puerto 5173).
En Google Colab, crea un túnel público mediante cloudflared.
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


def start_colab_tunnel(port: int = 5173):
    """Descarga e inicia cloudflared para exponer OpenCut con URL pública."""
    print(f"\n🌐 Configurando túnel público para puerto {port}...")
    cloudflared_path = Path("/usr/local/bin/cloudflared")
    if not cloudflared_path.exists():
        subprocess.run(
            ["curl", "-sSL", "-o", str(cloudflared_path),
             "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"],
            check=True
        )
        subprocess.run(["chmod", "+x", str(cloudflared_path)], check=True)

    log_file = Path("/tmp/cloudflared.log")
    tunnel_proc = subprocess.Popen(
        [str(cloudflared_path), "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Leer URL pública de los logs de cloudflared
    tunnel_url = None
    time.sleep(3)
    if tunnel_proc.stdout:
        for _ in range(25):
            line = tunnel_proc.stdout.readline()
            if "trycloudflare.com" in line:
                for word in line.split():
                    if "trycloudflare.com" in word:
                        tunnel_url = word.strip()
                        break
                if tunnel_url:
                    break
            time.sleep(0.5)

    if tunnel_url:
        print("\n" + "=" * 60)
        print(f"🎉 ¡OpenCut + V2V está disponible públicamente!")
        print(f"🔗 Abre este enlace: {tunnel_url}")
        print("=" * 60 + "\n")
    else:
        print("⚠️ No se pudo obtener la URL de cloudflared. Revisa http://localhost:5173")

    return tunnel_proc


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

    # 3. Túnel si es Colab
    tunnel_proc = None
    if is_colab():
        tunnel_proc = start_colab_tunnel(port=5173)

    print("\nPresiona Ctrl+C para detener todos los servicios.\n")
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
        for proc in (api_proc, web_proc, tunnel_proc):
            if proc and proc.poll() is None:
                proc.terminate()


if __name__ == "__main__":
    main()
