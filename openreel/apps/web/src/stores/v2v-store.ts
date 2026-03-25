import { create } from "zustand";
import { v2vApi, type Segment, type VideoResult, type JobUrlItem, type AudioSegmentItem } from "../lib/v2v-api";
import { useProjectStore } from "./project-store";
import { createEmptyProject } from "./project";
import { importMultipleMediaIntoProject } from "../utils/import-media-into-project";
import { toSafeToken, sanitizeFolderName, shortProjectToken, importKeyFor } from "../utils/v2v-utils";
import {
  addClipToDetachedProject,
  addTrackToDetachedProject,
  renameTrackInProject,
} from "../utils/detached-project-actions";
import { autoSaveManager } from "../services/auto-save";

const FOLDER_REFS_STORAGE_KEY = "openreel.v2v.folderRefs";
const JOB_STATE_STORAGE_KEY = "openreel.v2v.jobState";

let pollingTimer: ReturnType<typeof setInterval> | null = null;
let isImportingBusy = false;

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

  clearJobRunState: (opts?: { keepImports?: boolean; keepItems?: boolean }) => void;

  setLastUrlsSignature: (sig: string | null) => void;

  startPolling: (jobId: string) => void;
  stopPolling: () => void;

  reset: () => void;
}

const POLL_INTERVAL = 1500;

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

      pollingTimer = setInterval(async () => {
        const state = get();
        const { jobId } = state;
        if (!jobId || !state.isProcessing) {
          if (pollingTimer) clearInterval(pollingTimer);
          return;
        }

        try {
          const s = await v2vApi.getJobStatus(jobId);
          set({ progress: s.progress * 100, jobPhase: s.status });
          saveJobStateToStorage({ progress: s.progress * 100, jobPhase: s.status });

          const jobLog = await v2vApi.getJobLog(jobId);
          if (jobLog && jobLog.length > state.log.length) {
            set({ log: jobLog });
            saveJobStateToStorage({ log: jobLog });
          }

          const items = await v2vApi.getJobItems(jobId);
          if (items.length) {
            set((state) => {
              // Merge items: overwriting existing ones for THIS jobId, keeping others.
              // Note: current implementation of JobUrlItem doesn't have jobId. 
              // We'll match by index/url but actually, if we start a new job, 
              // the indices might overlap. 
              // Simple approach: if jobId is different, append. 
              // If jobId is same, refresh.
              const otherItems = state.urlItems.filter(it => (it as any).jobId && (it as any).jobId !== jobId);
              const jobItems = items.map(it => ({ ...it, jobId }));
              const nextItems = [...otherItems, ...jobItems];
              saveJobStateToStorage({ urlItems: nextItems });
              return { urlItems: nextItems };
            });
          }

          try {
            const partial = await v2vApi.getJobResult(jobId);
            if (partial.videos?.length) {
              set((state) => {
                const otherVideos = state.videos.filter(v => (v as any).jobId && (v as any).jobId !== jobId);
                const jobVideos = partial.videos.map(v => ({ ...v, jobId }));
                const nextVideos = [...otherVideos, ...jobVideos];
                saveJobStateToStorage({ videos: nextVideos });
                if (jobVideos[state.selectedVideoIndex]) {
                  return { videos: nextVideos, segments: jobVideos[state.selectedVideoIndex].segments };
                }
                return { videos: nextVideos };
              });
            }
          } catch { /* ignore */ }

          if (s.status === "done" || s.status === "error") {
            const currentIsImporting = isImportingBusy;
            if (!currentIsImporting) {
               // Re-check pending imports one last time before stopping
               const stillPending = get().videos.filter(v => !get().importStatusByKey[importKeyFor(v.url, v.index)]);
               if (stillPending.length === 0) {
                 get().stopPolling();
                 if (s.status === "error") set({ isProcessing: false });
               }
            }
          }

          if (!isImportingBusy) {
            const currentVideos = get().videos;
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
                    // Deduplicar por el campo 'seg' para evitar duplicados en el timeline
                    audioSegs = audioSegs.filter((s, i, a) => a.findIndex(t => t.seg === s.seg) === i);
                  } catch {
                    get().setImportStatus(key, "error");
                    continue;
                  }
                  if (!audioSegs.length) {
                    set((st) => {
                      const next = { ...st.importStatusByKey };
                      delete next[key];
                      return { importStatusByKey: next };
                    });
                    continue;
                  }

                  const folder = sanitizeFolderName(v.output_name || `video_${v.index}`);
                  const urlForLog = v.url || "";
                  const pos = get().urlItems.findIndex(it => it.url === v.url && it.index === v.index);
                  const seq = pos >= 0 ? pos + 1 : v.index + 1;
                  const projectTitle = `${seq}. TTS ${shortProjectToken(v.output_name || folder)}`;

                  let workingProject = createEmptyProject(projectTitle, {
                    width: baseProjectSettings.width,
                    height: baseProjectSettings.height,
                    frameRate: baseProjectSettings.frameRate,
                  });

                  const videoMediaName = `${folder}/video.mp4`;
                  const downloadTasks = [
                    v2vApi.fetchOutputVideoBlob(jobId, v.index).then(blob => ({ type: 'video' as const, blob, name: videoMediaName })),
                    ...audioSegs.map(seg => {
                      const speakerToken = toSafeToken(seg.speaker || "speaker");
                      const wavName = `${folder}/tts_${speakerToken}_${String(seg.seg).padStart(4, "0")}.wav`;
                      return v2vApi.fetchAudioSegmentBlob(jobId, v.index, seg.seg).then(blob => ({ type: 'audio' as const, blob, name: wavName }));
                    })
                  ];

                  const downloaded = await Promise.all(downloadTasks);
                  const files = downloaded.map(d => new File([d.blob], d.name, { type: d.type === 'video' ? 'video/mp4' : 'audio/wav' }));

                  const batchRes = await importMultipleMediaIntoProject(workingProject, files, { quick: true });
                  if (batchRes.success && batchRes.project) {
                    workingProject = batchRes.project;
                    const vMedia = workingProject.mediaLibrary.items.find(m => m.name === videoMediaName);
                    if (vMedia) {
                      const rv = (await addTrackToDetachedProject(workingProject, "video")) as any;
                      workingProject = rv.project!;
                      const vtId = workingProject.timeline.tracks.find(t => t.type === 'video' && (rv.trackId ? t.id === rv.trackId : true))?.id;
                      if (vtId) {
                        workingProject = renameTrackInProject(workingProject, vtId, `V2V · ${folder}`);
                        const cv = (await addClipToDetachedProject(workingProject, vtId, vMedia.id, 0)) as any;
                        workingProject = cv.project!;
                      }

                      const bySpeaker: Record<string, AudioSegmentItem[]> = {};
                      for (const seg of audioSegs) {
                        const spk = (seg.speaker || "").trim();
                        const k = spk || `Speaker_${seg.seg}`;
                        (bySpeaker[k] ||= []).push(seg);
                      }

                      for (const sKey of Object.keys(bySpeaker)) {
                        const segs = bySpeaker[sKey].sort((a,b) => a.seg - b.seg);
                        const ra = (await addTrackToDetachedProject(workingProject, "audio")) as any;
                        workingProject = ra.project!;
                        const atId = workingProject.timeline.tracks.find(t => t.type === 'audio' && (ra.trackId ? t.id === ra.trackId : true))?.id;
                        if (atId) {
                          workingProject = renameTrackInProject(workingProject, atId, sKey);
                          for (const seg of segs) {
                            const wName = `${folder}/tts_${toSafeToken(seg.speaker || "speaker")}_${String(seg.seg).padStart(4, "0")}.wav`;
                            const wm = workingProject.mediaLibrary.items.find(m => m.name === wName);
                            if (wm) {
                              const cw = (await addClipToDetachedProject(workingProject, atId, wm.id, seg.start)) as any;
                              workingProject = cw.project!;
                            }
                          }
                        }
                      }
                    }

                    await autoSaveManager.forceSave(workingProject);
                    get().setFolderRef(folder, { jobId: state.jobId!, videoIndex: v.index });
                    get().setImportStatus(key, "done");
                    if (urlForLog) get().appendUrlLog(urlForLog, `✅ Importación completada en segundo plano.`);
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
      }, POLL_INTERVAL);
    },

    stopPolling: () => {
      if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
      }
      set({ isProcessing: false });
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

