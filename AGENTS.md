# Reglas del Workspace y Guía Maestra: Fork V2V sobre OpenReel

Este documento es la **fuente de verdad única** de arquitectura, reglas de aislamiento y mantenimiento para desarrolladores y asistentes de IA (LLMs) que trabajen en este repositorio.

---

## 🚨 REGLAS MANDATORIAS PARA AGENTES E IA

1. **Aislamiento Total (Near-Zero Core Touch)**:
   - Todo código, componente, slice de Zustand, cliente API, utilidad o tipo de Video2Video debe residir **exclusivamente dentro de**:
     👉 `openreel/apps/web/src/v2v/`
   - **NUNCA modificar archivos de configuración o scripts de OpenReel**:
     - NO tocar `openreel/apps/desktop/package.json` ni añadir scripts en `openreel/apps/desktop/scripts/`.
     - NO modificar `package.json`, `pnpm-lock.yaml`, `vite.config.ts` ni `tsconfig.json` de OpenReel.
     - NO colocar código de V2V en los directorios nativos (`src/components/`, `src/stores/`, `src/lib/`, `src/utils/`).
   - **Puntos de montaje estrictamente limitados a 2 líneas en todo el proyecto**:
     1. `openreel/apps/web/src/components/editor/Toolbar.tsx`: `<V2VToolbarEntry />`
     2. `openreel/apps/web/src/desktop/DesktopApp.tsx`: `{hasProject && isVideoEditing ? <V2VToolbarEntry /> : null}`

2. **Compilación Oficial de Desktop (.exe en Windows)**:
   Ejecutar estrictamente el comando documentado:
   ```powershell
   cd .\openreel\
   $env:OPENREEL_DESKTOP="1"; pnpm --filter @openreel/web build; pnpm --filter @openreel/desktop run build:main; pnpm --filter @openreel/desktop exec electron-builder --dir
   ```

3. **Estado de V2V asociado al Proyecto Activo (Project Isolation)**:
   - La cola, URLs, videos procesados y logs del panel V2V están vinculados al `project.id` del proyecto actualmente abierto en OpenReel (`openreel.v2v.projectJob.<projectId>`).
   - Si se crea un **proyecto nuevo** o se abre un proyecto en blanco, el panel V2V arranca **completamente limpio**.
   - Si se abre un **proyecto existente** que ya tenía un trabajo V2V, restaura automáticamente sus URLs, videos y logs.
   - Las claves de API (Fish Audio, Google Gemini) y la URL del backend son globales y se conservan entre proyectos.

4. **Estrategia Anti-Límites de Cloudflare Tunnel y Optimización de Audio M4A (Regla Mandatoria)**:
   - Cloudflare Tunnel impone un límite estricto de **100 segundos** para el *primer byte* (Time To First Byte - TTFB) arrojando error `HTTP 524`.
   - **Prohibido empaquetar o comprimir en memoria (`io.BytesIO`)** durante peticiones HTTP.
   - **Arquitectura Dual de Audio en `Seqs_trg` (Sin duplicación WAV)**:
     - `tts_{speaker}_{idx}_raw.wav`: Máster puro e intacto generado por Fish Audio conservado exclusivamente para regeneraciones y sliders de velocidad/duración sin pérdida generativa acumulativa.
     - `tts_{speaker}_{idx}.m4a`: Audio final sincronizado y comprimido directamente a AAC 192k para el Timeline de OpenReel, empaquetado TAR y renderizado FFmpeg con GPU en Colab.
     - **Prohibido generar `.wav` sincronizados redundantes**: solo existen el máster `_raw.wav` y el sincronizado `.m4a`.
   - **Pre-caching en Background Instantáneo**: El paquete `audio_segments.tar.gz` se genera al terminar la síntesis TTS empaquetando directamente los `.m4a` existentes en disco (tiempo <150ms, tamaño ~2.5MB, 90% de ahorro de ancho de banda).
   - Todo endpoint de transferencia masiva (TAR de segmentos, videos largos, películas) debe **servirse directamente desde disco con `FileResponse`** (`sendfile()`) para emitir el primer byte en <10ms.
   - En el cliente (`v2v-api.ts`), **ninguna transferencia de medios tiene tope total**: usan una guarda de 30 s hasta las cabeceras y otra de 45 s sin recibir datos (watchdog de estancamiento), más descompresión nativa `DecompressionStream("gzip")`. Los activos de vídeo grandes se descargan además por rangos HTTP en paralelo (máximo 4 trozos de ~8 MB por archivo) cuando el servidor confirma soporte con `HEAD` + `Range`; si lo ignora, se consume la misma respuesta como un único flujo. Un semáforo global limita a **6 las conexiones de rango simultáneas** en toda la app, para que importar varios activos a la vez no sature los sockets. Los flujos únicos reintentan una vez ante errores de red o 5xx (nunca ante 4xx).
   - **Peticiones POST que devuelven medios** (regenerar TTS, aplicar velocidad, render de timeline y render batch) usan la misma guarda de estancamiento: sin tope al tiempo hasta las cabeceras (la generación puede tardar), pero con aborto y error claro si el cuerpo deja de avanzar.
   - **TTS Concurrente**: La síntesis con Fish Audio se paraleliza con `ThreadPoolExecutor(max_workers=5)` con reintento exponencial ante HTTP 429 para acelerar 4x la generación.
   - **Auto-emociones (`/enhance/text`)**: Es un endpoint interno del Studio de Fish. Solo responde con el **token de sesión web** de Fish (copiado de DevTools) en `FISH_ENHANCE_TOKEN`; la API key pública de TTS (`FISH_API_KEY`) no sirve para este endpoint. El token se lee del entorno o de los secretos de Kaggle/Colab, y el panel incluye un botón «Probar token» que avisa si está caducado. La opción de auto-emociones solo se puede activar cuando hay token. Sin token válido se registra el fallo una sola vez y se sintetiza el texto original, sin fallback a Gemini.
   - En fallbacks individuales de red, **prohibido `Promise.all` masivo** sin control de concurrencia; usar lotes concurrentes (máximo 5) con reintentos para evitar saturación de sockets en Chromium (error 429/502).
   - **Sincronía Temporal Exacta (Sin Silencio Artificial)**: Si el TTS queda más corto que su clip original (`orig_duration`), se alargan primero sus pausas internas reales (`distribute_silence_padding`) y, si no basta, se estira la voz con atempo hasta un suelo de `0.80x`. Prohibido añadir ceros o silencio artificial al final del clip (`pad_tail_silence` eliminado): la duración del clip en el timeline es siempre su duración física real. Si el TTS es tan corto que ni a `0.80x` cubre el hueco, se deja el hueco real entre clips antes que falsear la duración o inventar silencio. La duración en timeline de los clips TTS y originales refleja siempre su duración física real; prohibido aplicar fallbacks que fuercen la duración del audio original sobre el TTS o viceversa.

5. **Política de Cero Código Muerto y Barrido Post-Refactor (Zero-Dead-Code Policy)**:
   - Todo asistente de IA o desarrollador DEBE realizar un barrido completo de código huérfano después de modificar, simplificar o retirar cualquier funcionalidad, algoritmo, parámetro o endpoint:
     1. **Rastreo Integral Upstream y Downstream**: Realizar búsqueda exhaustiva (`grep`) de cada identificador, parámetro o flag eliminado a lo largo de toda la cadena completa:
        - UI (`TokensConfigSection`, `V2VPanel`, etc.)
        - Stores y Tipos (`v2v-types.ts`, `v2v-storage.ts`, `v2v-job-slice.ts`)
        - Cliente API (`v2v-api.ts`)
        - Backend FastAPI (`schemas.py`, `service.py`, `routes/process.py`)
        - Pipeline y STT/TTS (`pipeline.py`, `stt.py`, `translation.py`, `audio_utils.py`)
     2. **Eliminación en Cascada**: Prohibido dejar parámetros "fantasma", props no usadas, campos obsoletos en schemas o llamadas accesorias de extracción/cálculo cuyos resultados terminen descartados (ej. `.pop()`, métricas no leídas, módulos huérfanos).
     3. **Validación Dual de Compilación**: Tras cualquier refactorización, es obligatorio validar la sintaxis backend (`python -m py_compile`) y la compilación estricta de TypeScript (`pnpm --filter @openreel/web build`) antes de dar la tarea por concluida.

---

## 1. Filosofía de la Integración

Toda la funcionalidad de Video2Video vive encapsulada en `apps/web/src/v2v/`:
- **Cero colisiones con Upstream**: Actualizaciones y rebases desde el repo oficial (`Augani/openreel-video`) ocurren sin tocar el módulo V2V.
- **Cero cambios de configuración de compilación**: El alias nativo `@/*` resuelve `@/v2v` sin alterar bundlers.
- **Atajo global**: `Alt+V` para alternar el panel en cualquier plataforma.

---

## 2. Inventario del Módulo `apps/web/src/v2v/`

```
apps/web/src/v2v/
├── index.ts                           # Barrel export público (V2VToolbarEntry)
├── api/
│   └── v2v-api.ts                     # Cliente HTTP/WebSocket Typed con FastAPI, AbortController y endpoints
├── components/
│   ├── V2VToolbarEntry.tsx            # Punto de montaje UI: botón en Toolbar, drawer lateral y modal z-[200]
│   ├── V2VPanel.tsx                   # Panel principal: inferencia, modelos, tokens, limpieza por proyecto
│   ├── V2VSegmentBulkEditor.tsx       # Editor masivo flotante de segmentos (STT vs TTS, retraducción, sliders)
│   ├── V2VGenerateTTSSection.tsx      # Generador y sintetizador TTS por segmentos
│   ├── ColabExportTab.tsx             # Pestaña de exportación y render final acelerado por GPU en Colab
│   ├── TokensConfigSection.tsx        # Configuración de claves de API y modelos Gemini
│   ├── SpeakerSelector.tsx            # Selector de voz y emoción inicial
│   ├── JobProgressIndicator.tsx       # Barra de progreso de etapa, logs por URL y cancelaciones
│   ├── RenderProgressBar.tsx          # Progreso de renderizado FFmpeg en backend
│   ├── CatboxUploadStatus.tsx         # Estado de subida y enlace de descarga de Catbox
│   ├── BatchRenderQueue.tsx           # Visualización de la cola de videos a renderizar
│   ├── EmotionSelector.tsx            # Selector de emociones Fish Audio (S2.1)
│   ├── SegmentAudioSliders.tsx        # Sliders de temperatura, top_p, penalty y volumen
│   ├── SegmentRow.tsx                 # Fila individual de edición de segmento en el Bulk Editor
│   ├── TTSBatchControls.tsx           # Cabecera y accesos rápidos de generación TTS
│   └── TTSSegmentCard.tsx             # Tarjeta de edición de segmento con controles de velocidad
├── stores/
│   ├── v2v-types.ts                   # Tipos TypeScript centralizados para todos los slices
│   ├── v2v-storage.ts                 # Persistencia indexada por project.id (openreel.v2v.projectJob.<id>)
│   ├── v2v-folders-slice.ts           # Slice: gestión de carpetas, nativeFiles y folderRefs
│   ├── v2v-segments-slice.ts          # Slice: segmentos, speakers, multi-speaker mapping
│   ├── v2v-job-slice.ts               # Slice: WebSocket real-time, HTTP polling adaptativo y syncWithProject
│   ├── v2v-store.ts                   # Store unificado que combina todos los slices
│   └── colab-export-store.ts          # Slice: cola de renderizado en lote hacia Colab / Catbox
└── utils/
    ├── v2v-segment-regen.ts           # Regeneración de audio sin tocar el caché inmutable de OpenReel
    ├── v2v-segment-ids.ts             # Generador y parser de IDs deterministas de segmentos
    ├── v2v-utils.ts                   # Normalización de tokens, nombres lógicos y emparejamiento
    ├── v2v-detached-actions.ts        # Acciones sobre proyectos desacoplados e inserción en lote
    └── v2v-emotions.ts                # Catálogo unificado de emociones Fish Audio (s2.1)
```

---

## 3. Arquitectura del Backend y Formato de Persistencia (100% JSON)

1. **Cero Dependencias Binarias Propietarias (Sin Pickle)**: Toda inferencia se guarda en `result.json` en la carpeta del video (`drive_dir / out_dir / result.json`). Centralizado en `src/result_store.py`.
2. **Indexación O(1) de URLs en Cola**: Mantenido en `Queue/url_index.json`.
3. **Escritura por Lotes de Logs (`_LogBuffer`)**: `api/job_store.py` ejecuta flush cada 2s o 4KB, reduciendo la contención de disco.
4. **Dual-GPU Pipeline**: CrisperWhisper (o Whisper Turbo en modo `stable`) y el detector de idioma Whisper `tiny` en GPU 0, y Pyannote Diarization en GPU 1, en paralelo con `ThreadPoolExecutor` en `kaggle_launch.ipynb`. El detector se puede cambiar con `WHISPER_LANG_MODEL`.
5. **Transferencia Optimizada**: Instrumental (`no_vocals.m4a`), voz aislada (`vocals.m4a`), segmentos originales (`Seqs_src/*.m4a`) y segmentos sintetizados (`Seqs_trg/tts_*.m4a`) servidos en AAC/M4A 192k (ahorro del 90-94% de peso, reduciendo paquetes de segmentos de 27MB a ~2.5MB con fidelidad acústica de estudio) y TAR de segmentos cacheados en disco servidos vía `FileResponse` (primer byte <10ms) para transferencias instantáneas e ilimitadas a través de Cloudflare Tunnel.

---

## 4. Soporte Multi-Speaker Real y Diarización

1. **Preservación de `original_speaker`**: Pyannote clasifica por palabra (`assign_speakers_by_word`). El tag se conserva inmutable en `result.json`.
2. **Mapeo Flexible de Voces (`speaker_map`)**: Envía mapeos `{ "SPEAKER_00": "mrbeast", "SPEAKER_01": "default_fish" }` para clonación diferenciada por personaje.
3. **Control Visual**: En `V2VSegmentBulkEditor`, barra de reasignación masiva por speaker.
4. **Token de Hugging Face (`HF_TOKEN`) y repos restringidos**:
   - `pyannote/speaker-diarization-3.1` y `pyannote/segmentation-3.0` son repos **gated**. Sin token, Hugging Face responde `401 Unauthorized` sobre `config.yaml`, un mensaje que no explica el motivo real.
   - Los secretos de Colab y Kaggle se activan **por notebook**: al importar o copiar el notebook el interruptor «Acceso del notebook» se reinicia. Por eso los lanzadores **nunca** deben tragarse el fallo en silencio: imprimen qué secretos faltan y las instrucciones exactas de cada plataforma.
   - `get_hf_token()` acepta los alias `HF_TOKEN`, `HUGGINGFACE_TOKEN`, `HUGGING_FACE_HUB_TOKEN` y `HF_API_TOKEN`, lee de entorno, Colab userdata y Kaggle Secrets, y normaliza el valor en `HF_TOKEN`. Basta un token de **lectura**.
   - Si `Pipeline.from_pretrained` falla con 401/403, `src/diarization.py` diagnostica entonces el motivo real (`whoami` → `model_info` por repo) para distinguir «sin token», «token inválido» y «cuenta sin acceso». El diagnóstico es **posterior al fallo**, nunca previo: así una carga desde caché o un corte de red no se convierten en un falso «falta el token».
   - `huggingface_hub.login()` se llama **sin kwargs específicos de versión** (`login(token=...)`); `write_permission` ya no existe en las versiones actuales y hacía fallar el arranque aunque el token fuera correcto.
   - Los lanzadores marcan `/tmp/v2v_deps_ok` tras instalar dependencias: si el kernel sigue vivo, volver a ejecutar la celda **no reinstala** nada aunque la carga de modelos haya fallado antes.
5. **Qué se congela y qué se traduce (`entity lock`)**:
   - El criterio es general y vale para cualquier categoría: un término se **traduce** si el idioma destino tiene una forma propia y establecida para él; se **conserva** solo si el destino no tiene esa forma y lo reproduce con la misma grafía y pronunciación que el original.
   - La mayúscula no decide nada: el ASR capitaliza inicios de fragmento y palabras comunes. Los términos que el juez no conserva se traducen en la llamada principal; los conservados viajan como marcadores y se restauran intactos.
   - La consolidación de variantes del ASR **nunca** agrupa formas que solo difieran por una variación gramatical (número, género, conjugación): son palabras distintas, no dos grafías de la misma entidad.
   - Los prompts no incluyen listas ni ejemplos de pares de palabras: un diccionario nunca cubre todos los pares de idiomas y un ejemplo sesga la inferencia.

---

## 5. Streaming Real-Time WebSocket, HTTP Polling y Formato de Logs

1. **Streaming y Polling**:
   - Endpoint `/ws/job/{job_id}` despacha `job_snapshot`, `log_chunk` y `job_update`.
   - Fallback automático e ininterrumpido a HTTP polling cada 2s si la red o proxy bloquea WebSockets.
2. **Formato Fluido de Logs en Backend**:
   - Prohibido forzar anchos fijos tabulares con emojis o sangrías arbitrarias (`_pad_visible_tag`, sangrías de 10+ espacios) en terminal o visor de logs.
   - Las etiquetas de idioma (`[pt]`) y emoción (`[confident]`) se alinean a la derecha para que los corchetes de cierre coincidan visualmente sin sangría base, dejando el wrapping de texto libre para que el CSS del contenedor del frontend lo ajuste responsivamente.

---

## 6. Estrategia de Audio y Caché del Timeline

OpenReel indexa `AudioBuffer` en memoria usando `${mediaId}:0`. Para evitar que el reproductor ignore audios regenerados:
1. `v2v-segment-regen.ts` llama a `importMedia(file)` para generar un **nuevo `mediaId`**.
2. Reemplaza `clip.mediaId = newMediaId` y actualiza duración en el timeline.
3. Borra el blob viejo con `deleteMediaBlob(oldMediaId)` y ejecuta `loadProject()`.
4. OpenReel decodifica el nuevo ID al instante sin parches sobre el core.

---

## 7. Estrategia de Red y Mitigación de Límites de Cloudflare Tunnel

Al comunicar el cliente OpenReel con el backend a través de Cloudflare Tunnel (Kaggle/Colab), aplican restricciones estrictas que todo agente e IA debe respetar:

1. **Evasión del Timeout de 100s de Cloudflare (Error 524) y Pre-caching en Background**:
   - Cloudflare Tunnel cancela cualquier petición si no recibe el primer byte (TTFB) en 100 segundos.
   - **Solución implementada**:
     - `ensure_audio_segments_tar`: Empaqueta anticipadamente a disco (`folder / "audio_segments.tar.gz"`) directamente los archivos `.m4a` ya generados en disco con compresión gzip ligera (`compresslevel=1`, >150MB/s), ignorando los másters `*_raw.wav` para reducir el tamaño al 10% (de ~27MB a ~2.5MB en <0.15s).
     - Se ejecuta automáticamente en background al finalizar la etapa de TTS (o en caché hit), de modo que cuando el cliente solicita el paquete, ya está 100% generado en disco.
     - Se sirve mediante `FileResponse` utilizando `sendfile()` del kernel: el primer byte se transmite en <10ms hacia Cloudflare, lo cual **desactiva el timeout de 100s** y permite transferir películas de 2 horas sin interrupciones.
     - Caché en disco con validación por `mtime` de los segmentos para entrega instantánea en reimportaciones.

2. **Cero Límites Artificiales y Descompresión Nativa en el Cliente**:
   - Ninguna descarga de medios impone un tope total. `fetchBufferWithGuards` aplica 30 s máximo para recibir cabeceras y 45 s máximo sin datos entre chunks. Una transferencia lenta pero viva puede terminar; una conexión colgada falla con un error claro en vez de dejar la importación bloqueada. La cancelación manual sigue disponible vía `AbortSignal`.
   - Los flujos únicos (TAR, segmentos sueltos, archivos pequeños) reintentan una vez ante errores de red o 5xx; nunca ante un 4xx.
   - Detección automática de magic bytes gzip (`0x1f, 0x8b`) y descompresión en memoria mediante la API nativa de Chromium `DecompressionStream("gzip")`.

3. **Descarga por Rangos Paralelos para Activos Grandes**:
   - `fetchAssetBlob`, `fetchFileBlob` y `fetchOutputVideoBlob` sondean el tamaño con `HEAD` (cabeceras safelisted, legibles en cross-origin) y confirman soporte con `Range: bytes=0-0`.
   - Si el servidor responde `206` y el archivo supera 8 MB, se descarga en hasta 4 trozos de ~8 MB escritos directamente en su posición del buffer final. Cada trozo tiene 3 intentos. Si los rangos fallan de forma definitiva, se reintenta con un único flujo; si el servidor ignora `Range` (`200`), se consume esa misma respuesta sin descargar dos veces.
   - Un semáforo global limita a **6 las conexiones de rango simultáneas** en toda la app. Así, importar varios activos a la vez (que se piden en paralelo con `Promise.all`) no satura los sockets ni dispara `429/502`.

4. **Guarda de Estancamiento en POST que Devuelven Medios**:
   - `regenerateSegment`, `generateNewAudioSegment`, `applyAudioSpeed`, `renderTimeline` y `renderBatch` consumen el cuerpo con la misma guarda de estancamiento.
   - No se impone tope al tiempo hasta las cabeceras (la generación/render puede tardar minutos), pero si el cuerpo deja de avanzar durante 45 s se aborta con un mensaje claro.

5. **Control de Concurrencia en Fallback de Descargas (Anti-Saturación de Sockets)**:
   - Si el paquete TAR no está disponible y se recurre a descargar segmentos individualmente, las peticiones se procesan en lotes secuenciales de **5 peticiones simultáneas** con reintento automático (`CONCURRENCY_LIMIT = 5`).
   - Esto evita saturar los 6 sockets máximos de Chromium/Electron y previene bloqueos por rate limit (`429`) o `Connection Reset` (`502/524`) en Cloudflare.

6. **Síntesis TTS Concurrente (Fish Audio)**:
   - En `src/audio_utils.py`, `clone_voice_segments` ejecuta llamadas concurrentes con `ThreadPoolExecutor(max_workers=5)`, acelerando la generación de cientos de clips de minutos a segundos sin sobrepasar los límites de concurrencia de la API.
   - En `src/tts.py`, reintentos automáticos con backoff exponencial ante respuestas HTTP 429 (Rate Limit).

---

## 8. Protocolo de Actualización desde Upstream (`Augani/openreel-video`)

```bash
git remote add openreel-upstream https://github.com/Augani/openreel-video.git 2>/dev/null || true
git fetch openreel-upstream main
git merge openreel-upstream/main --allow-unrelated-histories -m "chore(openreel): merge upstream updates" -X subtree=openreel
```

### Reglas de Resolución de Conflictos:
1. `openreel/apps/web/src/v2v/*`: Tomar nuestra versión (`--ours`).
2. Archivos del core (`Timeline.tsx`, `project-store.ts`, etc.): Tomar versión de upstream (`--theirs`).
3. `Toolbar.tsx` y `DesktopApp.tsx`: Verificar que contengan los puntos de montaje de `<V2VToolbarEntry />`.
