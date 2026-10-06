import { create } from "zustand";

export interface CatboxVideoResult {
  filename: string;
  url: string;
  status: string;
}

export type ExportStatus = "idle" | "uploading" | "rendering" | "done" | "error";

const COLAB_EXPORT_STORAGE_KEY = "openreel.colabExport.settings";

interface PersistedExportSettings {
  isBatch?: boolean;
  uploadToCatbox?: boolean;
  deselectedProjectIds?: string[];
  geminiModel?: string;
  customGeminiModel?: string;
}

function loadPersistedSettings(): PersistedExportSettings {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem(COLAB_EXPORT_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function savePersistedSettings(settings: Partial<PersistedExportSettings>) {
  if (typeof window === "undefined") return;
  try {
    const current = loadPersistedSettings();
    localStorage.setItem(
      COLAB_EXPORT_STORAGE_KEY,
      JSON.stringify({ ...current, ...settings }),
    );
  } catch {
    // ignore storage quota errors
  }
}

export interface ColabExportState {
  isBatch: boolean;
  uploadToCatbox: boolean;
  deselectedProjectIds: string[];
  geminiModel: string;
  customGeminiModel: string;

  status: ExportStatus;
  statusMsg: string;
  errorMsg: string;

  progress: number;
  currentStep: string;
  currentVideoName: string;
  currentIdx: number;
  totalVideos: number;

  catboxUrl: string | null;
  catboxVideos: CatboxVideoResult[];

  setIsBatch: (isBatch: boolean) => void;
  setUploadToCatbox: (upload: boolean) => void;
  toggleProjectId: (id: string) => void;
  selectAllProjects: () => void;
  deselectAllProjects: (allIds: string[]) => void;
  setGeminiModel: (model: string) => void;
  setCustomGeminiModel: (customModel: string) => void;
  getActiveGeminiModel: () => string;

  setStatus: (status: ExportStatus) => void;
  setStatusMsg: (msg: string) => void;
  setErrorMsg: (msg: string) => void;
  setProgressData: (data: {
    progress?: number;
    currentStep?: string;
    currentVideoName?: string;
    currentIdx?: number;
    totalVideos?: number;
    statusMsg?: string;
  }) => void;
  setCatboxUrl: (url: string | null) => void;
  setCatboxVideos: (videos: CatboxVideoResult[]) => void;
  resetStatus: () => void;
}

const initialSettings = loadPersistedSettings();

export const useColabExportStore = create<ColabExportState>((set, get) => ({
  isBatch: initialSettings.isBatch ?? false,
  uploadToCatbox: initialSettings.uploadToCatbox ?? false,
  deselectedProjectIds: initialSettings.deselectedProjectIds ?? [],
  geminiModel: initialSettings.geminiModel ?? "gemini-flash-lite-latest",
  customGeminiModel: initialSettings.customGeminiModel ?? "",

  status: "idle",
  statusMsg: "",
  errorMsg: "",
  progress: 0,
  currentStep: "",
  currentVideoName: "",
  currentIdx: 0,
  totalVideos: 0,
  catboxUrl: null,
  catboxVideos: [],

  setIsBatch: (isBatch) => {
    savePersistedSettings({ isBatch });
    set({ isBatch });
  },

  setUploadToCatbox: (uploadToCatbox) => {
    savePersistedSettings({ uploadToCatbox });
    set({ uploadToCatbox, catboxUrl: null, catboxVideos: [] });
  },

  toggleProjectId: (id) =>
    set((state) => {
      const exists = state.deselectedProjectIds.includes(id);
      const updated = exists
        ? state.deselectedProjectIds.filter((x) => x !== id)
        : [...state.deselectedProjectIds, id];
      savePersistedSettings({ deselectedProjectIds: updated });
      return { deselectedProjectIds: updated };
    }),

  selectAllProjects: () => {
    savePersistedSettings({ deselectedProjectIds: [] });
    set({ deselectedProjectIds: [] });
  },

  deselectAllProjects: (allIds) => {
    savePersistedSettings({ deselectedProjectIds: allIds });
    set({ deselectedProjectIds: allIds });
  },

  setGeminiModel: (geminiModel) => {
    savePersistedSettings({ geminiModel });
    set({ geminiModel });
  },

  setCustomGeminiModel: (customGeminiModel) => {
    savePersistedSettings({ customGeminiModel });
    set({ customGeminiModel });
  },

  getActiveGeminiModel: () => {
    const { geminiModel, customGeminiModel } = get();
    if (geminiModel === "custom" && customGeminiModel.trim()) {
      return customGeminiModel.trim();
    }
    return geminiModel || "gemini-flash-lite-latest";
  },


  setStatus: (status) => set({ status }),
  setStatusMsg: (statusMsg) => set({ statusMsg }),
  setErrorMsg: (errorMsg) => set({ errorMsg }),
  setProgressData: (data) =>
    set((state) => ({
      ...state,
      progress: data.progress !== undefined ? data.progress : state.progress,
      currentStep: data.currentStep !== undefined ? data.currentStep : state.currentStep,
      currentVideoName: data.currentVideoName !== undefined ? data.currentVideoName : state.currentVideoName,
      currentIdx: data.currentIdx !== undefined ? data.currentIdx : state.currentIdx,
      totalVideos: data.totalVideos !== undefined ? data.totalVideos : state.totalVideos,
      statusMsg: data.statusMsg !== undefined ? data.statusMsg : (data.currentStep || state.statusMsg),
    })),
  setCatboxUrl: (catboxUrl) => set({ catboxUrl }),
  setCatboxVideos: (catboxVideos) => set({ catboxVideos }),
  resetStatus: () =>
    set({
      status: "idle",
      statusMsg: "",
      errorMsg: "",
      progress: 0,
      currentStep: "",
      currentVideoName: "",
      currentIdx: 0,
      totalVideos: 0,
      catboxUrl: null,
      catboxVideos: [],
    }),
}));
