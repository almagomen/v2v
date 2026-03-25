import { create } from "zustand";
import { v2vApi, type Segment, type VideoResult, type JobUrlItem } from "../lib/v2v-api";

const FOLDER_REFS_STORAGE_KEY = "openreel.v2v.folderRefs";
const JOB_STATE_STORAGE_KEY = "openreel.v2v.jobState";

export type V2VFolderRef = { jobId: string; videoIndex: number };

function loadFolderRefsFromStorage(): Record<string, V2VFolderRef> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(FOLDER_REFS_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, V2VFolderRef>) : {};
  } catch {
    return {};
  }
}

function saveFolderRefsToStorage(refs: Record<string, V2VFolderRef>): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(FOLDER_REFS_STORAGE_KEY, JSON.stringify(refs));
  } catch {
    // ignore quota
  }
}

type PersistedJobState = {
  urls: string;
  jobId: string | null;
  progress: number;
  videos: VideoResult[];
  selectedVideoIndex: number;
  segments: Segment[];
  urlItems: JobUrlItem[];
  urlLogs: Record<string, string>;
  jobPhase: string;
  importStatusByKey: Record<string, "in_progress" | "done" | "error">;
  log: string;
  shareUrl: string | null;
  lastUrlsSignature: string | null;
  translateLang: string;
  speaker: string;
};

function loadJobStateFromStorage(): Partial<PersistedJobState> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(JOB_STATE_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedJobState) : {};
  } catch {
    return {};
  }
}

function saveJobStateToStorage(state: Partial<PersistedJobState>): void {
  if (typeof window === "undefined") return;
  try {
    const existing = loadJobStateFromStorage();
    localStorage.setItem(
      JOB_STATE_STORAGE_KEY,
      JSON.stringify({ ...existing, ...state }),
    );
  } catch {
    // ignore quota
  }
}

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
  folderRefs: Record<string, V2VFolderRef>;
  selectedUrlForLogs: string | null;
  urlLogs: Record<string, string>;
  jobPhase: string;
  lastUrlsSignature: string | null;

  setUrls: (urls: string) => void;
  setTranslateLang: (lang: string) => void;
  setSpeaker: (speaker: string) => void;
  
  speakers: { label: string; value: string }[];
  fetchSpeakers: () => Promise<void>;

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

  setFolderRef: (folder: string, ref: V2VFolderRef) => void;
  getFolderRef: (folder: string) => V2VFolderRef | undefined;
  removeFolderRef: (folder: string) => void;
  renameFolderRef: (oldFolder: string, newFolder: string) => void;

  clearJobRunState: (opts?: { keepImports?: boolean }) => void;

  setLastUrlsSignature: (sig: string | null) => void;

  reset: () => void;
}

export const useV2VStore = create<V2VState>((set, get) => {
  const saved = loadJobStateFromStorage();
  return {
    urls: saved.urls ?? "",
    translateLang: saved.translateLang ?? "None",
    speaker: saved.speaker ?? "mrbeast_lmnt",

  jobId: saved.jobId ?? null,
  progress: saved.progress ?? 0,
  error: null,
  videos: saved.videos ?? [],
  selectedVideoIndex: saved.selectedVideoIndex ?? 0,
  segments: saved.segments ?? [],
  selectedRowIndex: null,
  isProcessing: false,               // no puede estar procesando si se recargó
  regenStatus: "",
  shareUrl: saved.shareUrl ?? null,
  log: saved.log ?? "",
  importStatusByKey: saved.importStatusByKey ?? {},
  urlItems: saved.urlItems ?? [],
  folderRefs: loadFolderRefsFromStorage(),
  selectedUrlForLogs: null,
  urlLogs: saved.urlLogs ?? {},
  jobPhase: saved.jobPhase ?? "idle",
  lastUrlsSignature: saved.lastUrlsSignature ?? null,

  speakers: [],

  setUrls: (urls) => { set({ urls }); saveJobStateToStorage({ urls }); },
  setTranslateLang: (translateLang) => { set({ translateLang }); saveJobStateToStorage({ translateLang }); },
  setSpeaker: (speaker) => { set({ speaker }); saveJobStateToStorage({ speaker }); },

  fetchSpeakers: async () => {
    try {
      const list = await v2vApi.getSpeakers();
      set({ speakers: list });
    } catch {
      // log o ignorar
    }
  },

  setJobId: (jobId) => { set({ jobId }); saveJobStateToStorage({ jobId }); },
  setProgress: (progress) => { set({ progress }); saveJobStateToStorage({ progress }); },
  setError: (error) => set({ error }),

  setVideos: (videos) => { set({ videos }); saveJobStateToStorage({ videos }); },
  setSelectedVideoIndex: (selectedVideoIndex) => { set({ selectedVideoIndex }); saveJobStateToStorage({ selectedVideoIndex }); },
  setSegments: (segments) =>
    set((state) => {
      const next = typeof segments === "function" ? (segments as (prev: Segment[]) => Segment[])(state.segments) : segments;
      saveJobStateToStorage({ segments: next });
      return { segments: next };
    }),
  setSelectedRowIndex: (selectedRowIndex) => set({ selectedRowIndex }),

  setIsProcessing: (isProcessing) => set({ isProcessing }),
  setRegenStatus: (regenStatus) => set({ regenStatus }),
  setShareUrl: (shareUrl) => { set({ shareUrl }); saveJobStateToStorage({ shareUrl }); },
  setLog: (log) => { set({ log }); saveJobStateToStorage({ log }); },
  setImportStatus: (key, status) =>
    set((state) => {
      const next = { ...state.importStatusByKey, [key]: status };
      saveJobStateToStorage({ importStatusByKey: next });
      return { importStatusByKey: next };
    }),
  setUrlItems: (urlItems) => { set({ urlItems }); saveJobStateToStorage({ urlItems }); },
  setSelectedUrlForLogs: (selectedUrlForLogs) => set({ selectedUrlForLogs }),
  appendUrlLog: (url, line) =>
    set((state) => {
      const prev = state.urlLogs[url] || "";
      const next = prev ? `${prev}\n${line}` : line;
      const updated = { ...state.urlLogs, [url]: next };
      saveJobStateToStorage({ urlLogs: updated });
      return { urlLogs: updated };
    }),
  setJobPhase: (jobPhase) => { set({ jobPhase }); saveJobStateToStorage({ jobPhase }); },
  setFolderRef: (folder: string, ref: V2VFolderRef) =>
    set((state) => {
      const folderRefs = { ...state.folderRefs, [folder]: ref };
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
      next[newFolder] = next[oldFolder];
      delete next[oldFolder];
      saveFolderRefsToStorage(next);
      return { folderRefs: next };
    }),

  clearJobRunState: (opts) =>
    set((state) => {
      const keepImports = opts?.keepImports ?? false;
      localStorage.removeItem(JOB_STATE_STORAGE_KEY);
      return {
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
        importStatusByKey: keepImports ? state.importStatusByKey : {},
        urlItems: [],
        selectedUrlForLogs: null,
        urlLogs: {},
        jobPhase: "idle",
        folderRefs: state.folderRefs,
      };
    }),

  setLastUrlsSignature: (lastUrlsSignature) => { set({ lastUrlsSignature }); saveJobStateToStorage({ lastUrlsSignature }); },

  reset: () => {
    saveFolderRefsToStorage({});
    localStorage.removeItem(JOB_STATE_STORAGE_KEY);
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
    });
  },
  };
});

