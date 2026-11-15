import type { MediaItem, Project } from "@openreel/core";
import { v4 as uuidv4 } from "uuid";

import { v2vApi, type AudioSegmentItem } from "../api/v2v-api";
import { useProjectStore } from "@/stores/project-store";
import { saveMediaBlob } from "@/services/media-storage";
import {
  addMultipleClipsToDetachedProject,
  addTrackAndGetId,
  muteTrackInProject,
  renameTrackInProject,
} from "./v2v-detached-actions";

/**
 * Reconstrucción de las pistas de audio segmentadas después de aplicar una
 * variación de cortes.
 *
 * El backend ya dejó en disco los `.m4a` nuevos y los TAR re-empaquetados, así
 * que aquí no se sintetiza nada: se descarga cada paquete una vez, se sustituyen
 * los clips de las pistas segmentadas por los del nuevo reparto y se cargan como
 * media nueva (ids frescos) para que OpenReel no sirva un `AudioBuffer` cacheado.
 *
 * Los clips que no pertenecen a esas pistas (vídeo, instrumental, voz completa)
 * no se tocan.
 */

export const TTS_MEDIA_RE = /(?:^|\/)(?:tts_|gen_).*_\d{3}\.(?:m4a|wav)$/i;
export const SRC_MEDIA_RE = /(?:^|\/)vocals_\d{3}\.(?:m4a|wav)$/i;

export const ORIGINAL_SEGMENTS_TRACK = "ORIGINAL_SEGMENTS";

export function isTtsMediaName(name: string): boolean {
  return TTS_MEDIA_RE.test(name.replace(/\\/g, "/"));
}

export function isSrcMediaName(name: string): boolean {
  return SRC_MEDIA_RE.test(name.replace(/\\/g, "/"));
}

export function findSegmentBlob(
  tarMap: Map<string, Blob>,
  seg: number,
): Blob | null {
  const pad = String(seg).padStart(3, "0");
  for (const [name, blob] of tarMap) {
    const base = name.split("/").pop() || name;
    if (base.endsWith(`_${pad}.m4a`) || base.endsWith(`_${pad}.wav`)) {
      return blob;
    }
  }
  return null;
}

/** @deprecated alias conservado para llamadas existentes. */
export const findTtsSegmentBlob = findSegmentBlob;

function mediaItemFor(name: string, blob: Blob, seg: AudioSegmentItem): MediaItem {
  const isM4A = name.endsWith(".m4a");
  return {
    id: uuidv4(),
    name,
    type: "audio",
    fileHandle: null,
    blob: null,
    metadata: {
      duration: seg.duration || Math.max(seg.end - seg.start, 0.1),
      width: 0,
      height: 0,
      frameRate: 0,
      codec: isM4A ? "aac" : "pcm_s16le",
      sampleRate: 44100,
      channels: 1,
      fileSize: blob.size,
    },
    thumbnailUrl: null,
    waveformData: null,
  };
}

/** Quita del proyecto los clips y media de las pistas que se van a rehacer. */
function withoutMedia(
  project: Project,
  matches: (name: string) => boolean,
): { project: Project; removedMediaIds: string[] } {
  const removedMediaIds = project.mediaLibrary.items
    .filter((item) => matches(item.name))
    .map((item) => item.id);
  const removed = new Set(removedMediaIds);

  return {
    removedMediaIds,
    project: {
      ...project,
      modifiedAt: Date.now(),
      timeline: {
        ...project.timeline,
        tracks: project.timeline.tracks.map((track) => ({
          ...track,
          clips: track.clips.filter((clip) => !removed.has(clip.mediaId)),
        })),
      },
      mediaLibrary: {
        ...project.mediaLibrary,
        items: project.mediaLibrary.items.filter((item) => !removed.has(item.id)),
      },
    },
  };
}

async function ensureTrack(
  project: Project,
  name: string,
  muted = false,
): Promise<{ project: Project; trackId: string | null }> {
  const existing = project.timeline.tracks.find(
    (track) => track.type === "audio" && track.name === name,
  );
  if (existing) {
    return {
      project: muted ? muteTrackInProject(project, existing.id, true) : project,
      trackId: existing.id,
    };
  }

  const { project: withTrack, trackId } = await addTrackAndGetId(project, "audio");
  if (!trackId) return { project, trackId: null };
  let next = renameTrackInProject(withTrack, trackId, name);
  if (muted) next = muteTrackInProject(next, trackId, true);
  return { project: next, trackId };
}

type RebuildSpec = {
  /** Nombre de pista por hablante o nombre único para la pista original. */
  trackName: (seg: AudioSegmentItem) => string;
  segments: AudioSegmentItem[];
  tarMap: Map<string, Blob>;
  fallbackPrefix: string;
  muted?: boolean;
};

async function rebuildTrack(
  project: Project,
  spec: RebuildSpec,
): Promise<{
  project: Project;
  items: Array<{ item: MediaItem; blob: Blob }>;
  clips: Array<{ trackId: string; mediaId: string; startTime: number; duration?: number }>;
  missing: number;
}> {
  let workingProject = project;
  const items: Array<{ item: MediaItem; blob: Blob }> = [];
  const clips: Array<{
    trackId: string;
    mediaId: string;
    startTime: number;
    duration?: number;
  }> = [];
  let missing = 0;

  const byTrack = new Map<string, AudioSegmentItem[]>();
  for (const seg of spec.segments) {
    const name = spec.trackName(seg);
    const list = byTrack.get(name) || [];
    list.push(seg);
    byTrack.set(name, list);
  }

  for (const [trackName, segs] of byTrack) {
    const ensured = await ensureTrack(workingProject, trackName, spec.muted);
    workingProject = ensured.project;
    if (!ensured.trackId) continue;

    for (const seg of segs) {
      const blob = findSegmentBlob(spec.tarMap, seg.seg);
      if (!blob) {
        missing++;
        continue;
      }
      const fileName =
        seg.filename?.split("/").pop() ||
        `${spec.fallbackPrefix}_${String(seg.seg).padStart(3, "0")}.m4a`;
      const item = mediaItemFor(fileName, blob, seg);
      items.push({ item, blob });
      clips.push({
        trackId: ensured.trackId,
        mediaId: item.id,
        startTime: seg.start,
        duration: seg.duration || Math.max(seg.end - seg.start, 0.1),
      });
    }
  }

  return { project: workingProject, items, clips, missing };
}

export type RebuildTtsResult = {
  success: boolean;
  message: string;
  clipCount: number;
  missing: number;
};

export async function rebuildSegmentationTracks(
  jobId: string,
  videoIndex: number,
  signal?: AbortSignal,
): Promise<RebuildTtsResult> {
  const audioSegs = await v2vApi.getAudioSegments(jobId, videoIndex);
  if (audioSegs.length === 0) {
    return {
      success: false,
      message: "El video no tiene segmentos de audio",
      clipCount: 0,
      missing: 0,
    };
  }
  const ttsTar = await v2vApi.fetchAudioSegmentsTar(jobId, videoIndex, signal);

  const current = useProjectStore.getState().project;
  const hasOriginalTrack = current.timeline.tracks.some(
    (track) => track.name === ORIGINAL_SEGMENTS_TRACK,
  );

  // La pista original solo se rehace si el usuario la tenía en el timeline.
  let srcSegs: AudioSegmentItem[] = [];
  let srcTar = new Map<string, Blob>();
  if (hasOriginalTrack) {
    srcSegs = await v2vApi.getSrcAudioSegments(jobId, videoIndex);
    srcTar = await v2vApi.fetchSrcAudioSegmentsTar(jobId, videoIndex, signal);
  }

  const ttsCleared = withoutMedia(current, isTtsMediaName);
  const srcCleared = hasOriginalTrack
    ? withoutMedia(ttsCleared.project, isSrcMediaName)
    : { project: ttsCleared.project, removedMediaIds: [] as string[] };

  const ttsRebuild = await rebuildTrack(srcCleared.project, {
    segments: audioSegs,
    tarMap: ttsTar,
    trackName: (seg) => (seg.speaker || "").trim() || `Speaker_${seg.seg}`,
    fallbackPrefix: "tts",
  });

  const srcRebuild = hasOriginalTrack
    ? await rebuildTrack(ttsRebuild.project, {
        segments: srcSegs,
        tarMap: srcTar,
        trackName: () => ORIGINAL_SEGMENTS_TRACK,
        fallbackPrefix: "vocals",
        muted: true,
      })
    : { project: ttsRebuild.project, items: [], clips: [], missing: 0 };

  const newItems = [...ttsRebuild.items, ...srcRebuild.items];
  const clipsToAdd = [...ttsRebuild.clips, ...srcRebuild.clips];
  const missing = ttsRebuild.missing + srcRebuild.missing;

  if (newItems.length === 0) {
    return {
      success: false,
      message: "Ningún audio nuevo estaba en el paquete del servidor",
      clipCount: 0,
      missing,
    };
  }

  const withMedia: Project = {
    ...srcRebuild.project,
    mediaLibrary: {
      ...srcRebuild.project.mediaLibrary,
      items: [
        ...srcRebuild.project.mediaLibrary.items,
        ...newItems.map(({ item }) => item),
      ],
    },
  };
  const { project: withClips } = await addMultipleClipsToDetachedProject(
    withMedia,
    clipsToAdd,
  );

  for (const { item, blob } of newItems) {
    await saveMediaBlob(withClips.id, item.id, blob, item.metadata).catch(() => {});
  }

  const { loadProject, forceSave } = useProjectStore.getState();
  loadProject(withClips);
  await forceSave();

  // Los blobs viejos ya no los usa ningún clip: se liberan para no acumular
  // megabytes por cada aplicación del banco de cortes.
  const removedMediaIds = [...ttsCleared.removedMediaIds, ...srcCleared.removedMediaIds];
  try {
    const { deleteMediaBlob } = await import("@/services/media-storage");
    await Promise.all(removedMediaIds.map((id) => deleteMediaBlob(id).catch(() => {})));
  } catch {
    // El almacenamiento de blobs es best-effort.
  }

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("openreel:preview-invalidate"));
  }

  return {
    success: true,
    message:
      missing > 0
        ? `${clipsToAdd.length} clips recolocados, ${missing} sin audio en el paquete`
        : `${clipsToAdd.length} clips recolocados en el timeline`,
    clipCount: clipsToAdd.length,
    missing,
  };
}

/** Alias histórico del panel. */
export const rebuildTtsTrackFromSegments = rebuildSegmentationTracks;
