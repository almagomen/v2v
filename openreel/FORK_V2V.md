# Fork V2V sobre OpenReel

Este directorio integra **Video2Video** (API FastAPI en el repo padre), carpetas de medios, clonación de voz en el **panel Video2Video** (no en el inspector) y persistencia `v2vFolderRefs` en el guardado del proyecto.

## Estrategia: menos conflictos al actualizar OpenReel

La idea es **concentrar lo específico de V2V** en rutas y módulos que upstream casi no toca (tabla “propios del fork”) y **minimizar parches** en archivos grandes que upstream cambia a menudo (Toolbar, AssetsPanel, `Preview.tsx`, `project-store.ts`). Cada merge debería:

1. Usar esta lista como checklist: si un archivo no está aquí, preferir **no** mezclar lógica V2V allí.
2. Tras traer upstream, **reaplicar solo los enganches** documentados en “compartidos”, no reescribir archivos enteros salvo conflicto inevitable.
3. Mantener el backend V2V en el **repo padre** (`api/`, `src/`) fuera del subtree `openreel/` cuando sea posible, para no inflar el diff del prefijo OpenReel.

Los cambios recientes (Vite Colab/proxy, caché de preview tras clonar voz, flag `needsV2VServerUpload`, resolución de rutas en render ffmpeg) siguen esa línea: **pocas líneas en superficies ya marcadas como sensibles** (`Preview`, `project-store`, `ColabExportTab`, `CloneVoiceSegmentSection`) más un campo opcional en el tipo core y un ajuste en `api/routes/render.py` del repo padre.

## Dev server y proxy API (Vite)

Archivo: [`apps/web/vite.config.ts`](apps/web/vite.config.ts)

| Qué | Por qué |
|-----|--------|
| `server.allowedHosts: true` y `preview.allowedHosts: true` | Colab / Codatalab usan un `Host` dinámico (`*.colab.dev`); sin esto Vite rechaza la petición. |
| `server.proxy` / `preview.proxy` para `"/api"` → `V2V_API_PROXY_TARGET` (defecto `http://127.0.0.1:8000`) | En dev el front suele ir en `:5173` y FastAPI en `:8000`. Las llamadas relativas a `/api/*` deben **reenviarse a uvicorn**; si no, Vite responde 404 o HTML del SPA. Variable de entorno opcional: **`V2V_API_PROXY_TARGET`** (sin barra final). |

El cliente sigue usando `VITE_V2V_API_URL` cuando el build debe apuntar a una API absoluta; el proxy cubre el caso **mismo origen en Colab + API en localhost del runtime**.

## Timeline / export tras “Clone voice”

Problema resuelto: la inferencia era correcta pero el **preview seguía con audio decodificado en caché** y el **export ffmpeg en Colab** leía el wav antiguo en disco.

| Repo | Archivo | Cambio breve |
|------|---------|----------------|
| OpenReel | `apps/web/src/components/editor/Preview.tsx` | En `openreel:preview-invalidate` se vacían `audioBufferCacheRef`, `processedAudioBufferCacheRef` y se revoca la URL del vídeo nativo asociada. |
| OpenReel | `apps/web/src/stores/audio-cache-store.ts` | `invalidateAudioCache` también dispara `openreel:preview-invalidate`. |
| OpenReel | `apps/web/src/components/editor/v2v/CloneVoiceSegmentSection.tsx` | `invalidateAudioCache` al **final** del flujo (tras `trimClip` / `loadProject`). Montado desde `V2VPanel` con clip único seleccionado en el timeline. |
| OpenReel | `packages/core/src/types/project.ts` | Campo opcional `needsV2VServerUpload` en `MediaItem`. |
| OpenReel | `apps/web/src/stores/project-store.ts` | `replaceMediaAsset` marca el flag si el nombre cae bajo un `folderRef` V2V; `clearNeedsV2VServerUpload` tras subida. |
| OpenReel | `apps/web/src/components/editor/ColabExportTab.tsx` | Clips con flag + blob → `upload_needed`; tras `uploadMediaForRender` se limpia el flag. |
| **Repo padre** (no bajo `openreel/`) | `api/routes/render.py` | `_resolve_media_path`: primero intenta archivo existente en `job_folder/<ruta relativa de media_name>` (seguro bajo el job), luego manifiesto / índice TTS. |

## Archivos propios del fork (bajo riesgo en sync)

| Área | Ruta |
|------|------|
| Cliente API | `apps/web/src/lib/v2v-api.ts` |
| Estado V2V | `apps/web/src/stores/v2v-store.ts` |
| Utilidades / IDs | `apps/web/src/utils/v2v-utils.ts`, `apps/web/src/utils/v2v-segment-ids.ts` |
| Import masivo | `apps/web/src/utils/import-media-into-project.ts` |
| UI | `apps/web/src/components/editor/V2VPanel.tsx`, `ColabExportTab.tsx` |
| Clonar voz (V2V) | `apps/web/src/components/editor/v2v/CloneVoiceSegmentSection.tsx` |
| Caché audio (V2V + preview) | `apps/web/src/stores/audio-cache-store.ts` |
| Vite (Colab / proxy API) | `apps/web/vite.config.ts` |
| Env | `apps/web/.env.example` (bloque `VITE_V2V_API_URL`) |
| Carpetas / timeline V2V en Assets | `apps/web/src/v2v/assets-integration/` (`v2v-folder-utils.ts`, `useV2VMediaFolders.ts`, `V2VMediaFolderChrome.tsx`) |

## Archivos compartidos con upstream (revisar en cada merge)

- `apps/web/src/components/editor/Toolbar.tsx` — icono YouTube, drawer `V2VPanel`, guardado manual.
- `apps/web/src/components/editor/AssetsPanel.tsx` — **solo enganches** en la pestaña Media: hook `useV2VMediaFolders`, componentes `V2VMediaFolderRails` / `V2VMediaFolderModals`, import y drop delegados en `v2v.importDroppedFiles`, rejilla con `v2v.filteredItems` e `itemForThumbnail`. La lógica pesada está en `v2v/assets-integration/`.
- `apps/web/src/components/editor/InspectorPanel.tsx` — **sin** sección Clone Voice V2V (el flujo vive en `V2VPanel` para reducir conflictos con upstream).
- `apps/web/src/components/editor/Preview.tsx` — listener `openreel:preview-invalidate`: vaciar cachés de audio (y URL de vídeo nativo) para que clone voice / efectos reflejen el blob actual.
- `apps/web/src/stores/project-store.ts` — `v2vFolderRefs` en `forceSave` y al recuperar autosave; **`replaceMediaAsset`** / **`clearNeedsV2VServerUpload`** para export Colab coherente con medios regenerados.
- `packages/core/src/types/project.ts` — campo opcional **`needsV2VServerUpload`** en `MediaItem` (serializable con el proyecto).
- `apps/web/src/components/editor/GenerateAudioSegmentSection.tsx` — TTS por carpeta y API v2v.

## Cómo actualizar desde `Augani/openreel-video`

El historial del prefijo `openreel/` no comparte ancestros con el upstream; `git subtree pull` puede responder *refusing to merge unrelated histories*. En este repo se usa:

```bash
git fetch openreel-upstream main
git merge openreel-upstream/main --allow-unrelated-histories -m "Merge OpenReel upstream main" -X subtree=openreel
```

Si aparecen muchos conflictos `AA` (add/add), una estrategia que funcionó aquí:

1. `git checkout --theirs openreel` y `git add openreel` para tomar la base upstream.
2. Restaurar desde la rama anterior los archivos **solo V2V** de la tabla de arriba (`git checkout <rama-base>:openreel/apps/web/...`), incluyendo `apps/web/src/components/editor/v2v/`.
3. Reaplicar a mano los parches en Toolbar, **`V2VPanel.tsx`** (drawer + bloque clonar voz + `useUIStore`), **`Preview.tsx`**, **`project-store.ts`**, **`packages/core/src/types/project.ts`**, **`audio-cache-store.ts`**, **`vite.config.ts`**, `ColabExportTab.tsx`, **`v2v/CloneVoiceSegmentSection.tsx`** y `.env.example` (usar la sección “compartidos” y las tablas de este documento como guía).
4. **AssetsPanel**: conservar el archivo upstream y volver a insertar el bloque V2V (imports de `useV2VMediaFolders` y `V2VMediaFolderRails` / `V2VMediaFolderModals`, `v2v.filteredItems` en la rejilla, delegación de import/drop en `v2v.importDroppedFiles`). Si upstream cambió la pestaña Media, edita solo el `case "media"` y deja intacto Recipes/Templates/KieAI.

5. `pnpm install && pnpm run build` dentro de `openreel/`.

## Comprobación rápida

- Build: `cd openreel && pnpm run build`
- Panel Video2Video (toolbar): procesar URLs, carpetas en Assets, **clonar voz** (un solo clip de audio TTS seleccionado en el timeline), proyecto con `v2vFolderRefs` tras guardar y recuperar.
- Tras **Clonar voz**, el preview del timeline debe usar el audio nuevo sin recargar; **Export Colab (ffmpeg)** debe alinear subida de blobs cuando el ítem tiene `needsV2VServerUpload`.
- **Colab + `pnpm dev`**: el host `*.colab.dev` es aceptado por Vite y las peticiones `POST/GET` a `/api/...` llegan al backend vía proxy (puerto distinto al 5173).
