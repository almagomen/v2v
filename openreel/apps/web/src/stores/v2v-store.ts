import { create } from "zustand";
import { v2vApi, type Segment, type VideoResult, type JobUrlItem, type AudioSegmentItem } from "../lib/v2v-api";
import { useProjectStore } from "./project-store";
import { createEmptyProject } from "./project";
import { importMultipleMediaIntoProject } from "../utils/import-media-into-project";
import {
  folderNameFromTitle,
  importKeyFor,
  segmentLogicalName,
  findSegmentMediaInLibrary,
} from "../utils/v2v-utils";
import { toast } from "./notification-store";
import {
  addClipToDetachedProject,
  addTrackAndGetId,
  renameTrackInProject,
  muteTrackInProject,
} from "../utils/detached-project-actions";
import { autoSaveManager } from "../services/auto-save";
import {
  type V2VSegmentInfo,
  type V2VFolderData,
  generateFolderId,
  createSegmentInfo,
} from "../utils/v2v-segment-ids";
import { getMediaBridge, initializeMediaBridge } from "../bridges/media-bridge";

const FOLDER_REFS_STORAGE_KEY = "openreel.v2v.folderRefs";
const JOB_STATE_STORAGE_KEY = "openreel.v2v.jobState";

const POLL_INTERVAL_FAST = 2000;
const POLL_INTERVAL_SLOW = 8000;

let pollingTimer: ReturnType<typeof setInterval> | null = null;
let isImportingBusy = false;
let isFetchingSpeakers = false;
let currentPollPhase: "fast" | "slow" = "fast";

export type V2VFolderRef = { 
  jobId: string; 
  videoIndex: number; 
  outputName?: string; 
  nativeFiles?: string[];
  segments?: Record<string, V2VSegmentInfo>;
};

type SerializedFolderData = Omit<V2VFolderData, "segments"> & { segments: Record<string, V2VSegmentInfo> };

function loadFolderRefsFromStorage(): Record<string, SerializedFolderData> {
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

function saveFolderRefsToStorage(refs: Record<string, SerializedFolderData>): void {
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
  folderRefs: Record<string, SerializedFolderData>;
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
  getFolderRef: (folder: string) => SerializedFolderData | undefined;
  removeFolderRef: (folder: string) => void;
  renameFolderRef: (oldFolder: string, newFolder: string) => void;

  setSegmentInfo: (folder: string, segment: V2VSegmentInfo) => void;
  getSegmentInfo: (folder: string, segmentId: string) => V2VSegmentInfo | undefined;
  getSegmentByMediaId: (folder: string, mediaId: string) => V2VSegmentInfo | undefined;
  updateSegmentText: (folder: string, segmentId: string, text: string) => void;
  updateSegmentSpeaker: (folder: string, segmentId: string, speaker: string | null) => void;
  updateSegmentSpeed: (folder: string, segmentId: string, speed: number | null) => void;

  clearJobRunState: (opts?: { keepImports?: boolean; keepItems?: boolean }) => void;

  setLastUrlsSignature: (sig: string | null) => void;

  startPolling: (jobId: string) => void;
  stopPolling: () => void;

  syncFolderAssets: (jobId: string, videoIndex: number, folder: string) => Promise<void>;
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
    isProcessing: false,
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
      if (get().speakers.length > 0 || isFetchingSpeakers) return;
      isFetchingSpeakers = true;
      try {
        const list = await v2vApi.getSpeakers();
        set({ speakers: list });
      } catch {
        // ignore
      } finally {
        isFetchingSpeakers = false;
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

    clearJobRunState: (opts) =>
      set((state) => {
        const keepImports = opts?.keepImports ?? false;
        const keepItems = opts?.keepItems ?? false;
        if (!keepItems) localStorage.removeItem(JOB_STATE_STORAGE_KEY);
        return {
          jobId: null,
          progress: 0,
          error: null,
          videos: keepItems ? state.videos : [],
          selectedVideoIndex: 0,
          segments: keepItems ? state.segments : [],
          selectedRowIndex: null,
          isProcessing: false,
          regenStatus: "",
          shareUrl: null,
          log: "",
          importStatusByKey: keepImports ? state.importStatusByKey : {},
          urlItems: keepItems ? state.urlItems : [],
          selectedUrlForLogs: null,
          urlLogs: keepItems ? state.urlLogs : {},
          jobPhase: "idle",
          folderRefs: state.folderRefs,
          lastUrlsSignature: state.lastUrlsSignature,
        };
      }),

    setLastUrlsSignature: (lastUrlsSignature) => { set({ lastUrlsSignature }); saveJobStateToStorage({ lastUrlsSignature }); },

    startPolling: (jobId) => {
      if (pollingTimer) clearInterval(pollingTimer);
      set({ jobId, isProcessing: true });
      saveJobStateToStorage({ jobId });
      currentPollPhase = "fast";

      const scheduleNext = () => {
        if (pollingTimer) clearInterval(pollingTimer);
        const interval = currentPollPhase === "fast" ? POLL_INTERVAL_FAST : POLL_INTERVAL_SLOW;
        pollingTimer = setInterval(pollOnce, interval);
      };

      const pollOnce = async () => {
        const state = get();
        if (!jobId || !state.isProcessing) {
          if (pollingTimer) {
            clearInterval(pollingTimer);
            pollingTimer = null;
          }
          return;
        }

        try {
          const pollResult = await v2vApi.poll(jobId);
          const { status: s, log: jobLog, items, result: partial } = pollResult;

          set({ progress: s.progress * 100, jobPhase: s.status });
          saveJobStateToStorage({ progress: s.progress * 100, jobPhase: s.status });

          if (jobLog && jobLog.length > state.log.length) {
            set({ log: jobLog });
            saveJobStateToStorage({ log: jobLog });
          }

          if (items && items.length) {
            set((st) => {
              const otherItems = st.urlItems.filter(it => (it as any).jobId && (it as any).jobId !== jobId);
              const jobItems = items.map(it => ({ ...it, jobId }));
              const nextItems = [...otherItems, ...jobItems];
              saveJobStateToStorage({ urlItems: nextItems });
              return { urlItems: nextItems };
            });
          }

          if (partial?.videos?.length) {
            set((st) => {
              const otherVideos = st.videos.filter(v => (v as any).jobId && (v as any).jobId !== jobId);
              const jobVideos = partial.videos.map(v => ({ ...v, jobId }));
              const nextVideos = [...otherVideos, ...jobVideos];
              saveJobStateToStorage({ videos: nextVideos });
              return { videos: nextVideos };
            });
          }

          // Adaptive polling: switch to slow when waiting for import
          const currentVideos = partial?.videos || [];
          const hasPendingImports = currentVideos.some(
            (v) => !get().importStatusByKey[importKeyFor(v.url, v.index)],
          );

          if (hasPendingImports && !isImportingBusy) {
            currentPollPhase = "slow";
            scheduleNext();
          } else if (currentPollPhase === "slow" && !hasPendingImports) {
            currentPollPhase = "fast";
            scheduleNext();
          }

          if (s.status === "done" || s.status === "error" || s.status === "interrupted") {
            if (s.status === "interrupted") {
              console.warn(`[V2V] Job ${jobId} fue interrumpido por reinicio del servidor`);
              get().stopPolling();
              set({
                isProcessing: false,
                error: "El servidor se reinició durante el procesamiento. Revisa los jobs completados o reinicia.",
              });
            } else if (!isImportingBusy) {
               const stillPending = get().videos.filter(v => !get().importStatusByKey[importKeyFor(v.url, v.index)]);
               if (stillPending.length === 0) {
                 get().stopPolling();
                 if (s.status === "error") set({ isProcessing: false });
               }
            }
          }

          if (!isImportingBusy) {
            const pendingVideos = currentVideos.filter(
              (v) => !get().importStatusByKey[importKeyFor(v.url, v.index)],
            );

            if (pendingVideos.length > 0) {
              isImportingBusy = true;
              try {
                const baseProjectSettings = useProjectStore.getState().project.settings;
                for (const v of pendingVideos) {
                  const key = importKeyFor(v.url, v.index);
                  if (get().importStatusByKey[key]) continue;

                  set((st) => ({
                    importStatusByKey: { ...st.importStatusByKey, [key]: "in_progress" }
                  }));

                  let audioSegs: AudioSegmentItem[] = [];
                  try {
                    audioSegs = await v2vApi.getAudioSegments(jobId, v.index);
                    audioSegs = audioSegs.filter((as, i, a) => a.findIndex(t => t.seg === as.seg) === i);
                  } catch {
                    get().setImportStatus(key, "error");
                    continue;
                  }

                  // folder: nombre de carpeta SIN hashtags (para paths de sistema)
                  // v.output_name: título completo CON hashtags (para el render final en Colab)
                  const folder = folderNameFromTitle(v.output_name || `video_${v.index}`);
                  const urlForLog = v.url || "";
                  let workingProject = createEmptyProject(folder, {
                    width: baseProjectSettings.width,
                    height: baseProjectSettings.height,
                    frameRate: baseProjectSettings.frameRate,
                  });

                  interface V2VAssetDef {
                    id: string;
                    serverFn: string;
                    logicalName: string;
                    type: 'video' | 'audio';
                    toTimeline: boolean;
                    trackPrefix?: string;
                    muted?: boolean;
                    enabled: boolean;
                  }

                  const assets: V2VAssetDef[] = [
                    { 
                      id: 'video_only', 
                      serverFn: v.video_only_path?.split(/[\\/]/).pop() || "", 
                      logicalName: `${folder}/${v.video_only_path?.split(/[\\/]/).pop() || "video_only.mp4"}`, 
                      type: 'video', 
                      toTimeline: true, 
                      trackPrefix: 'Video',
                      enabled: !!v.video_only_path 
                    },
                    { 
                      id: 'instrumental', 
                      serverFn: v.instrumental_path?.split(/[\\/]/).pop() || "no_vocals.wav", 
                      logicalName: `${folder}/no_vocals.wav`, 
                      type: 'audio', 
                      toTimeline: true, 
                      trackPrefix: 'INSTRUMENTAL',
                      enabled: !!v.instrumental_path 
                    },
                    { 
                      id: 'merged_video', 
                      serverFn: v.video_path?.split(/[\\/]/).pop() || "", 
                      logicalName: `${folder}/${v.video_path?.split(/[\\/]/).pop() || "merged.mp4"}`, 
                      type: 'video', 
                      toTimeline: false, 
                      enabled: !!v.video_path 
                    },
                    { 
                      id: 'original_audio', 
                      serverFn: v.original_audio_path?.split(/[\\/]/).pop() || "", 
                      logicalName: `${folder}/${v.original_audio_path?.split(/[\\/]/).pop() || "original_audio.webm"}`, 
                      type: 'audio', 
                      toTimeline: false, 
                      enabled: !!v.original_audio_path 
                    },
                    { 
                      id: 'vocals_original', 
                      serverFn: v.vocals_path?.split(/[\\/]/).pop() || "vocals.wav", 
                      logicalName: `${folder}/vocals.wav`, 
                      type: 'audio', 
                      toTimeline: false, 
                      enabled: !!v.vocals_path 
                    }
                  ];

                  const fetchAssetBlob = async (asset: V2VAssetDef) => {
                    if (!asset.enabled) return null;
                    try {
                      const blob = await v2vApi.fetchFileBlob(jobId, v.index, asset.serverFn);
                      return { asset, blob };
                    } catch (e) {
                      console.warn(`[V2V] Asset opcional no disponible: ${asset.serverFn}`, e);
                      return null;
                    }
                  };

                  const assetTasks = assets.map(fetchAssetBlob);
                  const segmentTasks = audioSegs.map((seg) => {
                    const logicalName = segmentLogicalName(folder, seg);
                    return v2vApi
                      .fetchAudioSegmentBlob(jobId, v.index, seg.seg)
                      .then((blob) => ({ isSegment: true as const, seg, logicalName, blob }))
                      .catch(() => null);
                  });

                  const [downloadedAssetsRaw, downloadedSegsRaw] = await Promise.all([
                    Promise.all(assetTasks),
                    Promise.all(segmentTasks)
                  ]);

                  const downloadedAssets = downloadedAssetsRaw.filter((d): d is { asset: V2VAssetDef, blob: Blob } => d !== null);
                  const downloadedSegs = downloadedSegsRaw.filter((d): d is { isSegment: true, seg: AudioSegmentItem, logicalName: string, blob: Blob } => d !== null);

                  if (audioSegs.length > 0 && downloadedSegs.length === 0) {
                    console.warn(
                      `[V2V] ${audioSegs.length} segmentos listados pero ningún WAV descargado para ${folder}`,
                    );
                    get().setImportStatus(key, "error");
                    if (urlForLog) {
                      get().appendUrlLog(
                        urlForLog,
                        "❌ No se pudieron descargar los audios TTS; reintenta o usa Re-importar.",
                      );
                    }
                    continue;
                  }

                  const filesToImport = [
                    ...downloadedAssets.map(d => new File([d.blob], d.asset.logicalName, { type: d.asset.type === 'video' ? 'video/mp4' : 'audio/wav' })),
                    ...downloadedSegs.map(d => new File([d.blob], d.logicalName, { type: 'audio/wav' }))
                  ];

                  const batchRes = await importMultipleMediaIntoProject(workingProject, filesToImport, { quick: true });
                  if (batchRes.success && batchRes.project) {
                    workingProject = batchRes.project;

                    const vMedia = workingProject.mediaLibrary.items.find(m => m.name === `${folder}/${v.video_only_path?.split(/[\\/]/).pop() || "video_only.mp4"}`);
                    if (vMedia?.metadata.width && vMedia?.metadata.height) {
                      workingProject = {
                        ...workingProject,
                        settings: { ...workingProject.settings, width: vMedia.metadata.width, height: vMedia.metadata.height },
                      };
                    }

                    for (const { asset } of downloadedAssets) {
                      if (!asset.toTimeline) continue;
                      const media = workingProject.mediaLibrary.items.find(m => m.name === asset.logicalName);
                      if (!media) continue;

                      const { project: p1, trackId } = await addTrackAndGetId(workingProject, asset.type);
                      workingProject = p1;
                      if (!trackId) continue;
                      workingProject = renameTrackInProject(workingProject, trackId, asset.trackPrefix ? asset.trackPrefix : asset.id);
                      if (asset.muted) workingProject = muteTrackInProject(workingProject, trackId, true);
                      const clipRes = (await addClipToDetachedProject(workingProject, trackId, media.id, 0)) as any;
                      workingProject = clipRes.project!;
                    }

                    const bySpeaker: Record<string, typeof downloadedSegs> = {};
                    for (const d of downloadedSegs) {
                      const spk = (d.seg.speaker || "").trim() || `Speaker_${d.seg.seg}`;
                      (bySpeaker[spk] ||= []).push(d);
                    }

                    for (const sKey of Object.keys(bySpeaker)) {
                      const segs = bySpeaker[sKey].sort((a,b) => a.seg.seg - b.seg.seg);
                      const { project: p2, trackId } = await addTrackAndGetId(workingProject, "audio");
                      workingProject = p2;
                      if (!trackId) continue;

                      workingProject = renameTrackInProject(workingProject, trackId, sKey);
                      for (const d of segs) {
                        const media = findSegmentMediaInLibrary(
                          workingProject.mediaLibrary.items,
                          folder,
                          d.seg,
                        );
                        if (!media) {
                          console.warn(
                            `[V2V] Segmento ${d.seg.seg} no montado: logicalName=${d.logicalName}, filename=${d.seg.filename}`,
                          );
                          continue;
                        }
                        const clipRes = (await addClipToDetachedProject(
                          workingProject,
                          trackId,
                          media.id,
                          d.seg.start,
                        )) as { project?: typeof workingProject };
                        if (clipRes.project) workingProject = clipRes.project;
                      }
                    }

                    await autoSaveManager.forceSave(workingProject);
                    
                    const audioSegmentsImported = workingProject.mediaLibrary.items.filter(
                      m => m.type === "audio" && m.name.startsWith(`${folder}/tts_`) && !m.waveformData
                    );
                    
                    if (audioSegmentsImported.length > 0) {
                      const mediaBridge = getMediaBridge();
                      if (!mediaBridge.isInitialized()) {
                        await initializeMediaBridge();
                      }
                      for (const mediaItem of audioSegmentsImported) {
                        if (!mediaItem.blob) continue;
                        try {
                          const waveformData = await mediaBridge.generateWaveform(mediaItem.blob, mediaItem.id);
                          const idx = workingProject.mediaLibrary.items.findIndex(m => m.id === mediaItem.id);
                          if (idx >= 0) {
                            workingProject.mediaLibrary.items[idx] = {
                              ...workingProject.mediaLibrary.items[idx],
                              waveformData: waveformData?.peaks || null,
                            };
                          }
                        } catch (e) {
                          console.warn(`[V2V] Error generating waveform for ${mediaItem.name}:`, e);
                        }
                      }
                      await autoSaveManager.forceSave(workingProject);
                    }
                    
                    const nativeFiles = filesToImport.map(f => f.name.split("/").pop() || "");
                    
                    get().setFolderRef(folder, { jobId: state.jobId!, videoIndex: v.index, outputName: v.output_name, nativeFiles });
                    
                    const segsWithMediaInfo = downloadedSegs.map((d) => {
                      const media = findSegmentMediaInLibrary(
                        workingProject.mediaLibrary.items,
                        folder,
                        d.seg,
                      );
                      const videoSegment = v.segments.find((s) => s.seg === d.seg.seg);
                      return {
                        seg: d.seg,
                        mediaId: media?.id || "",
                        logicalName: d.logicalName,
                        text: videoSegment?.text || "",
                        speaker: videoSegment?.speaker || d.seg.speaker,
                      };
                    });
                    
                    for (const segInfo of segsWithMediaInfo) {
                      if (segInfo.mediaId) {
                        const segmentData = createSegmentInfo({
                          mediaId: segInfo.mediaId,
                          jobId: state.jobId!,
                          videoIndex: v.index,
                          segIdx: segInfo.seg.seg,
                          folder: folder,
                          originalText: segInfo.text,
                          speaker: segInfo.speaker,
                        });
                        get().setSegmentInfo(folder, segmentData);
                      }
                    }
                    
                    get().setImportStatus(key, "done");
                    if (urlForLog) get().appendUrlLog(urlForLog, `✅ Importación completada por activos.`);

                    const activeProject = useProjectStore.getState().project;
                    if (activeProject.name === folder) {
                      useProjectStore.getState().loadProject(workingProject);
                      toast.success(
                        "Timeline V2V actualizado",
                        "Video, instrumental y voces TTS montados en el timeline.",
                      );
                    } else {
                      toast.info(
                        "Importación guardada en autosave",
                        `Abre el proyecto "${folder}" o recupera el autosave más reciente para ver el timeline completo.`,
                      );
                    }
                  }
                }
              } catch (err) {
                console.error("V2V Background import error:", err);
              } finally {
                isImportingBusy = false;
              }
            }
          }
        } catch (err) {
          console.error("V2V Polling error:", err);
        }
      };

      scheduleNext();
    },

    stopPolling: () => {
      if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
      }
      currentPollPhase = "fast";
      set({ isProcessing: false });
    },

    syncFolderAssets: async (jobId, videoIndex, folder) => {
      try {
        const assets = await v2vApi.getManifest(jobId, videoIndex);
        const filenames = Object.entries(assets)
          .flatMap(([k, v]) => {
            if (typeof v === "string") return [v];
            // Extraer las rutas individuales alojadas dentro del objeto literal "segments"
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

    reset: () => {
      get().stopPolling();
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
        lastUrlsSignature: null,
      });
    },
  };
});
