import type { MediaItem, Project } from "@openreel/core";

/**
 * Clips del timeline que se enviarán al render de Colab.
 *
 * Vive fuera del componente para poder probar la semántica de mute/solo/hidden
 * sin montar la UI.
 */

type ClipStatus = "ok" | "upload_needed" | "not_allowed";

export interface AnalyzedClip {
  clipId: string;
  mediaId: string;
  mediaName: string;
  type: "video" | "audio";
  start: number;
  end: number;
  trackStart: number;
  volume: number;
  status: ClipStatus;
  blob?: Blob;
}

/** Determine if a media_name belongs to a V2V folder (already in Colab). */
export function isInV2VFolder(
  mediaName: string,
  folderRefs: Record<string, unknown>,
): boolean {
  const norm = mediaName.replace(/\\/g, "/");
  const filename = norm.split("/").pop() || norm;

  for (const folderKey of Object.keys(folderRefs)) {
    const ref = folderRefs[folderKey] as { nativeFiles?: unknown };
    if (ref?.nativeFiles && Array.isArray(ref.nativeFiles)) {
      if (ref.nativeFiles.includes(filename) || ref.nativeFiles.includes(norm)) {
        return true;
      }
    }
  }

  // Detección tolerante de medios que provienen intrínsecamente del pipeline V2V en Colab
  const isV2VStandardAsset =
    filename.startsWith("tts_") ||
    filename.startsWith("seg_") ||
    filename.startsWith("video_only") ||
    filename.startsWith("merged") ||
    filename.startsWith("vocals_") ||
    filename === "vocals.wav" ||
    filename === "vocals.m4a" ||
    filename.startsWith("no_vocals") ||
    filename.startsWith("instrumental") ||
    filename.includes("tts_") ||
    filename.includes("seg_");

  if (isV2VStandardAsset && Object.keys(folderRefs).length > 0) {
    return true;
  }

  return false;
}

/**
 * Recorre el timeline y devuelve los clips que deben renderizarse.
 *
 * Respeta el estado de las pistas tal como lo hace la reproducción:
 * - `hidden`: la pista no aporta ni vídeo ni audio.
 * - `muted`: su audio no entra en la mezcla. Las pistas de audio se omiten por
 *   completo (no se descargan ni se resuelven); el vídeo se mantiene visible con
 *   `volume: 0` para que su audio tampoco suene.
 * - `solo`: si hay alguna pista en solo, solo suenan las pistas en solo.
 *
 * Así, importar los cortes originales (que se crean silenciados) y exportar no
 * vuelve a mezclar el audio original en el vídeo final.
 */
export function analyzeProject(
  project: Project,
  folderRefs: Record<string, unknown>,
): AnalyzedClip[] {
  const mediaMap = new Map<string, MediaItem>(
    project.mediaLibrary.items.map((m) => [m.id, m]),
  );

  const clips: AnalyzedClip[] = [];

  const renderTracks = project.timeline.tracks.filter(
    (track) => track.type === "video" || track.type === "audio",
  );
  // Misma semántica que la reproducción: una pista en solo silencia al resto.
  const hasSoloTracks = project.timeline.tracks.some((track) => track.solo);

  for (const track of renderTracks) {
    // Una pista oculta no aporta ni vídeo ni audio al render.
    if (track.hidden) continue;

    const isAudible = !track.muted && (!hasSoloTracks || track.solo);
    // Las pistas de audio silenciadas se omiten por completo: no se descargan,
    // no se resuelven y no entran en la mezcla (p. ej. los cortes originales).
    if (track.type === "audio" && !isAudible) continue;

    for (const clip of track.clips) {
      const media = mediaMap.get(clip.mediaId);
      if (!media) continue;
      if (media.type === "image") continue;

      const inServer = isInV2VFolder(media.name, folderRefs);
      const hasBlob = !!media.blob;

      let status: ClipStatus;
      if (inServer) {
        status = "ok";
      } else if (hasBlob) {
        status = "upload_needed";
      } else {
        status = "not_allowed";
      }

      clips.push({
        clipId: clip.id,
        mediaId: clip.mediaId,
        mediaName: media.name,
        type: track.type as "video" | "audio",
        start: clip.inPoint ?? 0,
        end: clip.outPoint ?? (clip.inPoint ?? 0) + clip.duration,
        trackStart: clip.startTime,
        // El vídeo de una pista silenciada sigue visible, pero su audio no suena.
        volume: isAudible ? (clip.volume ?? 1.0) : 0,
        status,
        blob: media.blob ?? undefined,
      });
    }
  }

  return clips;
}
