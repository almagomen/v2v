import { v2vApi } from "../api/v2v-api";
import { useProjectStore } from "@/stores/project-store";
import { useV2VStore } from "../stores/v2v-store";
import { generateSegmentId } from "./v2v-segment-ids";
import { toSafeToken, parseV2VSegmentFromName, findSegmentMediaInLibrary } from "./v2v-utils";
import { moveClipToTrack } from "@/utils/detached-project-actions";

export async function getAudioDuration(blob: Blob): Promise<number> {
  const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("AudioContext no soportado");
  }
  const audioContext = new AudioContextClass();
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    return audioBuffer.duration;
  } finally {
    audioContext.close();
  }
}

export function findClipIdForSegment(
  mediaId: string,
  trackStart: number,
  tolerance = 0.08,
): string | null {
  const { project } = useProjectStore.getState();
  for (const track of project.timeline.tracks) {
    if (track.type !== "audio") continue;
    for (const clip of track.clips) {
      if (clip.mediaId === mediaId && Math.abs(clip.startTime - trackStart) < tolerance) {
        return clip.id;
      }
    }
  }
  for (const track of project.timeline.tracks) {
    if (track.type !== "audio") continue;
    const clip = track.clips.find((c) => c.mediaId === mediaId);
    if (clip) return clip.id;
  }
  return null;
}

export function resolveMediaIdForSegment(
  segIdx: number,
  opts?: { speaker?: string | null; filename?: string | null },
): string | undefined {
  const { project } = useProjectStore.getState();
  const match = findSegmentMediaInLibrary(project.mediaLibrary.items, {
    seg: segIdx,
    speaker: opts?.speaker ?? undefined,
    filename: opts?.filename ?? undefined,
  });
  return match?.id;
}

function speakerFilenameToken(
  previousToken: string,
  selectedVoice: string,
  speakerLabel: string,
): string {
  if (previousToken === selectedVoice || previousToken === toSafeToken(selectedVoice)) {
    return previousToken;
  }
  return speakerLabel.replace(/[^a-zA-Z0-9_-]/g, "_") || toSafeToken(selectedVoice);
}

export type ApplyRegenParams = {
  folder: string;
  jobId: string;
  videoIndex: number;
  segIdx: number;
  regenBlob: Blob;
  text: string;
  speaker: string;
  speakerLabel: string;
  previousSpeakerToken: string;
  start: number;
  end: number;
  effectiveSpeed: number;
  mediaId?: string;
  clipId?: string;
  trackStart: number;
  targetStartTime?: number;
};

export type ApplyRegenResult = {
  success: boolean;
  message: string;
  mediaId?: string;
  clipId?: string;
};

export async function applyRegeneratedSegmentToTimeline(
  params: ApplyRegenParams,
): Promise<ApplyRegenResult> {
  const {
    folder,
    jobId,
    videoIndex,
    segIdx,
    regenBlob,
    text,
    speaker,
    speakerLabel,
    previousSpeakerToken,
    effectiveSpeed,
    trackStart,
  } = params;

  let mediaId = params.mediaId;
  const segmentId = generateSegmentId(jobId, videoIndex, segIdx);

  const filenameToken = speakerFilenameToken(previousSpeakerToken, speaker, speakerLabel);
  const newFileName = `tts_${filenameToken}_${String(segIdx).padStart(3, "0")}.wav`;
  const newMediaName = newFileName;
  const file = new File([regenBlob], newMediaName, { type: "audio/wav" });

  if (!mediaId) {
    mediaId = resolveMediaIdForSegment(segIdx, {
      speaker,
      filename: newFileName,
    });
  }

  if (!mediaId) {
    return {
      success: false,
      message: `No hay media en el proyecto para el segmento ${segIdx}`,
    };
  }

  const { importMedia, forceSave, loadProject, getClip, getMediaItem } =
    useProjectStore.getState();

  const { updateSegmentText, updateSegmentSpeaker, updateSegmentSpeed } = useV2VStore.getState();
  updateSegmentText(folder, segmentId, text);
  updateSegmentSpeaker(folder, segmentId, speaker);
  updateSegmentSpeed(folder, segmentId, effectiveSpeed);

  // Importar el nuevo audio como nuevo MediaItem para asegurar que OpenReel
  // genere un nuevo mediaId con waveform y decodificación fresca sin colisionar
  // con la caché inmutable de AudioBuffer interna del reproductor.
  const oldMediaId = mediaId;
  const importResult = await importMedia(file);
  if (!importResult.success || !importResult.actionId) {
    const msg =
      typeof importResult.error === "string"
        ? importResult.error
        : importResult.error?.message || "Error al importar el audio regenerado";
    return { success: false, message: msg };
  }

  const newMediaId = importResult.actionId;
  const newDuration = await getAudioDuration(regenBlob);
  let clipId = params.clipId ?? findClipIdForSegment(oldMediaId, trackStart);

  let currentProject = useProjectStore.getState().project;

  // Actualizar el clip en el timeline para apuntar al nuevo mediaId, posición y duración
  const effectiveNewStart = params.targetStartTime !== undefined ? params.targetStartTime : params.start;

  if (clipId) {
    currentProject = {
      ...currentProject,
      timeline: {
        ...currentProject.timeline,
        tracks: currentProject.timeline.tracks.map((track) => ({
          ...track,
          clips: track.clips.map((clip) => {
            if (clip.id === clipId) {
              const inPoint = clip.inPoint ?? 0;
              return {
                ...clip,
                startTime: effectiveNewStart !== undefined ? effectiveNewStart : clip.startTime,
                mediaId: newMediaId,
                inPoint,
                outPoint: inPoint + newDuration,
                duration: newDuration,
              };
            }
            return clip;
          }),
        })),
      },
      modifiedAt: Date.now(),
    };
  }

  const speakerChanged =
    previousSpeakerToken !== speaker && previousSpeakerToken !== toSafeToken(speaker);

  if (speakerChanged && clipId) {
    const moveResult = await moveClipToTrack(
      currentProject,
      clipId,
      speakerLabel,
      effectiveNewStart !== undefined ? effectiveNewStart : trackStart,
    );
    if (moveResult.success) {
      currentProject = moveResult.project;
    }
  }

  // Eliminar el mediaItem viejo de la librería para evitar duplicados
  if (oldMediaId && oldMediaId !== newMediaId) {
    currentProject = {
      ...currentProject,
      mediaLibrary: {
        ...currentProject.mediaLibrary,
        items: currentProject.mediaLibrary.items.filter((item) => item.id !== oldMediaId),
      },
      modifiedAt: Date.now(),
    };
    try {
      const { deleteMediaBlob } = await import("@/services/media-storage");
      await deleteMediaBlob(oldMediaId);
    } catch {
      // Ignorar si el blob anterior ya no existía
    }
  }

  // Cargar el proyecto actualizado en el store de OpenReel
  loadProject(currentProject);

  try {
    const parts = newMediaName.replace(/\\/g, "/").split("/");
    const subfolder = parts.length > 1 ? parts[0] : "";
    const baseName = parts[parts.length - 1] ?? newFileName;
    await v2vApi.uploadMediaForRender(
      jobId,
      videoIndex,
      new File([regenBlob], baseName, { type: "audio/wav" }),
      subfolder || undefined,
    );
    await useV2VStore.getState().syncFolderAssets(jobId, videoIndex, folder);
  } catch (syncErr) {
    console.warn("[V2V] No se pudo sincronizar el audio regenerado en Colab:", syncErr);
  }

  await forceSave();

  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent("openreel:preview-invalidate", { detail: { mediaId: newMediaId } }),
    );
  }

  return {
    success: true,
    message: speakerChanged
      ? `Segmento ${segIdx} regenerado y movido a "${speakerLabel}"`
      : `Segmento ${segIdx} regenerado`,
    mediaId,
    clipId: clipId ?? undefined,
  };
}

export function parsedSpeakerTokenFromMediaName(mediaName: string): string {
  const parsed = parseV2VSegmentFromName(mediaName);
  return parsed?.speakerToken ?? "speaker";
}
