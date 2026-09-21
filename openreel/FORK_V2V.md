# Fork V2V sobre OpenReel — Guía Maestra de Integración y Mantenimiento

Este documento detalla exhaustivamente la arquitectura de integración de **Video2Video** (backend FastAPI en el repo padre) sobre el frontend de **OpenReel**. 
Está diseñado para que futuros desarrolladores o asistentes de IA (LLMs) entiendan con total precisión cómo funciona la integración y **cómo actualizar OpenReel desde el upstream oficial sin romper el código ni introducir conflictos de Git**.

---

## 1. Filosofía de la Integración: Mínima Huella (Near-Zero Core Touch)

Toda la funcionalidad de Video2Video vive encapsulada en **módulos propios y autónomos** dentro de `apps/web/src/components/editor/v2v/`, `apps/web/src/stores/` y `apps/web/src/utils/`.

> [!IMPORTANT]
> **En toda la aplicación de OpenReel, solo existe 1 punto de montaje en el código fuente:**
> - **`apps/web/src/components/editor/Toolbar.tsx`**: Una única línea JSX que monta `<V2VToolbarEntry />`.
> 
> Todos los demás archivos del núcleo de OpenReel (`Timeline.tsx`, `project-store.ts`, `Preview.tsx`, `media-slice.ts`, `audio-engine.ts`, `EditorInterface.tsx`, `AssetsPanel.tsx`, `dialog.tsx`, `playback-controller.ts`, `playback-bridge.ts`) son **100% IDÉNTICOS al repositorio oficial upstream**.

---

## 2. Inventario Total de Archivos de la Integración

### A. Archivos Propios de V2V (Añadidos por nosotros — Riesgo Nulo en Upstream)
Estos archivos son exclusivos de V2V. Si se actualiza OpenReel desde upstream, estos archivos se conservan intactos sin colisiones:

| Archivo | Propósito |
|---|---|
| `apps/web/src/components/editor/v2v/V2VToolbarEntry.tsx` | **Punto de montaje UI único**: aloja el botón de Video2Video en el Toolbar, el drawer lateral con `V2VPanel` y el modal flotante no bloqueante (`z-[200]`) del Bulk Editor sin contaminar `Toolbar.tsx` ni `EditorInterface.tsx`. |
| `apps/web/src/components/editor/V2VPanel.tsx` | Panel principal de Video2Video: control de inferencia, selección de modelos, botón de tokens (`FISH_API_KEY`, `GOOGLE_API_KEY`), export a Colab y acceso al editor de segmentos. |
| `apps/web/src/components/editor/v2v/V2VSegmentBulkEditor.tsx` | Diálogo flotante y no bloqueante para edición masiva de segmentos (STT vs TTS, retraducción con Gemini, ajuste de parámetros Fish Audio por slot: temp, top_p, rep_penalty, volumen, chips S2 y regeneración individual). |
| `apps/web/src/components/editor/v2v/CloneVoiceSegmentSection.tsx` | Sección para clonación y síntesis de voz de un clip seleccionado en el timeline. |
| `apps/web/src/components/editor/ColabExportTab.tsx` | Pestaña de exportación y render final acelerado por GPU en Colab. |
| `apps/web/src/lib/v2v-api.ts` | Cliente HTTP Typed con endpoints de FastAPI (`/api/job/...`, `/api/settings/tokens`, etc.). |
| `apps/web/src/stores/v2v-store.ts` | Zustand store autónomo para el estado reactivo del job, segmentos, transcripciones y persistencia de `folderRefs` en `localStorage` (`openreel.v2v.folderRefs`). |
| `apps/web/src/utils/v2v-segment-regen.ts` | **Motor de regeneración de audio**: sustituye audios en el timeline de forma desacoplada usando la API pública `importMedia` (ver sección 3). |
| `apps/web/src/utils/v2v-segment-ids.ts` | Generador y parser de IDs deterministas de segmentos. |
| `apps/web/src/utils/v2v-utils.ts` | Normalización de nombres de medios (`segmentLogicalName`), parseo de tokens y emparejamiento en librería. |
| `apps/web/src/utils/detached-project-actions.ts` | Manipulación funcional del objeto `Project` de OpenReel (mover clips entre pistas con `uuidv4` seguro). |
| `apps/web/src/utils/import-media-into-project.ts` | Utilidad de importación de assets al timeline tras finalizar inferencia. |
| `apps/web/src/v2v/assets-integration/` | Helpers de integración de carpetas y assets de jobs V2V en la librería de medios. |

---

### B. Archivos Compartidos del Core de OpenReel (Puntos de Montaje)
Solo estos archivos originales contienen personalizaciones mínimas de integración:

1. **`apps/web/src/components/editor/Toolbar.tsx`**:
   - **Modificación**: Monta el componente encapsulado `<V2VToolbarEntry />` en la sección derecha del header:
     ```tsx
     import { V2VToolbarEntry } from "./v2v/V2VToolbarEntry";
     // ...
     <V2VToolbarEntry />
     ```
   - **Regla**: Conservar solo ese import y esa etiqueta JSX.

2. **`apps/web/vite.config.ts` y `.env.example`**:
   - **Modificación**: Configuración de proxy `/api` hacia `127.0.0.1:8000` (`V2V_API_PROXY_TARGET`) y `allowedHosts: true` para admitir dominios dinámicos de Google Colab / Localtunnel.

---

### C. Archivos del Core de OpenReel que están 100% Limpios (NO TOCAR)
> [!IMPORTANT]
> **REGLA DE ORO PARA LLMs Y DESARROLLADORES**: Los siguientes archivos están 100% sincronizados con upstream y **NUNCA DEBEN MODIFICARSE**:
> - `apps/web/src/components/editor/Timeline.tsx` (100% limpio — el z-index `z-[200]` se maneja en `V2VToolbarEntry.tsx`)
> - `apps/web/src/stores/project-store.ts` (100% limpio — la persistencia de proyectos V2V se maneja en `v2v-store.ts` vía `localStorage`)
> - `apps/web/src/components/editor/EditorInterface.tsx` (100% limpio — el modal flotante se aloja en `V2VToolbarEntry.tsx`)
> - `apps/web/src/components/editor/Preview.tsx` (100% limpio — la invalidación de audio se resuelve por nuevo `mediaId`)
> - `apps/web/src/stores/project/media-slice.ts` (100% limpio)
> - `packages/core/src/audio/audio-engine.ts` (100% limpio)
> - `packages/core/src/playback/playback-controller.ts` (100% limpio)
> - `apps/web/src/bridges/playback-bridge.ts` (100% limpio)
> - `apps/web/src/components/editor/AssetsPanel.tsx` (100% limpio)
> - `packages/ui/src/components/dialog.tsx` (100% limpio)

---

## 3. Estrategia de Audio y Caché del Timeline (Desacoplamiento Total)

### El Problema de OpenReel con la Caché de Audio
OpenReel maneja la reproducción de audio en `Preview.tsx` y `PlaybackController` indexando los `AudioBuffer` decodificados en memoria usando el `mediaId` (`${mediaId}:0`). 
Si se regenera un segmento y se sobreescribe el blob manteniendo el mismo `mediaId`, **OpenReel nunca vuelve a decodificar el archivo** porque la clave ya existe en su caché inmutable en RAM. Por eso sonaba el audio original y no el regenerado.

### La Solución Desacoplada (Implementada en `v2v-segment-regen.ts`)
En lugar de parchear las clases internas de OpenReel, la función `applyRegeneratedSegmentToTimeline`:
1. Llama a la API pública nativa de OpenReel: `await importMedia(file)`.
2. `importMedia` genera un **nuevo `mediaId` único**, calcula la forma de onda (*waveform*), extrae la duración real y persiste el nuevo blob en IndexedDB de forma 100% estándar.
3. Actualiza el clip en el timeline reemplazando `clip.mediaId = newMediaId` y ajustando la duración:
   ```typescript
   currentProject = {
     ...currentProject,
     timeline: {
       ...currentProject.timeline,
       tracks: currentProject.timeline.tracks.map((track) => ({
         ...track,
         clips: track.clips.map((clip) =>
           clip.id === clipId
             ? { ...clip, mediaId: newMediaId, inPoint: clip.inPoint ?? 0, outPoint: (clip.inPoint ?? 0) + newDuration, duration: newDuration }
             : clip,
         ),
       })),
     },
     modifiedAt: Date.now(),
   };
   ```
4. Elimina el `oldMediaId` de `project.mediaLibrary.items` y borra el blob viejo con `deleteMediaBlob(oldMediaId)`.
5. Ejecuta `loadProject(currentProject)` y `forceSave()`.

**Resultado**:
- OpenReel detecta un `mediaId` nuevo, no lo encuentra en su caché en RAM y lo decodifica de inmediato: **el Timeline se actualiza al instante**.
- Si el usuario arrastra el medio desde la pestaña Media, arrastra el nuevo audio.
- **Se mantiene el código del core de OpenReel completamente virgen**, garantizando compatibilidad absoluta con futuras versiones.

---

## 4. Sincronización en Backend (`api/routes/render.py` y `api/routes/files.py`)

Al regenerar un segmento desde la UI:
1. Se sube el archivo a `/api/render/upload-media`.
2. En `render.py`, si el nombre coincide con un segmento (`tts_*_NNN.wav`), se escribe tanto en la raíz como en el subdirectorio `Seqs_trg/` y se invoca `register_segment(folder, seg_idx, dest_seqs)` para actualizar el manifiesto de render final.
3. En `files.py`, `serve_file` cuenta con fallback a `Seqs_trg/{filename}` en caso de que se solicite un archivo no presente en la raíz.

---

## 5. Protocolo de Actualización desde Upstream (`Augani/openreel-video`)

Cuando se desee incorporar los últimos cambios del repositorio oficial de OpenReel:

```bash
# 1. Asegurar remote upstream
git remote add openreel-upstream https://github.com/Augani/openreel-video.git 2>/dev/null || true
git fetch openreel-upstream main

# 2. Hacer merge de upstream en la rama monorepo-subtree
git merge openreel-upstream/main --allow-unrelated-histories -m "chore(openreel): merge upstream updates" -X subtree=openreel
```

### Si ocurren conflictos:
1. **Archivos propios de V2V (`openreel/apps/web/src/components/editor/v2v/*`, etc.)**:
   - Tomar nuestra versión (`--ours`). Upstream no tiene estos archivos.
2. **Archivos limpios del core (`Timeline.tsx`, `project-store.ts`, `Preview.tsx`, `audio-engine.ts`, `media-slice.ts`, `EditorInterface.tsx`)**:
   - Tomar la versión de upstream (`--theirs`), ya que son archivos upstream puros.
3. **`Toolbar.tsx`**:
   - Aceptar los cambios de upstream y simplemente asegurar que `<V2VToolbarEntry />` esté montado en la barra superior:
     ```tsx
     import { V2VToolbarEntry } from "./v2v/V2VToolbarEntry";
     // ...
     <V2VToolbarEntry />
     ```
4. **Validar la compilación**:
   ```bash
   cd openreel/apps/web
   pnpm install
   pnpm run build
   ```
