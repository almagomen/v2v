import type { StateCreator } from "zustand";
import { v2vApi } from "../api/v2v-api";
import {
  type V2VSegmentInfo,
  generateFolderId,
} from "../utils/v2v-segment-ids";
import type {
  V2VState,
  FoldersSlice,
  V2VFolderRef,
  SerializedFolderData,
} from "./v2v-types";

export const FOLDER_REFS_STORAGE_KEY = "openreel.v2v.folderRefs";

export function loadFolderRefsFromStorage(): Record<string, SerializedFolderData> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(FOLDER_REFS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, SerializedFolderData>;
    const result: Record<string, SerializedFolderData> = {};
    for (const [key, value] of Object.entries(parsed)) {
      result[key] = value;
    }
    return result;
  } catch {
    return {};
  }
}

export function saveFolderRefsToStorage(refs: Record<string, SerializedFolderData>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(FOLDER_REFS_STORAGE_KEY, JSON.stringify(refs));
  } catch {
    // ignore quota
  }
}

export const createFoldersSlice: StateCreator<V2VState, [], [], FoldersSlice> = (set, get) => ({
  folderRefs: loadFolderRefsFromStorage(),

  setFolderRef: (folder: string, ref: V2VFolderRef) =>
    set((state) => {
      const existing = state.folderRefs[folder];
      const now = Date.now();
      const newFolderData: SerializedFolderData = {
        folderId: existing?.folderId || generateFolderId(folder, ref.jobId),
        jobId: ref.jobId,
        videoIndex: ref.videoIndex,
        outputName: ref.outputName || null,
        nativeFiles: ref.nativeFiles || [],
        segments: existing?.segments || {},
        createdAt: existing?.createdAt || now,
        updatedAt: now,
        projectId: ref.projectId,
      };
      const folderRefs = { ...state.folderRefs, [folder]: newFolderData };
      saveFolderRefsToStorage(folderRefs);
      return { folderRefs };
    }),

  getFolderRef: (folder: string) => {
    const mem = get().folderRefs[folder];
    if (mem) return mem;
    const disk = loadFolderRefsFromStorage()[folder];
    if (disk) {
      set((state) => ({
        folderRefs: { ...state.folderRefs, [folder]: disk },
      }));
      return disk;
    }
    return undefined;
  },

  removeFolderRef: (folder: string) =>
    set((state) => {
      const next = { ...state.folderRefs };
      delete next[folder];
      saveFolderRefsToStorage(next);
      return { folderRefs: next };
    }),

  renameFolderRef: (oldFolder: string, newFolder: string) =>
    set((state) => {
      if (!state.folderRefs[oldFolder]) return state;
      const next = { ...state.folderRefs };
      const renamedFolder = { ...next[oldFolder], folderId: generateFolderId(newFolder, next[oldFolder].jobId) };
      next[newFolder] = renamedFolder;
      delete next[oldFolder];
      saveFolderRefsToStorage(next);
      return { folderRefs: next };
    }),

  setSegmentInfo: (folder: string, segment: V2VSegmentInfo) =>
    set((state) => {
      const folderData = state.folderRefs[folder];
      if (!folderData) {
        console.warn(`[V2V] No folderRef found for ${folder}`);
        return state;
      }
      const now = Date.now();
      const segments = { ...folderData.segments, [segment.segmentId]: segment };
      const updatedFolder: SerializedFolderData = {
        ...folderData,
        segments,
        updatedAt: now,
      };
      const folderRefs = { ...state.folderRefs, [folder]: updatedFolder };
      saveFolderRefsToStorage(folderRefs);
      return { folderRefs };
    }),

  getSegmentInfo: (folder: string, segmentId: string) => {
    const folderData = get().folderRefs[folder];
    return folderData?.segments[segmentId];
  },

  getSegmentByMediaId: (folder: string, mediaId: string) => {
    const folderData = get().folderRefs[folder];
    if (!folderData) return undefined;
    for (const segment of Object.values(folderData.segments)) {
      if (segment.mediaId === mediaId) {
        return segment;
      }
    }
    return undefined;
  },

  updateSegmentText: (folder: string, segmentId: string, text: string) =>
    set((state) => {
      const folderData = state.folderRefs[folder];
      if (!folderData || !folderData.segments[segmentId]) return state;
      const now = Date.now();
      const updatedSegment: V2VSegmentInfo = {
        ...folderData.segments[segmentId],
        editedText: text,
        updatedAt: now,
      };
      const segments = { ...folderData.segments, [segmentId]: updatedSegment };
      const updatedFolder: SerializedFolderData = {
        ...folderData,
        segments,
        updatedAt: now,
      };
      const folderRefs = { ...state.folderRefs, [folder]: updatedFolder };
      saveFolderRefsToStorage(folderRefs);
      return { folderRefs };
    }),

  updateSegmentSpeaker: (folder: string, segmentId: string, speaker: string | null) =>
    set((state) => {
      const folderData = state.folderRefs[folder];
      if (!folderData || !folderData.segments[segmentId]) return state;
      const now = Date.now();
      const updatedSegment: V2VSegmentInfo = {
        ...folderData.segments[segmentId],
        speaker,
        updatedAt: now,
      };
      const segments = { ...folderData.segments, [segmentId]: updatedSegment };
      const updatedFolder: SerializedFolderData = {
        ...folderData,
        segments,
        updatedAt: now,
      };
      const folderRefs = { ...state.folderRefs, [folder]: updatedFolder };
      saveFolderRefsToStorage(folderRefs);
      return { folderRefs };
    }),

  updateSegmentSpeed: (folder: string, segmentId: string, speed: number | null) =>
    set((state) => {
      const folderData = state.folderRefs[folder];
      if (!folderData || !folderData.segments[segmentId]) return state;
      const now = Date.now();
      const updatedSegment: V2VSegmentInfo = {
        ...folderData.segments[segmentId],
        speed,
        updatedAt: now,
      };
      const segments = { ...folderData.segments, [segmentId]: updatedSegment };
      const updatedFolder: SerializedFolderData = {
        ...folderData,
        segments,
        updatedAt: now,
      };
      const folderRefs = { ...state.folderRefs, [folder]: updatedFolder };
      saveFolderRefsToStorage(folderRefs);
      return { folderRefs };
    }),

  syncFolderAssets: async (jobId, videoIndex, folder) => {
    try {
      const assets = await v2vApi.getManifest(jobId, videoIndex);
      const filenames = Object.entries(assets)
        .flatMap(([k, v]) => {
          if (typeof v === "string") return [v];
          if (k === "segments" && typeof v === "object" && v !== null) {
            return Object.values(v).filter((val): val is string => typeof val === "string");
          }
          return [];
        })
        .map((v) => v.split(/[\\/]/).pop() || "");

      set((state) => {
        const ref = state.folderRefs[folder];
        if (!ref) return state;
        const next = {
          ...state.folderRefs,
          [folder]: { ...ref, nativeFiles: filenames },
        };
        saveFolderRefsToStorage(next);
        return { folderRefs: next };
      });
    } catch (e) {
      console.warn(`[V2V] Error al sincronizar manifiesto para ${folder}:`, e);
    }
  },
});
