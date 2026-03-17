#!/usr/bin/env python3
"""
Lanza el backend v2v + OpenReel en Colab.
Uso en Colab:
  1. !pip install -r requirements.txt
  2. (opcional) from google.colab import drive; drive.mount('/content/drive')
  3. !python colab_launch.py

Para tunnel público usa ngrok:
  !pip install pyngrok
  from pyngrok import ngrok
  url = ngrok.connect(8000)
  print(f"Abre OpenReel en: {url.public_url}")
"""
import os
import sys
import subprocess
import webbrowser
from pathlib import Path

# Asegurar que el proyecto está en el path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main():
    # Verificar que openreel está construido
    dist_path = PROJECT_ROOT / "openreel" / "apps" / "web" / "dist"
    if not dist_path.exists():
        print("⚠️  OpenReel no está construido. Ejecuta en el directorio del proyecto:")
        print("   cd openreel && pnpm install && pnpm build")
        print("   Luego copia openreel/apps/web/dist al proyecto o ejecuta desde v2v con openreel ya construido.")
        print("   Para Colab: construye localmente y sube la carpeta dist, o usa build en Colab (requiere Node/pnpm).")
        resp = input("¿Continuar sin OpenReel? (s/n): ")
        if resp.lower() != "s":
            sys.exit(1)

    print("Iniciando servidor v2v en http://0.0.0.0:8000")
    print("API docs: http://localhost:8000/docs")
    if dist_path.exists():
        print("OpenReel: http://localhost:8000/")
    else:
        print("Sin frontend OpenReel - solo API disponible en /docs")

    # En Colab, 0.0.0.0 permite acceso externo
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        cwd=PROJECT_ROOT,
    )


if __name__ == "__main__":
    main()
