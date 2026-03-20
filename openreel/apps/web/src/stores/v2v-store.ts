import { create } from "zustand";
import type { Segment, VideoResult, JobUrlItem } from "../lib/v2v-api";

export interface V2VState {
  urls: string;
  translateLang: string;
  speaker: string;

  jobId: string | null;
  progress: number;
  error: string | null;
  videos: VideoResult[];
  selectedVideoIndex: number;
  segments: Segment[];
  selectedRowIndex: number | null;
  isProcessing: boolean;
  regenStatus: string;
  shareUrl: string | null;
  log: string;
  importStatusByKey: Record<string, "in_progress" | "done" | "error">; // `${jobId}:${videoIndex}`
  urlItems: JobUrlItem[];
  folderRefs: Record<string, { jobId: string; videoIndex: number }>;
  selectedUrlForLogs: string | null;
  urlLogs: Record<string, string>;
  jobPhase: string;

  setUrls: (urls: string) => void;
  setTranslateLang: (lang: string) => void;
  setSpeaker: (speaker: string) => void;

  setJobId: (jobId: string | null) => void;
  setProgress: (progress: number) => void;
  setError: (error: string | null) => void;

  setVideos: (videos: VideoResult[]) => void;
  setSelectedVideoIndex: (idx: number) => void;
  setSegments: (segments: Segment[] | ((prev: Segment[]) => Segment[])) => void;
  setSelectedRowIndex: (idx: number | null) => void;

  setIsProcessing: (isProcessing: boolean) => void;
  setRegenStatus: (status: string) => void;
  setShareUrl: (url: string | null) => void;
  setLog: (log: string) => void;
  setImportStatus: (key: string, status: "in_progress" | "done" | "error") => void;
  setUrlItems: (items: JobUrlItem[]) => void;
  setSelectedUrlForLogs: (url: string | null) => void;
  appendUrlLog: (url: string, line: string) => void;
  setJobPhase: (phase: string) => void;

  setFolderRef: (folder: string, ref: { jobId: string; videoIndex: number }) => void;
  removeFolderRef: (folder: string) => void;
  renameFolderRef: (oldFolder: string, newFolder: string) => void;

  reset: () => void;
}

export const useV2VStore = create<V2VState>((set) => ({
  urls: "",
  translateLang: "None",
  speaker: "mrbeast_lmnt",

  jobId: null,
  progress: 0,
  error: null,
  videos: [],
  selectedVideoIndex: 0,
  segments: [],
  selectedRowIndex: null,
  isProcessing: false,
  regenStatus: "",
  shareUrl: null,
  log: "",
  importStatusByKey: {},
  urlItems: [],
  folderRefs: {},
  selectedUrlForLogs: null,
  urlLogs: {},
  jobPhase: "idle",

  setUrls: (urls) => set({ urls }),
  setTranslateLang: (translateLang) => set({ translateLang }),
  setSpeaker: (speaker) => set({ speaker }),

  setJobId: (jobId) => set({ jobId }),
  setProgress: (progress) => set({ progress }),
  setError: (error) => set({ error }),

  setVideos: (videos) => set({ videos }),
  setSelectedVideoIndex: (selectedVideoIndex) => set({ selectedVideoIndex }),
  setSegments: (segments) =>
    set((state) => ({
      segments:
        typeof segments === "function" ? (segments as (prev: Segment[]) => Segment[])(state.segments) : segments,
    })),
  setSelectedRowIndex: (selectedRowIndex) => set({ selectedRowIndex }),

  setIsProcessing: (isProcessing) => set({ isProcessing }),
  setRegenStatus: (regenStatus) => set({ regenStatus }),
  setShareUrl: (shareUrl) => set({ shareUrl }),
  setLog: (log) => set({ log }),
  setImportStatus: (key, status) =>
    set((state) => ({
      importStatusByKey: { ...state.importStatusByKey, [key]: status },
    })),
  setUrlItems: (urlItems) => set({ urlItems }),
  setSelectedUrlForLogs: (selectedUrlForLogs) => set({ selectedUrlForLogs }),
  appendUrlLog: (url, line) =>
    set((state) => {
      const prev = state.urlLogs[url] || "";
      const next = prev ? `${prev}\n${line}` : line;
      return { urlLogs: { ...state.urlLogs, [url]: next } };
    }),
  setJobPhase: (jobPhase) => set({ jobPhase }),
  setFolderRef: (folder: string, ref: { jobId: string; videoIndex: number }) =>
    set((state) => ({
      folderRefs: { ...state.folderRefs, [folder]: ref },
    })),
  removeFolderRef: (folder: string) =>
    set((state) => {
      const next = { ...state.folderRefs };
      delete next[folder];
      return { folderRefs: next };
    }),
  renameFolderRef: (oldFolder: string, newFolder: string) =>
    set((state) => {
      if (!state.folderRefs[oldFolder]) return state;
      const next = { ...state.folderRefs };
      next[newFolder] = next[oldFolder];
      delete next[oldFolder];
      return { folderRefs: next };
    }),

  reset: () =>
    set({
      urls: "",
      translateLang: "None",
      speaker: "mrbeast_lmnt",
      jobId: null,
      progress: 0,
      error: null,
      videos: [],
      selectedVideoIndex: 0,
      segments: [],
      selectedRowIndex: null,
      isProcessing: false,
      regenStatus: "",
      shareUrl: null,
      log: "",
      importStatusByKey: {},
      urlItems: [],
      folderRefs: {},
      selectedUrlForLogs: null,
      urlLogs: {},
      jobPhase: "idle",
    }),
}));

