import { create } from "zustand";
import type { Segment, VideoResult } from "../lib/v2v-api";

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
    }),
}));

