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
