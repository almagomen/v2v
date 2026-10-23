import type { StateCreator } from "zustand";
import { v4 as uuidv4 } from "uuid";
import type { MediaItem } from "@openreel/core";
import {
  v2vApi,
  type VideoResult,
  type JobUrlItem,
  type AudioSegmentItem,
} from "../api/v2v-api";
import { useProjectStore } from "@/stores/project-store";
import { createEmptyProject } from "@/stores/project";
import { importMultipleMediaIntoProject } from "@/utils/import-media-into-project";
import {
  folderNameFromTitle,
  importKeyFor,
  segmentLogicalName,
  findSegmentMediaInLibrary,
  toSafeToken,
  getWavBlobDuration,
} from "../utils/v2v-utils";
import { toast } from "@/stores/notification-store";
import {
  addClipToDetachedProject,
  addMultipleClipsToDetachedProject,
  addTrackAndGetId,
  renameTrackInProject,
  muteTrackInProject,
} from "../utils/v2v-detached-actions";
import { autoSaveManager } from "@/services/auto-save";
import { saveMediaBlob } from "@/services/media-storage";
import {
  generateFolderId,
  createSegmentInfo,
} from "../utils/v2v-segment-ids";
import { getMediaBridge, initializeMediaBridge } from "@/bridges/media-bridge";
import type { V2VState, JobSlice, SerializedFolderData } from "./v2v-types";
import {
  saveJobStateToStorage,
  loadJobStateForProject,
  saveJobStateForProject,
  clearJobStateForProject,
  loadV2VPreferences,
  saveV2VPreferences,
} from "./v2v-storage";
import {
  saveFolderRefsToStorage,
} from "./v2v-folders-slice";

const POLL_INTERVAL_FAST = 2000;
const POLL_INTERVAL_SLOW = 8000;

let pollingTimer: ReturnType<typeof setInterval> | null = null;
let activeWebSocket: WebSocket | null = null;
let isImportingBusy = false;
let currentPollPhase: "fast" | "slow" = "fast";

async function generateWaveformsInBackground(projectId: string, mediaItems: MediaItem[]) {
  if (!mediaItems || mediaItems.length === 0) return;
  try {
    const mediaBridge = getMediaBridge();
    if (!mediaBridge.isInitialized()) {
      await initializeMediaBridge();
    }
    const BATCH_SIZE = 4;
    for (let i = 0; i < mediaItems.length; i += BATCH_SIZE) {
      const slice = mediaItems.slice(i, i + BATCH_SIZE);
      const results = await Promise.all(
        slice.map(async (item) => {
          if (!item.blob) return null;
          try {
            const wf = await mediaBridge.generateWaveform(item.blob, item.id);
            return { id: item.id, peaks: wf?.peaks || null };
          } catch {
            return null;
          }
        })
      );

      const currentStore = useProjectStore.getState();
      if (currentStore.project && currentStore.project.id === projectId) {
        const updatedItems = currentStore.project.mediaLibrary.items.map((m) => {
          const match = results.find((r) => r && r.id === m.id);
          return match && match.peaks ? { ...m, waveformData: match.peaks } : m;
        });
        useProjectStore.setState({
          project: {
            ...currentStore.project,
            mediaLibrary: {
              ...currentStore.project.mediaLibrary,
              items: updatedItems,
            },
          },
        });
      }

      await new Promise((resolve) => setTimeout(resolve, 16));
    }

    const finalStore = useProjectStore.getState();
    if (finalStore.project && finalStore.project.id === projectId) {
      await autoSaveManager.forceSave(finalStore.project);
    }
  } catch (err) {
    console.warn("[V2V] Error generating waveforms in background:", err);
  }
}

export const createJobSlice: StateCreator<V2VState, [], [], JobSlice> = (set, get) => {
  const saveProjectPatch = (patch: Partial<any>) => {
    const pid = get().currentProjectId || useProjectStore.getState().project?.id;
    if (pid) {
      saveJobStateForProject(pid, patch);
    }
  };

  return {
    currentProjectId: null,
    urls: "",
    jobId: null,
    progress: 0,
    error: null,
    videos: [],
    selectedVideoIndex: 0,
    isProcessing: false,
    shareUrl: null,
    log: "",
    importStatusByKey: {},
    urlItems: [],
    selectedUrlForLogs: null,
    urlLogs: {},
    jobPhase: "idle",
    lastUrlsSignature: null,

    isV2VOpen: false,
    setIsV2VOpen: (isV2VOpen) => set({ isV2VOpen }),
    bulkEditorOpen: false,
    setBulkEditorOpen: (bulkEditorOpen) => set({ bulkEditorOpen }),
    timelineHeight: 320,
    setTimelineHeight: (timelineHeight) => set({ timelineHeight }),

    enableEmotions: loadV2VPreferences().enableEmotions,
    importInstrumental: loadV2VPreferences().importInstrumental,
    importOriginalAudio: loadV2VPreferences().importOriginalAudio,
    importOriginalVocals: loadV2VPreferences().importOriginalVocals,
    importOriginalSegments: loadV2VPreferences().importOriginalSegments,
    importMergedVideo: loadV2VPreferences().importMergedVideo,

    setEnableEmotions: (enableEmotions) => {
      saveV2VPreferences({ enableEmotions });
      set({ enableEmotions });
    },
    setImportInstrumental: (importInstrumental) => {
      saveV2VPreferences({ importInstrumental });
      set({ importInstrumental });
    },
    setImportOriginalAudio: (importOriginalAudio) => {
      saveV2VPreferences({ importOriginalAudio });
      set({ importOriginalAudio });
    },
    setImportOriginalVocals: (importOriginalVocals) => {
      saveV2VPreferences({ importOriginalVocals });
      set({ importOriginalVocals });
    },
    setImportOriginalSegments: (importOriginalSegments) => {
      saveV2VPreferences({ importOriginalSegments });
      set({ importOriginalSegments });
    },
    setImportMergedVideo: (importMergedVideo) => {
      saveV2VPreferences({ importMergedVideo });
      set({ importMergedVideo });
    },

    syncWithProject: (projectId: string | null) => {
      if (!projectId) {
        set({ currentProjectId: null });
        return;
      }
      if (get().currentProjectId === projectId) {
        return;
      }

      // Si hay un trabajo en progreso en la sesión actual, preservar la memoria
      if (get().isProcessing) {
        set({ currentProjectId: projectId });
        return;
      }

      // Cargar únicamente el estado guardado para este projectId exacto
      const saved = loadJobStateForProject(projectId);
      const hasSavedData = !!(
        saved.urls ||
        (saved.videos && saved.videos.length > 0) ||
        saved.jobId ||
        (saved.urlLogs && Object.keys(saved.urlLogs).length > 0)
      );

      if (hasSavedData) {
        set({
          currentProjectId: projectId,
          urls: saved.urls ?? "",
          jobId: saved.jobId ?? null,
          progress: saved.progress ?? 0,
          videos: saved.videos ?? [],
          selectedVideoIndex: saved.selectedVideoIndex ?? 0,
          segments: saved.segments ?? [],
          urlItems: saved.urlItems ?? [],
          urlLogs: saved.urlLogs ?? {},
          log: saved.log ?? "",
          jobPhase: (saved.jobPhase as any) ?? "idle",
          importStatusByKey: (saved.importStatusByKey as any) ?? {},
          shareUrl: saved.shareUrl ?? null,
          lastUrlsSignature: saved.lastUrlsSignature ?? null,
          isProcessing: false,
        });
      } else {
        // Proyecto nuevo o sin corrida de V2V: iniciar completamente limpio
        set({
          currentProjectId: projectId,
          urls: "",
          jobId: null,
          progress: 0,
          videos: [],
          selectedVideoIndex: 0,
          segments: [],
          urlItems: [],
          urlLogs: {},
          log: "",
          jobPhase: "idle",
          importStatusByKey: {},
          shareUrl: null,
          lastUrlsSignature: null,
          isProcessing: false,
        });
      }
    },

    setUrls: (urls) => {
      set({ urls });
      saveProjectPatch({ urls });
    },
    setJobId: (jobId) => {
      set({ jobId });
      saveProjectPatch({ jobId });
    },
    setProgress: (progress) => {
      set({ progress });
      saveProjectPatch({ progress });
    },
    setError: (error) => set({ error }),

    setVideos: (videos) => {
      set({ videos });
      saveProjectPatch({ videos });
    },
    setSelectedVideoIndex: (selectedVideoIndex) => {
      set({ selectedVideoIndex });
      saveProjectPatch({ selectedVideoIndex });
    },

    setIsProcessing: (isProcessing) => set({ isProcessing }),
    setShareUrl: (shareUrl) => {
      set({ shareUrl });
      saveProjectPatch({ shareUrl });
    },
    setLog: (log) => {
      set({ log });
      saveProjectPatch({ log });
    },
    setImportStatus: (key, status) =>
      set((state) => {
        const next = { ...state.importStatusByKey, [key]: status };
        saveProjectPatch({ importStatusByKey: next });
        return { importStatusByKey: next };
      }),
    setUrlItems: (urlItems) => {
      set({ urlItems });
      saveProjectPatch({ urlItems });
    },
    setSelectedUrlForLogs: (selectedUrlForLogs) => set({ selectedUrlForLogs }),
    appendUrlLog: (url, line) =>
      set((state) => {
        const prev = state.urlLogs[url] || "";
        const next = prev ? `${prev}\n${line}` : line;
        const updated = { ...state.urlLogs, [url]: next };
        saveProjectPatch({ urlLogs: updated });
        return { urlLogs: updated };
      }),
    setJobPhase: (jobPhase) => {
      set({ jobPhase });
      saveProjectPatch({ jobPhase });
    },

    clearJobRunState: (opts) =>
      set((state) => {
        const keepImports = opts?.keepImports ?? false;
        const keepItems = opts?.keepItems ?? false;
        if (!keepItems) {
          const pid = get().currentProjectId || useProjectStore.getState().project?.id;
          if (pid) clearJobStateForProject(pid);
        }
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

    setLastUrlsSignature: (lastUrlsSignature) => {
      set({ lastUrlsSignature });
      saveProjectPatch({ lastUrlsSignature });
    },

    startPolling: (jobId) => {
      if (pollingTimer) clearInterval(pollingTimer);
      if (activeWebSocket) {
        try { activeWebSocket.close(); } catch {}
        activeWebSocket = null;
      }

      set({ jobId, isProcessing: true });
      saveJobStateToStorage({ jobId });
      currentPollPhase = "fast";

      // ── Conexión WebSocket para streaming en tiempo real ──
      try {
        const wsUrl = v2vApi.getJobWebSocketUrl(jobId);
        const ws = new WebSocket(wsUrl);
        activeWebSocket = ws;

        ws.onopen = () => {
          console.log(`[V2V] ⚡ WebSocket conectado en tiempo real para job ${jobId}`);
        };

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === "log_chunk" && msg.chunk) {
              set((st) => {
                const nextLog = (st.log || "") + msg.chunk;
                saveJobStateToStorage({ log: nextLog });
                return { log: nextLog };
              });
            } else if (msg.type === "job_update" && msg.data) {
              const d = msg.data;
              const updates: Partial<any> = {};
              if (d.progress !== undefined) updates.progress = d.progress * 100;
              if (d.status) updates.jobPhase = d.status;
              if (d.url_states) {
                updates.urlItems = (d.url_states as JobUrlItem[]).map((it) => ({ ...it, jobId }));
              }
              if (d.videos) {
                updates.videos = (d.videos as VideoResult[]).map((v) => ({ ...v, jobId }));
              }
              set(updates);
              saveJobStateToStorage(updates);
            } else if (msg.type === "job_snapshot" && msg.data) {
              const snap = msg.data;
              const snapUpdates: Partial<any> = {};
              if (snap.progress !== undefined) snapUpdates.progress = snap.progress * 100;
              if (snap.status) snapUpdates.jobPhase = snap.status;
              if (snap.log) snapUpdates.log = snap.log;
              if (snap.url_states) {
                snapUpdates.urlItems = snap.url_states.map((it: any) => ({ ...it, jobId }));
              }
              if (snap.videos) {
                snapUpdates.videos = snap.videos.map((v: any) => ({ ...v, jobId }));
              }
              set(snapUpdates);
              saveJobStateToStorage(snapUpdates);
            }
          } catch {
            // Ignorar respuestas no-JSON
          }
        };

        ws.onerror = (e) => {
          console.warn("[V2V] WebSocket no disponible o error, continuando con HTTP polling:", e);
        };

        ws.onclose = () => {
          if (activeWebSocket === ws) activeWebSocket = null;
        };
      } catch (wsErr) {
        console.warn("[V2V] Excepción al conectar WebSocket, continuando con HTTP polling:", wsErr);
      }

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
          if (activeWebSocket) {
            try { activeWebSocket.close(); } catch {}
            activeWebSocket = null;
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

          const pendingVideos = currentVideos.filter(
            (v) => !get().importStatusByKey[importKeyFor(v.url, v.index)],
          );

          if (s.status === "done" || s.status === "error" || s.status === "interrupted") {
            if (s.status === "interrupted") {
              console.warn(`[V2V] Job ${jobId} fue interrumpido por reinicio del servidor`);
              get().stopPolling();
              set({
                isProcessing: false,
                error: "El servidor se reinició durante el procesamiento. Revisa los jobs completados o reinicia.",
              });
            } else if (!isImportingBusy && pendingVideos.length === 0) {
              const stillPending = get().videos.filter(v => !get().importStatusByKey[importKeyFor(v.url, v.index)]);
              if (stillPending.length === 0) {
                get().stopPolling();
                if (s.status === "error") set({ isProcessing: false });
              }
            }
          }

          if (!isImportingBusy && pendingVideos.length > 0) {
            isImportingBusy = true;
            try {
              const baseProjectSettings = useProjectStore.getState().project.settings;
              for (const v of pendingVideos) {
                const key = importKeyFor(v.url, v.index);
                if (get().importStatusByKey[key]) continue;

                set((st) => ({
                  importStatusByKey: { ...st.importStatusByKey, [key]: "in_progress" }
                }));

                const folder = folderNameFromTitle(v.output_name || `video_${v.index}`);
                const urlForLog = v.url || "";
                const importStartTime = performance.now();

                let audioSegs: AudioSegmentItem[] = [];
                try {
                  audioSegs = await v2vApi.getAudioSegments(jobId, v.index);
                  audioSegs = audioSegs.filter((as, i, a) => a.findIndex(t => t.seg === as.seg) === i);
                } catch (e) {
                  console.error(`[V2V] Error obteniendo audio segments para video ${v.index}:`, e);
                  get().setImportStatus(key, "error");
                  if (urlForLog) {
                    get().appendUrlLog(urlForLog, `❌ Error obteniendo segmentos de audio para video ${v.index}: ${e instanceof Error ? e.message : String(e)}`);
                  }
                  continue;
                }

                let srcAudioSegs: AudioSegmentItem[] = [];
                if (get().importOriginalSegments) {
                  try {
                    srcAudioSegs = await v2vApi.getSrcAudioSegments(jobId, v.index);
                    srcAudioSegs = srcAudioSegs.filter((as, i, a) => a.findIndex(t => t.seg === as.seg) === i);
                  } catch (e) {
                    console.warn(`[V2V] No se pudo obtener lista src-audio-segments para video ${v.index}:`, e);
                  }
                  // Si el backend no devolvió segmentos o falló, construir la lista fiel desde v.segments (result.json)
                  if (srcAudioSegs.length === 0 && v.segments && v.segments.length > 0) {
                    srcAudioSegs = v.segments.map((s) => {
                      const oStart = s.orig_start !== undefined ? s.orig_start : s.start;
                      const oEnd = s.orig_end !== undefined ? s.orig_end : s.end;
                      const oDur = s.orig_duration !== undefined ? s.orig_duration : Math.max(oEnd - oStart, 0.05);
                      return {
                        seg: s.seg,
                        start: oStart,
                        end: oEnd,
                        duration: oDur,
                        orig_start: oStart,
                        orig_end: oEnd,
                        orig_duration: oDur,
                        speaker: s.original_speaker || s.speaker || "SPEAKER_00",
                        filename: `vocals_${String(s.seg).padStart(3, "0")}.wav`,
                      };
                    });
                  }
                }
                  let workingProject = createEmptyProject(folder, {
                    width: baseProjectSettings.width,
                    height: baseProjectSettings.height,
                    frameRate: baseProjectSettings.frameRate,
                  });

                  interface V2VAssetDef {
                    id: string;
                    assetKey: string;
                    serverFn: string;
                    logicalName: string;
                    type: 'video' | 'audio';
                    toTimeline: boolean;
                    trackPrefix?: string;
                    muted?: boolean;
                    enabled: boolean;
                  }

                  const currentPrefs = get();
                  const assets: V2VAssetDef[] = [
                    { 
                      id: 'video_only', 
                      assetKey: 'video_only',
                      serverFn: v.video_only_path?.split(/[\\/]/).pop() || "", 
                      logicalName: v.video_only_path?.split(/[\\/]/).pop() || "video_only.mp4", 
                      type: 'video', 
                      toTimeline: true, 
                      trackPrefix: 'Video',
                      enabled: !!(v.video_only_path || v.video_path) 
                    },
                    { 
                      id: 'instrumental', 
                      assetKey: 'instrumental',
                      serverFn: v.instrumental_path?.split(/[\\/]/).pop() || "no_vocals.wav", 
                      logicalName: "no_vocals.wav", 
                      type: 'audio', 
                      toTimeline: currentPrefs.importInstrumental, 
                      trackPrefix: 'INSTRUMENTAL',
                      enabled: !!v.instrumental_path && currentPrefs.importInstrumental 
                    },
                    { 
                      id: 'merged_video', 
                      assetKey: 'merged',
                      serverFn: v.video_path?.split(/[\\/]/).pop() || "", 
                      logicalName: v.video_path?.split(/[\\/]/).pop() || "merged.mp4", 
                      type: 'video', 
                      toTimeline: currentPrefs.importMergedVideo, 
                      trackPrefix: 'MERGED_VIDEO',
                      enabled: !!v.video_path && currentPrefs.importMergedVideo 
                    },
                    { 
                      id: 'original_audio', 
                      assetKey: 'original_audio',
                      serverFn: v.original_audio_path?.split(/[\\/]/).pop() || "", 
                      logicalName: v.original_audio_path?.split(/[\\/]/).pop() || "original_audio.webm", 
                      type: 'audio', 
                      toTimeline: currentPrefs.importOriginalAudio, 
                      trackPrefix: 'ORIGINAL_AUDIO',
                      muted: true,
                      enabled: !!v.original_audio_path && currentPrefs.importOriginalAudio 
                    },
                    { 
                      id: 'vocals_original', 
                      assetKey: 'vocals',
                      serverFn: v.vocals_path?.split(/[\\/]/).pop() || "vocals.wav", 
                      logicalName: "vocals.wav", 
                      type: 'audio', 
                      toTimeline: currentPrefs.importOriginalVocals, 
                      trackPrefix: 'VOCALS_ORIGINAL',
                      muted: true,
                      enabled: !!v.vocals_path && currentPrefs.importOriginalVocals 
                    }
                  ];

                  const fetchAssetBlob = async (asset: V2VAssetDef) => {
                    if (!asset.enabled) return null;
                    try {
                      let blob: Blob | null = null;
                      try {
                        blob = await v2vApi.fetchAssetBlob(jobId, v.index, asset.assetKey);
                      } catch {
                        if (asset.id === 'video_only') {
                          try {
                            blob = await v2vApi.fetchOutputVideoBlob(jobId, v.index);
                          } catch {}
                        }
                        if (!blob && asset.serverFn) {
                          blob = await v2vApi.fetchFileBlob(jobId, v.index, asset.serverFn);
                        }
                      }
                      if (!blob) throw new Error(`No se pudo obtener el blob de ${asset.id}`);
                      return { asset, blob };
                    } catch (e) {
                      console.warn(`[V2V] Asset opcional no disponible: ${asset.serverFn || asset.id}`, e);
                      return null;
                    }
                  };

                  if (urlForLog) {
                    get().appendUrlLog(urlForLog, `\n${"=".repeat(60)}`);
                    get().appendUrlLog(urlForLog, `🚀 [Importación Timeline] Iniciando: "${folder}"`);

                    const activeOpts: string[] = [];
                    activeOpts.push(`🗣️ TTS: ${audioSegs.length} audios`);
                    if (currentPrefs.importOriginalSegments) activeOpts.push(`🎙️ Voces cortadas originales: ${srcAudioSegs.length || audioSegs.length} audios`);
                    if (currentPrefs.importInstrumental) activeOpts.push(`🎸 Instrumental (no_vocals)`);
                    if (currentPrefs.importOriginalVocals) activeOpts.push(`🎤 Voces originales completas (vocals.wav)`);
                    if (currentPrefs.importOriginalAudio) activeOpts.push(`🎵 Audio original completo`);
                    if (currentPrefs.importMergedVideo) activeOpts.push(`🎬 Video final mezclado`);

                    get().appendUrlLog(urlForLog, `• 📋 Configuración activa:\n   ${activeOpts.join("\n   ")}`);
                    get().appendUrlLog(urlForLog, `• 📥 Descargando medios (${activeOpts.join(" + ")})...`);
                  }

                  const tStartDownload = performance.now();
                  const assetTasks = assets.map(fetchAssetBlob);

                  const [downloadedAssetsRaw, downloadedSegs, downloadedSrcSegs] = await Promise.all([
                    Promise.all(assetTasks),
                    (async () => {
                      if (audioSegs.length === 0) return [];
                      try {
                        const tarMap = await v2vApi.fetchAudioSegmentsTar(jobId, v.index);
                        const segsFromTar: Array<{ isSegment: true; seg: AudioSegmentItem; logicalName: string; blob: Blob }> = [];
                        for (const seg of audioSegs) {
                          const logicalName = segmentLogicalName(seg);
                          let blob: Blob | undefined;
                          if (seg.filename && tarMap.has(seg.filename)) {
                            blob = tarMap.get(seg.filename);
                          } else if (tarMap.has(logicalName)) {
                            blob = tarMap.get(logicalName);
                          } else {
                            const segSuffix = `_${String(seg.seg).padStart(3, "0")}.wav`;
                            for (const [name, b] of tarMap.entries()) {
                              if (name.endsWith(segSuffix)) {
                                blob = b;
                                break;
                              }
                            }
                          }
                          if (blob) {
                            segsFromTar.push({ isSegment: true, seg, logicalName, blob });
                          }
                        }
                        if (segsFromTar.length > 0) {
                          return segsFromTar;
                        }
                      } catch (e) {
                        console.warn(`[V2V] Fallback a descargas individuales de audio para ${folder}:`, e);
                      }

                      if (urlForLog) {
                        get().appendUrlLog(urlForLog, `⚠️ [Fallback] Descargando ${audioSegs.length} audios en lotes controlados...`);
                      }
                      const CONCURRENCY_LIMIT = 5;
                      const individualResults: Array<{ isSegment: true; seg: AudioSegmentItem; logicalName: string; blob: Blob } | null> = [];
                      for (let i = 0; i < audioSegs.length; i += CONCURRENCY_LIMIT) {
                        const chunk = audioSegs.slice(i, i + CONCURRENCY_LIMIT);
                        const chunkResults = await Promise.all(
                          chunk.map(async (seg) => {
                            const logicalName = segmentLogicalName(seg);
                            for (let attempt = 0; attempt < 2; attempt++) {
                              try {
                                const blob = await v2vApi.fetchAudioSegmentBlob(jobId, v.index, seg.seg);
                                return { isSegment: true as const, seg, logicalName, blob };
                              } catch {
                                if (attempt === 0) await new Promise((r) => setTimeout(r, 400));
                              }
                            }
                            return null;
                          })
                        );
                        individualResults.push(...chunkResults);
                      }
                      const res = individualResults.filter((d): d is { isSegment: true; seg: AudioSegmentItem; logicalName: string; blob: Blob } => d !== null);
                      return res;
                    })(),
                    (async () => {
                      if (!currentPrefs.importOriginalSegments) return [];
                      const targetSrcList = srcAudioSegs.length > 0 ? srcAudioSegs : audioSegs;
                      if (targetSrcList.length === 0) return [];
                      try {
                        const tarMap = await v2vApi.fetchSrcAudioSegmentsTar(jobId, v.index);
                        const srcSegsFromTar: Array<{ isSrcSegment: true; seg: AudioSegmentItem; logicalName: string; blob: Blob }> = [];
                        for (const seg of targetSrcList) {
                          const segSuffix = `_${String(seg.seg).padStart(3, "0")}.wav`;
                          const logicalName = `vocals_${String(seg.seg).padStart(3, "0")}.wav`;
                          let blob: Blob | undefined;
                          if (tarMap.has(logicalName)) {
                            blob = tarMap.get(logicalName);
                          } else {
                            for (const [name, b] of tarMap.entries()) {
                              if (name.endsWith(segSuffix)) {
                                blob = b;
                                break;
                              }
                            }
                          }
                          if (blob) {
                            srcSegsFromTar.push({ isSrcSegment: true, seg, logicalName, blob });
                          }
                        }
                        if (srcSegsFromTar.length > 0) {
                          return srcSegsFromTar;
                        }
                      } catch (e) {
                        console.warn(`[V2V] Fallback a descargas individuales de audio original para ${folder}:`, e);
                      }

                      const CONCURRENCY_LIMIT = 5;
                      const individualSrcResults: Array<{ isSrcSegment: true; seg: AudioSegmentItem; logicalName: string; blob: Blob } | null> = [];
                      for (let i = 0; i < targetSrcList.length; i += CONCURRENCY_LIMIT) {
                        const chunk = targetSrcList.slice(i, i + CONCURRENCY_LIMIT);
                        const chunkResults = await Promise.all(
                          chunk.map(async (seg) => {
                            const logicalName = `vocals_${String(seg.seg).padStart(3, "0")}.wav`;
                            for (let attempt = 0; attempt < 2; attempt++) {
                              try {
                                const blob = await v2vApi.fetchSrcAudioSegmentBlob(jobId, v.index, seg.seg);
                                return { isSrcSegment: true as const, seg, logicalName, blob };
                              } catch {
                                if (attempt === 0) await new Promise((r) => setTimeout(r, 400));
                              }
                            }
                            return null;
                          })
                        );
                        individualSrcResults.push(...chunkResults);
                      }
                      return individualSrcResults.filter((d): d is { isSrcSegment: true; seg: AudioSegmentItem; logicalName: string; blob: Blob } => d !== null);
                    })()
                  ]);

                  const downloadedAssets = downloadedAssetsRaw.filter((d): d is { asset: V2VAssetDef, blob: Blob } => d !== null);
                  const tTotalDlSec = ((performance.now() - tStartDownload) / 1000).toFixed(1);
                  if (urlForLog) {
                    get().appendUrlLog(urlForLog, `• 📦 Medios descargados en ${tTotalDlSec}s (${downloadedAssets.length + downloadedSegs.length + downloadedSrcSegs.length} archivos)`);
                  }

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

                  const baseFilesToImport = downloadedAssets.map(d => {
                    const isM4A = d.blob.type.includes("mp4") && d.asset.type === 'audio';
                    const fileName = isM4A ? d.asset.logicalName.replace(/\.wav$/i, ".m4a") : d.asset.logicalName;
                    const mimeType = d.blob.type || (d.asset.type === 'video' ? 'video/mp4' : isM4A ? 'audio/mp4' : 'audio/wav');
                    return new File([d.blob], fileName, { type: mimeType });
                  });

                  const batchRes = await importMultipleMediaIntoProject(workingProject, baseFilesToImport, { quick: true });
                  if (!batchRes.success || !batchRes.project) {
                    console.error(`[V2V] importMultipleMediaIntoProject falló para ${folder}`);
                    get().setImportStatus(key, "error");
                    if (urlForLog) {
                      get().appendUrlLog(urlForLog, `❌ Falló la importación del video base para ${folder}`);
                    }
                    continue;
                  }

                  workingProject = batchRes.project;
                  const vMedia = workingProject.mediaLibrary.items.find(m => m.name === (v.video_only_path?.split(/[\\/]/).pop() || "video_only.mp4"));
                  if (vMedia?.metadata.width && vMedia?.metadata.height) {
                    workingProject = {
                      ...workingProject,
                      settings: { ...workingProject.settings, width: vMedia.metadata.width, height: vMedia.metadata.height },
                    };
                  }

                  const ttsMediaItems: MediaItem[] = [];
                  for (const d of downloadedSegs) {
                    const fallbackDuration = Math.max(d.seg.end - d.seg.start, 0.1);
                    const meta = {
                      duration: fallbackDuration,
                      width: 0,
                      height: 0,
                      frameRate: 0,
                      codec: "pcm_s16le",
                      sampleRate: 48000,
                      channels: 1,
                      fileSize: d.blob.size,
                    };
                    const item: MediaItem = {
                      id: uuidv4(),
                      name: d.logicalName,
                      type: "audio",
                      fileHandle: null,
                      blob: d.blob,
                      metadata: meta,
                      thumbnailUrl: null,
                      waveformData: null,
                    };
                    ttsMediaItems.push(item);

                    saveMediaBlob(workingProject.id, item.id, d.blob, meta).catch((err) =>
                      console.warn(`[V2V] Error guardando blob en IndexedDB para ${d.logicalName}:`, err)
                    );
                  }

                  const srcMediaItems: MediaItem[] = [];
                  for (const d of downloadedSrcSegs) {
                    const wavDur = await getWavBlobDuration(d.blob);
                    const segMeta = v.segments?.find((s) => s.seg === d.seg.seg);
                    const realDuration =
                      wavDur ||
                      d.seg.orig_duration ||
                      segMeta?.orig_duration ||
                      (d.seg.orig_end !== undefined && d.seg.orig_start !== undefined
                        ? Math.max(d.seg.orig_end - d.seg.orig_start, 0.05)
                        : (segMeta?.orig_end !== undefined && segMeta?.orig_start !== undefined
                          ? Math.max(segMeta.orig_end - segMeta.orig_start, 0.05)
                          : 0.1));
                    const meta = {
                      duration: realDuration,
                      width: 0,
                      height: 0,
                      frameRate: 0,
                      codec: "pcm_s16le",
                      sampleRate: 48000,
                      channels: 1,
                      fileSize: d.blob.size,
                    };
                    const item: MediaItem = {
                      id: uuidv4(),
                      name: d.logicalName,
                      type: "audio",
                      fileHandle: null,
                      blob: d.blob,
                      metadata: meta,
                      thumbnailUrl: null,
                      waveformData: null,
                    };
                    srcMediaItems.push(item);

                    saveMediaBlob(workingProject.id, item.id, d.blob, meta).catch((err) =>
                      console.warn(`[V2V] Error guardando blob en IndexedDB para ${d.logicalName}:`, err)
                    );
                  }

                  workingProject = {
                    ...workingProject,
                    mediaLibrary: {
                      ...workingProject.mediaLibrary,
                      items: [...workingProject.mediaLibrary.items, ...ttsMediaItems, ...srcMediaItems],
                    },
                    modifiedAt: Date.now(),
                  };

                  const tStartTimeline = performance.now();

                  for (const { asset } of downloadedAssets) {
                    if (!asset.toTimeline) continue;
                    const media = workingProject.mediaLibrary.items.find(
                      m => m.name === asset.logicalName || m.name === asset.logicalName.replace(/\.wav$/i, ".m4a")
                    );
                    if (!media) continue;

                    const { project: p1, trackId } = await addTrackAndGetId(workingProject, asset.type);
                    workingProject = p1;
                    if (!trackId) continue;
                    workingProject = renameTrackInProject(workingProject, trackId, asset.trackPrefix ? asset.trackPrefix : asset.id);
                    if (asset.muted) workingProject = muteTrackInProject(workingProject, trackId, true);
                    const clipRes = (await addClipToDetachedProject(workingProject, trackId, media.id, 0)) as any;
                    workingProject = clipRes.project!;
                  }

                  const bySpkAll: Record<string, AudioSegmentItem[]> = {};
                  for (const seg of audioSegs) {
                    const spk = (seg.speaker || "").trim() || `Speaker_${seg.seg}`;
                    (bySpkAll[spk] ||= []).push(seg);
                  }

                  const allClipsToBatchAdd: Array<{ trackId: string; mediaId: string; startTime: number; duration?: number }> = [];

                  for (const sKey of Object.keys(bySpkAll)) {
                    const segs = bySpkAll[sKey].sort((a, b) => a.seg - b.seg);
                    const { project: p2, trackId } = await addTrackAndGetId(workingProject, "audio");
                    workingProject = p2;
                    if (!trackId) continue;

                    workingProject = renameTrackInProject(workingProject, trackId, sKey);
                    const failedSegNums: number[] = [];

                    for (const seg of segs) {
                      const downloaded = downloadedSegs.find(d => d.seg.seg === seg.seg);

                      if (downloaded) {
                        const media = findSegmentMediaInLibrary(
                          workingProject.mediaLibrary.items,
                          seg,
                        );
                        if (!media) {
                          console.warn(
                            `[V2V] Segmento ${seg.seg} descargado pero no encontrado en librería: ${downloaded.logicalName}`,
                          );
                          continue;
                        }
                        const ttsDuration = seg.duration || Math.max(seg.end - seg.start, 0.1);
                        allClipsToBatchAdd.push({
                          trackId,
                          mediaId: media.id,
                          startTime: seg.start,
                          duration: ttsDuration,
                        });
                      } else {
                        const placeholderName = `tts_${toSafeToken(sKey)}_${String(seg.seg).padStart(3, "0")}.wav`;
                        const placeholderItem: MediaItem = {
                          id: uuidv4(),
                          name: placeholderName,
                          type: "audio",
                          fileHandle: null,
                          blob: null,
                          isPlaceholder: true,
                          metadata: {
                            duration: Math.max(seg.end - seg.start, 0.1),
                            width: 0,
                            height: 0,
                            frameRate: 0,
                            codec: "",
                            sampleRate: 48000,
                            channels: 1,
                            fileSize: 0,
                          },
                          thumbnailUrl: null,
                          waveformData: null,
                        };

                        workingProject = {
                          ...workingProject,
                          mediaLibrary: {
                            ...workingProject.mediaLibrary,
                            items: [...workingProject.mediaLibrary.items, placeholderItem],
                          },
                        };

                        allClipsToBatchAdd.push({
                          trackId,
                          mediaId: placeholderItem.id,
                          startTime: seg.start,
                        });
                        failedSegNums.push(seg.seg);
                      }
                    }

                    if (failedSegNums.length > 0) {
                      const logMsg = `⚠️ Speaker "${sKey}": ${failedSegNums.length} segmento(s) sin audio TTS (error al generar) → #${failedSegNums.join(", #")}. Recupéralos desde el Bulk Editor.`;
                      console.warn(`[V2V] ${logMsg}`);
                      if (urlForLog) get().appendUrlLog(urlForLog, logMsg);
                    }

                    if (currentPrefs.importOriginalSegments && downloadedSrcSegs.length > 0) {
                      const origTrackName = `ORIG_${sKey}`;
                      const { project: pOrig, trackId: origTrackId } = await addTrackAndGetId(workingProject, "audio");
                      workingProject = pOrig;
                      if (origTrackId) {
                        workingProject = renameTrackInProject(workingProject, origTrackId, origTrackName);
                        workingProject = muteTrackInProject(workingProject, origTrackId, true);

                        for (const seg of segs) {
                          const downloadedSrc = downloadedSrcSegs.find(d => d.seg.seg === seg.seg);
                          if (downloadedSrc) {
                            const media = workingProject.mediaLibrary.items.find(m => m.name === downloadedSrc.logicalName);
                            if (media) {
                              const segOrigMeta = v.segments?.find(s => s.seg === seg.seg);
                              const origStart = downloadedSrc.seg.orig_start !== undefined
                                ? downloadedSrc.seg.orig_start
                                : (segOrigMeta?.orig_start !== undefined ? segOrigMeta.orig_start : seg.start);
                              const origDuration = media.metadata.duration;
                              allClipsToBatchAdd.push({
                                trackId: origTrackId,
                                mediaId: media.id,
                                startTime: origStart,
                                duration: origDuration,
                              });
                            }
                          }
                        }
                      }
                    }
                  }

                  if (allClipsToBatchAdd.length > 0) {
                    const batchAddRes = await addMultipleClipsToDetachedProject(workingProject, allClipsToBatchAdd);
                    workingProject = batchAddRes.project;
                  }

                  await autoSaveManager.forceSave(workingProject);

                  const tTimelineMs = Math.round(performance.now() - tStartTimeline);
                  if (urlForLog) {
                    const ttsCount = downloadedSegs.length;
                    const srcCount = currentPrefs.importOriginalSegments ? downloadedSrcSegs.length : 0;
                    get().appendUrlLog(urlForLog, `• 🎬 Montaje: ${allClipsToBatchAdd.length} clips sincronizados (${ttsCount} TTS${srcCount > 0 ? ` + ${srcCount} originales con duración real` : ""}) en ${tTimelineMs}ms`);
                  }

                  const audioSegmentsImported = workingProject.mediaLibrary.items.filter(
                    m => m.type === "audio" && (m.name.startsWith("tts_") || m.name.startsWith("vocals_")) && !m.waveformData && !m.isPlaceholder
                  );
                  
                  if (audioSegmentsImported.length > 0) {
                    generateWaveformsInBackground(workingProject.id, audioSegmentsImported);
                  }
                  
                  const totalFilesCount = baseFilesToImport.length + ttsMediaItems.length + srcMediaItems.length;
                  const nativeFiles = [...baseFilesToImport.map(f => f.name), ...ttsMediaItems.map(m => m.name), ...srcMediaItems.map(m => m.name)];
                  
                  get().setFolderRef(folder, { jobId: state.jobId!, videoIndex: v.index, outputName: v.output_name, nativeFiles, projectId: workingProject.id });
                  
                  const segsWithMediaInfo = downloadedSegs.map((d) => {
                    const media = findSegmentMediaInLibrary(
                      workingProject.mediaLibrary.items,
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
                  const importElapsedSec = ((performance.now() - importStartTime) / 1000).toFixed(1);
                  if (urlForLog) {
                    get().appendUrlLog(urlForLog, `⏱️ [Importación Timeline] Completada en ${importElapsedSec}s (${totalFilesCount} archivos)`);
                    get().appendUrlLog(urlForLog, `✅ Proyecto "${folder}" listo para editar en OpenReel`);
                    get().appendUrlLog(urlForLog, `${"=".repeat(60)}\n`);
                  }

                  // Persistir estado de V2V directamente vinculado al nuevo workingProject.id
                  const currentState = get();
                  const allVideosToPersist = currentState.videos.length > 0 ? currentState.videos : (state.videos || []);
                  const allUrlItemsToPersist = currentState.urlItems.length > 0 ? currentState.urlItems : (state.urlItems || []);
                  const fullBatchUrls = (currentState.urls && currentState.urls.trim().split("\n").filter(Boolean).length > 1)
                    ? currentState.urls
                    : (allUrlItemsToPersist.length > 0 ? allUrlItemsToPersist.map(it => it.url).filter(Boolean).join("\n") : (currentState.urls || v.url || ""));

                  const jobSnapshotToPersist = {
                    urls: fullBatchUrls,
                    jobId: state.jobId!,
                    progress: 100,
                    videos: allVideosToPersist,
                    selectedVideoIndex: v.index,
                    segments: currentState.segments,
                    urlItems: allUrlItemsToPersist,
                    urlLogs: currentState.urlLogs,
                    log: currentState.log,
                    jobPhase: "done" as const,
                    importStatusByKey: { ...currentState.importStatusByKey, [key]: "done" as const },
                    shareUrl: currentState.shareUrl,
                    lastUrlsSignature: currentState.lastUrlsSignature,
                  };
                  saveJobStateForProject(workingProject.id, jobSnapshotToPersist);

                  // Propagar la lista acumulada de videos, urlItems y URLs a todos los proyectos de este job
                  if (allVideosToPersist.length > 0) {
                    for (const ref of Object.values(currentState.folderRefs || {})) {
                      if (ref.projectId && ref.jobId === state.jobId) {
                        saveJobStateForProject(ref.projectId, {
                          urls: fullBatchUrls,
                          videos: allVideosToPersist,
                          urlItems: allUrlItemsToPersist,
                        });
                      }
                    }
                  }

                  const activeProject = useProjectStore.getState().project;
                  const tracks = activeProject.timeline?.tracks || [];
                  const isCurrentProjectEmpty =
                    tracks.length === 0 ||
                    tracks.every((t) => !t.clips || t.clips.length === 0);

                  const shouldAutoLoad =
                    activeProject.id === workingProject.id ||
                    activeProject.name === folder ||
                    isCurrentProjectEmpty ||
                    ["Vertical", "Horizontal", "Square", "Untitled"].includes(activeProject.name);

                  if (shouldAutoLoad) {
                    useProjectStore.getState().loadProject(workingProject);
                    set({ currentProjectId: workingProject.id });
                    toast.success(
                      "Timeline V2V listo",
                      `Video "${folder}" montado con instrumental y voces en el timeline.`,
                    );
                  } else {
                    toast.info(
                      "Importación guardada en autosave",
                      `Abre el proyecto "${folder}" o recupera el autosave más reciente para ver el timeline completo.`,
                    );
                  }
                }
              } catch (err) {
                console.error("V2V Background import error:", err);
                const state = get();
                const pendingKeys = Object.keys(state.importStatusByKey).filter(k => state.importStatusByKey[k] === "in_progress");
                if (pendingKeys.length > 0) {
                  set((st) => {
                    const newStatus = { ...st.importStatusByKey };
                    pendingKeys.forEach(k => { newStatus[k] = "error"; });
                    return { importStatusByKey: newStatus };
                  });
                }
              } finally {
                isImportingBusy = false;
                const remaining = get().videos.filter(
                  (v) => !get().importStatusByKey[importKeyFor(v.url, v.index)],
                );
                if (remaining.length > 0) {
                  setTimeout(() => { void pollOnce(); }, 200);
                } else {
                  // Todos los videos terminaron de importarse: asegurar que cada proyecto tenga la lista completa
                  const finalVideos = get().videos;
                  const finalUrlItems = get().urlItems;
                  if (finalVideos.length > 0) {
                    const finalFullUrls = (get().urls && get().urls.trim().split("\n").filter(Boolean).length > 1)
                      ? get().urls
                      : (finalUrlItems.length > 0 ? finalUrlItems.map(it => it.url).filter(Boolean).join("\n") : get().urls);
                    for (const ref of Object.values(get().folderRefs || {})) {
                      if (ref.projectId && ref.jobId === state.jobId) {
                        saveJobStateForProject(ref.projectId, {
                          urls: finalFullUrls,
                          videos: finalVideos,
                          urlItems: finalUrlItems,
                        });
                      }
                    }
                  }
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
      if (activeWebSocket) {
        try { activeWebSocket.close(); } catch {}
        activeWebSocket = null;
      }
      if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
      }
      currentPollPhase = "fast";
      set({ isProcessing: false });
    },

    updateVideoOutputName: async (videoIndex: number, newOutputName: string, targetJobId?: string) => {
      const state = get();
      const newFolder = folderNameFromTitle(newOutputName);

      const updatedVideos = (state.videos || []).map((v, i) => {
        if (v.index === videoIndex || i === videoIndex) {
          return { ...v, output_name: newOutputName };
        }
        return v;
      });

      const updatedUrlItems = (state.urlItems || []).map((it, i) => {
        if (it.index === videoIndex || i === videoIndex) {
          return { ...it, output_name: newOutputName };
        }
        return it;
      });

      let matchedOldFolderKey: string | null = null;
      let matchedRef: SerializedFolderData | null = null;

      for (const [fKey, ref] of Object.entries(state.folderRefs || {})) {
        if (ref.videoIndex === videoIndex && (!targetJobId || ref.jobId === targetJobId)) {
          matchedOldFolderKey = fKey;
          matchedRef = ref;
          break;
        }
      }

      if (!matchedOldFolderKey && updatedVideos[videoIndex]) {
        const oldTitle = updatedVideos[videoIndex]?.output_name;
        if (oldTitle) {
          const oldFold = folderNameFromTitle(oldTitle);
          if (state.folderRefs[oldFold]) {
            matchedOldFolderKey = oldFold;
            matchedRef = state.folderRefs[oldFold];
          }
        }
      }

      const updatedFolderRefs = { ...state.folderRefs };
      if (matchedOldFolderKey && matchedRef) {
        const targetRef: SerializedFolderData = {
          ...matchedRef,
          outputName: newOutputName,
          folderId: generateFolderId(newFolder, matchedRef.jobId),
          updatedAt: Date.now(),
        };

        if (matchedOldFolderKey !== newFolder) {
          delete updatedFolderRefs[matchedOldFolderKey];
          updatedFolderRefs[newFolder] = targetRef;
        } else {
          updatedFolderRefs[matchedOldFolderKey] = targetRef;
        }
      }

      set({
        videos: updatedVideos,
        urlItems: updatedUrlItems,
        folderRefs: updatedFolderRefs,
      });
      saveJobStateToStorage({ videos: updatedVideos, urlItems: updatedUrlItems });
      saveFolderRefsToStorage(updatedFolderRefs);

      try {
        const projectStore = useProjectStore.getState();
        const activeProj = projectStore.project;
        const isActive =
          (matchedOldFolderKey && activeProj.name === matchedOldFolderKey) ||
          (matchedRef?.projectId && activeProj.id === matchedRef.projectId) ||
          (matchedRef?.nativeFiles &&
            activeProj.timeline.tracks.some((t) =>
              t.clips.some((c) => {
                const base = (c as any).mediaName?.split("/").pop() || "";
                return matchedRef!.nativeFiles.includes(base);
              }),
            )) ||
          activeProj.name === folderNameFromTitle(matchedRef?.outputName || "");

        if (isActive) {
          await projectStore.renameProject(newFolder);
          await autoSaveManager.initialize();
          const curr = useProjectStore.getState().project;
          await autoSaveManager.forceSave(curr);
        }

        await autoSaveManager.initialize();
        const saves = await autoSaveManager.checkForRecovery();
        for (const s of saves) {
          if (
            (matchedRef?.projectId && s.projectId === matchedRef.projectId) ||
            (matchedOldFolderKey && s.projectName === matchedOldFolderKey)
          ) {
            const p = await autoSaveManager.recover(s.id);
            if (p) {
              const updatedP = { ...p, name: newFolder };
              await autoSaveManager.forceSave(updatedP);
            }
          }
        }
      } catch (err) {
        console.warn("[V2V] Error actualizando proyecto tras regenerar título:", err);
      }
    },

    reset: () => {
      get().stopPolling();
      saveFolderRefsToStorage({});
      const pid = get().currentProjectId;
      if (pid) clearJobStateForProject(pid);
      set({
        urls: "",
        translateLang: "None",
        speaker: "mrbeast",
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
        isV2VOpen: false,
        bulkEditorOpen: false,
      });
    },
  };
};
