import type { Project, MediaItem } from "@openreel/core";
import { v4 as uuidv4 } from "uuid";
import { getMediaBridge, initializeMediaBridge } from "../bridges/media-bridge";
import { saveMediaBlob } from "../services/media-storage";

export type ImportMediaIntoProjectResult =
  | { success: true; project: Project; newMediaItem: MediaItem }
  | {
      success: false;
      error: { code: "DECODE_ERROR"; message: string };
    };

/**
 * Importa un archivo a la biblioteca de un proyecto sin tocar el store global.
 * Usado p. ej. para construir proyectos V2V en segundo plano mientras el usuario sigue editando otro.
 */
export async function importMediaIntoProject(
  project: Project,
  file: File,
): Promise<ImportMediaIntoProjectResult> {
  try {
    const mediaBridge = getMediaBridge();
    if (!mediaBridge.isInitialized()) {
      await initializeMediaBridge();
    }

    const isLargeFile = file.size > 50 * 1024 * 1024;
    const importResult = await mediaBridge.importFile(file, true, isLargeFile);

    if (!importResult.success || !importResult.media) {
      return {
        success: false,
        error: {
          code: "DECODE_ERROR" as const,
          message: importResult.error || "Failed to import media",
        },
      };
    }

    const processedMedia = importResult.media;

    let thumbnailUrl: string | null = null;
    const filmstripThumbnails: { timestamp: number; url: string }[] = [];

    if (processedMedia.thumbnails && processedMedia.thumbnails.length > 0) {
      for (const thumb of processedMedia.thumbnails) {
        let thumbUrl: string | null = null;

        if (thumb.dataUrl) {
          thumbUrl = thumb.dataUrl;
        } else if (thumb.canvas) {
          try {
            if (thumb.canvas instanceof OffscreenCanvas) {
              const blob = await thumb.canvas.convertToBlob({
                type: "image/jpeg",
                quality: 0.7,
              });
              thumbUrl = URL.createObjectURL(blob);
            } else if (thumb.canvas instanceof HTMLCanvasElement) {
              thumbUrl = thumb.canvas.toDataURL("image/jpeg", 0.7);
            }
          } catch (e) {
            console.warn("Failed to convert thumbnail canvas to URL:", e);
          }
        }

        if (thumbUrl) {
          filmstripThumbnails.push({
            timestamp: thumb.timestamp,
            url: thumbUrl,
          });
        }
      }

      if (filmstripThumbnails.length > 0) {
        thumbnailUrl = filmstripThumbnails[0].url;
      }
    }

    let mediaType: "video" | "audio" | "image";
    if (file.type.startsWith("image/")) {
      mediaType = "image";
    } else if (processedMedia.metadata.hasVideo) {
      mediaType = "video";
    } else if (processedMedia.metadata.hasAudio) {
      mediaType = "audio";
    } else {
      mediaType = "image";
    }

    const newMediaItem: MediaItem = {
      id: uuidv4(),
      name: file.name,
      type: mediaType,
      fileHandle: null,
      blob: file,
      metadata: {
        duration: processedMedia.metadata.duration || 0,
        width: processedMedia.metadata.width || 0,
        height: processedMedia.metadata.height || 0,
        frameRate: processedMedia.metadata.frameRate || 0,
        codec: processedMedia.metadata.codec || "",
        sampleRate: processedMedia.metadata.sampleRate || 0,
        channels: processedMedia.metadata.channels || 0,
        fileSize: file.size,
      },
      thumbnailUrl,
      waveformData: processedMedia.waveformData?.peaks || null,
      filmstripThumbnails:
        filmstripThumbnails.length > 0 ? filmstripThumbnails : undefined,
    };

    const updatedProject: Project = {
      ...project,
      mediaLibrary: {
        ...project.mediaLibrary,
        items: [...project.mediaLibrary.items, newMediaItem],
      },
      modifiedAt: Date.now(),
    };

    try {
      await saveMediaBlob(
        updatedProject.id,
        newMediaItem.id,
        file,
        newMediaItem.metadata,
      );
    } catch (err) {
      console.error("[importMediaIntoProject] Failed to persist media blob:", err);
    }

    return {
      success: true,
      project: updatedProject,
      newMediaItem,
    };
  } catch (error) {
    return {
      success: false,
      error: {
        code: "DECODE_ERROR" as const,
        message: error instanceof Error ? error.message : "Unknown import error",
      },
    };
  }
}

export type ImportMultipleMediaResult = {
  success: boolean;
  project: Project;
  newMediaItems: MediaItem[];
  errors: { fileName: string; message: string }[];
};

/**
 * Importa múltiples archivos a la vez, optimizando el rendimiento al actualizar el proyecto una sola vez al final.
 */
export async function importMultipleMediaIntoProject(
  project: Project,
  files: File[],
  options?: { quick?: boolean }
): Promise<ImportMultipleMediaResult> {
  const mediaBridge = getMediaBridge();
  if (!mediaBridge.isInitialized()) {
    await initializeMediaBridge();
  }

  const newMediaItems: MediaItem[] = [];
  const errors: { fileName: string; message: string }[] = [];
  const quick = options?.quick ?? false;

  // Procesamos archivos. Podríamos usar Promise.all con un limitador si fuera necesario,
  // pero manteniéndolo secuencial aquí ya ahorramos los clones de proyecto y renders de React.
  for (const file of files) {
    try {
      const isLargeFile = file.size > 50 * 1024 * 1024;
      // En modo 'quick', saltamos generación de waveform para ganar velocidad
      const importResult = await mediaBridge.importFile(file, true, quick || isLargeFile);

      if (!importResult.success || !importResult.media) {
        errors.push({ fileName: file.name, message: importResult.error || "Import failed" });
        continue;
      }

      const processedMedia = importResult.media;
      const filmstripThumbnails: { timestamp: number; url: string }[] = [];

      if (processedMedia.thumbnails) {
        for (const thumb of processedMedia.thumbnails) {
          let thumbUrl: string | null = thumb.dataUrl || null;
          if (!thumbUrl && thumb.canvas) {
            try {
              if (thumb.canvas instanceof OffscreenCanvas) {
                const blob = await thumb.canvas.convertToBlob({ type: "image/jpeg", quality: 0.7 });
                thumbUrl = URL.createObjectURL(blob);
              } else if (thumb.canvas instanceof HTMLCanvasElement) {
                thumbUrl = thumb.canvas.toDataURL("image/jpeg", 0.7);
              }
            } catch {}
          }
          if (thumbUrl) filmstripThumbnails.push({ timestamp: thumb.timestamp, url: thumbUrl });
        }
      }

      const mediaType = file.type.startsWith("image/") ? "image" :
                        processedMedia.metadata.hasVideo ? "video" :
                        processedMedia.metadata.hasAudio ? "audio" : "image";

      const item: MediaItem = {
        id: uuidv4(),
        name: file.name,
        type: mediaType,
        fileHandle: null,
        blob: file,
        metadata: {
          duration: processedMedia.metadata.duration || 0,
          width: processedMedia.metadata.width || 0,
          height: processedMedia.metadata.height || 0,
          frameRate: processedMedia.metadata.frameRate || 0,
          codec: processedMedia.metadata.codec || "",
          sampleRate: processedMedia.metadata.sampleRate || 0,
          channels: processedMedia.metadata.channels || 0,
          fileSize: file.size,
        },
        thumbnailUrl: filmstripThumbnails[0]?.url || null,
        waveformData: processedMedia.waveformData?.peaks || null,
        filmstripThumbnails: filmstripThumbnails.length > 0 ? filmstripThumbnails : undefined,
      };

      newMediaItems.push(item);

      // Persistencia asíncrona (no bloqueamos el bucle principal esperando a IDB)
      saveMediaBlob(project.id, item.id, file, item.metadata).catch(err => 
        console.error("Failed to persist media:", file.name, err)
      );

    } catch (e) {
      errors.push({ fileName: file.name, message: String(e) });
    }
  }

  const updatedProject: Project = {
    ...project,
    mediaLibrary: {
      ...project.mediaLibrary,
      items: [...project.mediaLibrary.items, ...newMediaItems],
    },
    modifiedAt: Date.now(),
  };

  return {
    success: true,
    project: updatedProject,
    newMediaItems,
    errors,
  };
}
