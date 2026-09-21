import { v2vApi } from "../lib/v2v-api";
import { useProjectStore } from "../stores/project-store";
import { useV2VStore } from "../stores/v2v-store";
import { invalidateAudioCache } from "../stores/audio-cache-store";
import { generateSegmentId } from "./v2v-segment-ids";
import { toSafeToken, parseV2VSegmentFromName, findSegmentMediaInLibrary } from "./v2v-utils";
import { moveClipToTrack, renameMediaInLibrary } from "./detached-project-actions";

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

  const { replaceMediaAsset, forceSave, loadProject, getClip, trimClip, getMediaItem } =
    useProjectStore.getState();

  const { updateSegmentText, updateSegmentSpeaker, updateSegmentSpeed } = useV2VStore.getState();
  updateSegmentText(folder, segmentId, text);
  updateSegmentSpeaker(folder, segmentId, speaker);
  updateSegmentSpeed(folder, segmentId, effectiveSpeed);

  const replaceResult = await replaceMediaAsset(mediaId, file);
  if (!replaceResult.success) {
    const msg =
      typeof replaceResult.error === "string"
        ? replaceResult.error
        : replaceResult.error?.message || "Error al reemplazar audio";
    return { success: false, message: msg };
  }

  invalidateAudioCache(mediaId);
  try {
    const { useEngineStore } = await import("../stores/engine-store");
    useEngineStore.getState().playbackController?.invalidateAudioBuffer(mediaId);
  } catch (err) {
    console.warn("[V2V] No se pudo invalidar audioBuffer:", err);
  }

  const newDuration = await getAudioDuration(regenBlob);
  let clipId = params.clipId ?? findClipIdForSegment(mediaId, trackStart);

  if (clipId) {
    const currentClip = getClip(clipId);
    if (currentClip) {
      const newOutPoint = currentClip.inPoint + newDuration;
      await trimClip(clipId, currentClip.inPoint, newOutPoint);
    }
  }

  const speakerChanged =
    previousSpeakerToken !== speaker && previousSpeakerToken !== toSafeToken(speaker);

  if (speakerChanged && clipId) {
    const mediaItem = getMediaItem(mediaId);
    if (mediaItem) {
      const { project: renamedProject } = useProjectStore.getState();
      const projectAfterRename = renameMediaInLibrary(renamedProject, mediaId, newMediaName);
      const moveResult = await moveClipToTrack(
        projectAfterRename,
        clipId,
        speakerLabel,
        trackStart,
      );
      if (moveResult.success) {
        loadProject(moveResult.project);
      } else {
        loadProject(projectAfterRename);
      }
    }
  }

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
      new CustomEvent("openreel:preview-invalidate", { detail: { mediaId } }),
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
