import type { MediaItem } from "@openreel/core";
import { useProjectStore } from "@/stores/project-store";

export function getFolderName(name: string): string | null {
  const idx = name.indexOf("/");
  if (idx <= 0) return null;
  return name.slice(0, idx);
}

export function getDisplayName(name: string): string {
  const idx = name.indexOf("/");
  return idx >= 0 ? name.slice(idx + 1) : name;
}

export function listFolderNames(mediaItems: MediaItem[]): string[] {
  return Array.from(
    new Set(
      mediaItems
        .map((m) => getFolderName(m.name))
        .filter((x): x is string => Boolean(x)),
    ),
  ).sort((a, b) => a.localeCompare(b));
}

/** Copia blobs de Media de una carpeta `folder/...` a archivos para importar en otro proyecto. */
export function collectFolderMediaFiles(items: MediaItem[], folder: string): File[] {
  const out: File[] = [];
  for (const m of items) {
    const idx = m.name.indexOf("/");
    if (idx <= 0) continue;
    if (m.name.slice(0, idx) !== folder) continue;
    if (!m.blob) continue;
    out.push(
      new File([m.blob], m.name, {
        type: m.blob.type || "application/octet-stream",
      }),
    );
  }
  return out;
}

export function renameTimelineTrack(trackId: string, name: string) {
  useProjectStore.setState((state) => ({
    project: {
      ...state.project,
      timeline: {
        ...state.project.timeline,
        tracks: state.project.timeline.tracks.map((t) =>
          t.id === trackId ? { ...t, name } : t,
        ),
      },
    },
  }));
}

export type FolderClipSnapshot = {
  mediaName: string;
  startTime: number;
  inPoint: number;
  outPoint: number;
  volume: number;
};

export type FolderTrackSnapshot = {
  type: string;
  name: string;
  clips: FolderClipSnapshot[];
};

export type FolderTimelineSnapshot = {
  folderName: string;
  tracks: FolderTrackSnapshot[];
  savedAt: number;
};

const SNAPSHOT_PREFIX = "or_folder_snapshot_";

export function getFolderSnapshotKey(folder: string) {
  return `${SNAPSHOT_PREFIX}${folder.replace(/[^a-zA-Z0-9]/g, "_")}`;
}

export function saveFolderSnapshot(snapshot: FolderTimelineSnapshot) {
  try {
    localStorage.setItem(
      getFolderSnapshotKey(snapshot.folderName),
      JSON.stringify(snapshot),
    );
  } catch {
    /* ignore */
  }
}

export function loadFolderSnapshot(folder: string): FolderTimelineSnapshot | null {
  try {
    const raw = localStorage.getItem(getFolderSnapshotKey(folder));
    return raw ? (JSON.parse(raw) as FolderTimelineSnapshot) : null;
  } catch {
    return null;
  }
}

export function extractFolderTimelineSnapshot(folder: string): FolderTimelineSnapshot {
  const { project } = useProjectStore.getState();

  const folderMediaMap = new Map<string, string>();
  for (const m of project.mediaLibrary.items) {
    const idx = m.name.indexOf("/");
    if (idx <= 0) continue;
    if (m.name.slice(0, idx) !== folder) continue;
    folderMediaMap.set(m.id, m.name.slice(idx + 1));
  }

  const tracks: FolderTrackSnapshot[] = [];

  for (const track of project.timeline.tracks) {
    const filteredClips: FolderClipSnapshot[] = [];
    for (const clip of track.clips) {
      const relName = folderMediaMap.get(clip.mediaId);
      if (!relName) continue;
      filteredClips.push({
        mediaName: relName,
        startTime: clip.startTime,
        inPoint: clip.inPoint,
        outPoint: clip.outPoint,
        volume: clip.volume ?? 1,
      });
    }
    if (filteredClips.length > 0) {
      tracks.push({
        type: track.type,
        name: track.name,
        clips: filteredClips,
      });
    }
  }

  return { folderName: folder, tracks, savedAt: Date.now() };
}
