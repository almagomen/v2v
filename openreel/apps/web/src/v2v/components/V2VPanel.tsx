import React, { useEffect, useCallback, useMemo } from "react";
import { Youtube, Loader2, AlertCircle, Settings, RefreshCw } from "lucide-react";
import {
  ScrollArea,
  Button,
} from "@openreel/ui";
import { toast } from "@/stores/notification-store";
import { v2vApi } from "../api/v2v-api";
import { useProjectStore } from "@/stores/project-store";
import { useV2VStore } from "../stores/v2v-store";
import { autoSaveManager } from "@/services/auto-save";
import {
  folderNameFromTitle,
  importKeyFor,
} from "../utils/v2v-utils";
import { ColabExportTab } from "./ColabExportTab";
import { useColabExportStore } from "../stores/colab-export-store";
import { V2VGenerateTTSSection } from "./V2VGenerateTTSSection";
import { TokensConfigSection } from "./TokensConfigSection";
import { SpeakerSelector } from "./SpeakerSelector";
import { JobProgressIndicator } from "./JobProgressIndicator";
import { DEFAULT_EMOTION_TAG } from "../utils/v2v-emotions";

const TRANSLATE_OPTIONS = [
  { value: "None", label: "Sin traducción" },
  { value: "es", label: "Español" },
  { value: "pt", label: "Portugués" },
  { value: "en", label: "Inglés" },
  { value: "fr", label: "Francés" },
  { value: "de", label: "Alemán" },
  { value: "it", label: "Italiano" },
];


const STATUS_LABEL: Record<string, string> = {
  pending: "En cola",
  downloading: "Descargando",
  cached: "Caché",
  transcribing: "Transcribiendo",
  tts: "TTS",
  audio_ready: "Audio listo",
  ready: "Listo (STT)",
  done: "Completado",
  error: "Error",
};

export const V2VPanel: React.FC<{ embedInDrawer?: boolean }> = ({
  embedInDrawer: _embedInDrawer = false,
}) => {
  const { project } = useProjectStore();
  const {
    urls,
    setUrls,
    translateLang,
    setTranslateLang,
    speaker,
    setSpeaker,
    jobId,
    setJobId,
    log,
    setLog,
    error,
    setError,
    videos,
    selectedVideoIndex,
    setSelectedVideoIndex,
    isProcessing,
    setIsProcessing,
    importStatusByKey,
    urlItems,
    urlLogs,
    jobPhase,
    setJobPhase,
    speakers,
    fetchSpeakers,
    startPolling,
    getFolderRef,
    bulkEditorOpen,
    setBulkEditorOpen,
  } = useV2VStore();

  const [backendUrl, setBackendUrl] = React.useState<string>(() => v2vApi.getBackendUrl());
  const [fishApiKey, setFishApiKey] = React.useState("");
  const [googleApiKey, setGoogleApiKey] = React.useState("");
  const [titleModel, setTitleModel] = React.useState<string>("gemini-flash-lite-latest");
  const [customTitleModel, setCustomTitleModel] = React.useState<string>("");
  const [translationModel, setTranslationModel] = React.useState<string>("gemini-flash-lite-latest");
  const [customTranslationModel, setCustomTranslationModel] = React.useState<string>("");
  const [initialEmotion, setInitialEmotion] = React.useState<string>(DEFAULT_EMOTION_TAG);
  const [forceReprocess, setForceReprocess] = React.useState<boolean>(false);
  const [showTokenSettings, setShowTokenSettings] = React.useState(false);
  const [isSavingTokens, setIsSavingTokens] = React.useState(false);

  const loadTokensAndModels = useCallback(async () => {
    try {
      const res = await v2vApi.getTokens();
      if (res.fish_api_key !== undefined) setFishApiKey(res.fish_api_key || "");
      if (res.google_api_key !== undefined) setGoogleApiKey(res.google_api_key || "");

      const knownModels = ["gemini-flash-lite-latest", "gemma-4-26b-a4b-it"];

      if (res.title_model) {
        if (knownModels.includes(res.title_model)) {
          setTitleModel(res.title_model);
        } else {
          setTitleModel("custom");
          setCustomTitleModel(res.title_model);
        }
      }

      if (res.translation_model) {
        if (knownModels.includes(res.translation_model)) {
          setTranslationModel(res.translation_model);
        } else {
          setTranslationModel("custom");
          setCustomTranslationModel(res.translation_model);
        }
      }
      return true;
    } catch (err) {
      console.error("Error cargando configuración de tokens/modelos:", err);
      return false;
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    const init = async () => {
      const ok = await loadTokensAndModels();
      if (!ok && mounted) {
        // Reintentar una vez tras 2 segundos si el backend o túnel aún estaban sincronizando
        setTimeout(() => {
          if (mounted) loadTokensAndModels();
        }, 2000);
      }
    };
    init();
    return () => {
      mounted = false;
    };
  }, [loadTokensAndModels]);

  const handleSaveTokens = useCallback(async () => {
    setIsSavingTokens(true);
    try {
      const effTitle = titleModel === "custom"
        ? (customTitleModel.trim() || "gemini-flash-lite-latest")
        : titleModel;
      const effTrans = translationModel === "custom"
        ? (customTranslationModel.trim() || "gemini-flash-lite-latest")
        : translationModel;

      v2vApi.setBackendUrl(backendUrl);
      await v2vApi.saveTokens(fishApiKey, googleApiKey, effTitle, effTrans);

      // Sincronizar también con colab-export-store para exportación coherente
      useColabExportStore.getState().setGeminiModel(titleModel);
      if (titleModel === "custom" && customTitleModel.trim()) {
        useColabExportStore.getState().setCustomGeminiModel(customTitleModel.trim());
      }

      await fetchSpeakers();
      await loadTokensAndModels();

      toast.success("Configuración guardada", "Servidor y tokens de IA actualizados correctamente.");
      setShowTokenSettings(false);
    } catch (err) {
      toast.error("Error al guardar", err instanceof Error ? err.message : "No se pudo actualizar");
    } finally {
      setIsSavingTokens(false);
    }
  }, [fishApiKey, googleApiKey, titleModel, customTitleModel, translationModel, customTranslationModel]);



  // Calcula cuál índice de video corresponde al proyecto activo.
  // Si el proyecto no es V2V (no coincide con ninguno), retorna -1 para mostrar el placeholder.
  const effectiveDropdownValue = useMemo(() => {
    for (let i = 0; i < videos.length; i++) {
      const v = videos[i] as any;
      const projectTitle = folderNameFromTitle(v.output_name || `video_${v.index}`);
      if (project.name === projectTitle) return i;
    }
    return -1;
  }, [videos, project.name]);

  const bulkEditorContext = useMemo(() => {
    const videoIdx =
      effectiveDropdownValue >= 0 ? effectiveDropdownValue : (selectedVideoIndex >= 0 ? selectedVideoIndex : 0);
    if (!jobId || videoIdx < 0 || !videos[videoIdx]) return null;
    const v = videos[videoIdx] as { index: number; output_name?: string; url?: string };
    const folder = folderNameFromTitle(v.output_name || `video_${v.index}`);
    if (!getFolderRef(folder)) return null;
    return {
      jobId,
      videoIndex: v.index,
      folder,
      targetLang: translateLang === "None" ? null : translateLang,
    };
  }, [jobId, selectedVideoIndex, effectiveDropdownValue, videos, getFolderRef, translateLang]);

  useEffect(() => {
    if (!bulkEditorContext && bulkEditorOpen) {
      setBulkEditorOpen(false);
    }
  }, [bulkEditorContext, bulkEditorOpen]);

  useEffect(() => {
    if (speakers.length === 0) {
      fetchSpeakers();
    }
  }, [speakers.length, fetchSpeakers]);

  // Si ya hay un jobId activo al montar, iniciamos polling por si acaso (recuperación tras refresh)
  useEffect(() => {
    if (jobId && isProcessing) {
      startPolling(jobId);
    }
  }, []);

  const handleProcess = useCallback(async () => {
    const urlList = urls
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    const normalized = urlList
      .map((u: string) => (/^https?:\/\//i.test(u) ? u : `https://${u}`))
      .filter((u: string) => /^https?:\/\/(www\.)?(youtube\.com\/|youtu\.be\/)/i.test(u));
    if (normalized.length === 0) {
      setError("Introduce al menos una URL de YouTube");
      return;
    }

    let urlsToProcess = normalized;
    if (!forceReprocess) {
      const currentUrls = new Set(urlItems.map((it) => it.url));
      const newUrls = normalized.filter((u) => !currentUrls.has(u));
      if (newUrls.length > 0) {
        urlsToProcess = newUrls;
      } else {
        toast.info(
          "URL ya procesada",
          "Esta URL ya fue procesada previamente. Marca la casilla 'Re-inferir (nueva versión)' para procesarla de nuevo creando un proyecto nuevo (_v2, _v3) sin sobrescribir el original."
        );
        return;
      }
    }

    const signature = normalized.map((u: string) => encodeURIComponent(u)).join("|");
    const keepItems = true; 

    useV2VStore.getState().clearJobRunState({ keepImports: true, keepItems });
    useV2VStore.setState({ lastUrlsSignature: signature });
    setError(null);
    setLog("");
    setIsProcessing(true);
    setJobPhase("downloading");
    try {
      const res = await v2vApi.processUrls(
        urlsToProcess,
        translateLang === "None" ? null : translateLang,
        speaker,
        initialEmotion === "none" ? null : initialEmotion,
        {
          forceReprocess: forceReprocess,
        }
      );
      setJobId(res.job_id);
      startPolling(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al iniciar");
      setIsProcessing(false);
    }
  }, [
    urls,
    urlItems,
    translateLang,
    speaker,
    initialEmotion,
    forceReprocess,
    startPolling,
    setJobId,
    setError,
    setLog,
    setIsProcessing,
    setJobPhase,
  ]);

  const handleVideoSelect = useCallback(
    async (idx: number) => {
      setSelectedVideoIndex(idx);
      // Actualizamos segments en el store para que Clone Voice lo vea
      const v = videos[idx];
      if (v) {
        useV2VStore.getState().setSegments(v.segments);
      }

      // Cambiar al proyecto correspondiente al video seleccionado
      if (!v) return;
      const projectTitle = folderNameFromTitle(v.output_name || `video_${v.index}`);

      const projectStore = useProjectStore.getState();
      const wasAlreadyActive = projectStore.project.name === projectTitle;

      try {
        await autoSaveManager.initialize();

        // Persistir el proyecto actual antes de abandonarlo para evitar pérdida de cambios
        // y para que el import en background no sobreescriba el estado al hacer loadProject
        const currentProject = projectStore.project;
        if (!wasAlreadyActive && currentProject.timeline.tracks.length > 0) {
          await autoSaveManager.forceSave(currentProject);
        }

        const saves = await autoSaveManager.checkForRecovery();
        const uniqueProjects = saves.reduce((acc: any[], save: any) => {
          const existing = acc.find((s: any) => s.projectId === save.projectId);
          if (!existing || save.timestamp > existing.timestamp) {
            return [...acc.filter((s: any) => s.projectId !== save.projectId), save];
          }
          return acc;
        }, [] as any[]);

        const targetSave = uniqueProjects.find((s: any) => s.projectName === projectTitle);
        if (targetSave) {
          await projectStore.recoverFromAutoSave(targetSave.id);
          toast.info(
            wasAlreadyActive ? "Proyecto actualizado" : "Proyecto cargado",
            wasAlreadyActive
              ? `Autosave más reciente de "${projectTitle}" aplicado.`
              : `Proyecto "${projectTitle}" activo.`,
          );
        }
      } catch {
        // Ignorar errores de cambio de proyecto silenciosamente
      }
    },
    [videos, setSelectedVideoIndex],
  );

  // Cargar en editor eliminado: ahora se importa automáticamente a Media durante el proceso.


  const handleDeleteFolder = useCallback(async (displayName: string, folderName?: string, urlToRemove?: string) => {
    if (!confirm(`¿Estás seguro de eliminar "${displayName}"? Se borrará el caché de descarga y procesamiento para permitir re-intentar.`)) {
      return;
    }

    try {
      setIsProcessing(true);
      await v2vApi.deleteVideo(folderName, urlToRemove);
      toast.success("Eliminado", `Vídeo "${displayName}" eliminado.`);
      
      // Limpiar urlItems, videos e importStatusByKey del store local
      useV2VStore.setState((state) => {
        const nextUrlItems = urlToRemove ? state.urlItems.filter(it => it.url !== urlToRemove) : state.urlItems;
        const nextVideos = urlToRemove ? state.videos.filter(v => v.url !== urlToRemove) : state.videos;
        const nextStatus = { ...state.importStatusByKey };
        if (urlToRemove) {
          for (const k of Object.keys(nextStatus)) {
            if (k.startsWith(`${urlToRemove}::`)) {
              delete nextStatus[k];
            }
          }
        }
        return {
          urlItems: nextUrlItems,
          videos: nextVideos,
          importStatusByKey: nextStatus,
        };
      });

      if (jobId) startPolling(jobId);
    } catch (e) {
      toast.error("Error al borrar", e instanceof Error ? e.message : "No se pudo borrar");
    } finally {
      setIsProcessing(false);
    }
  }, [jobId, setIsProcessing, startPolling]);



  return (
    <>
    <ScrollArea className="h-full min-h-0 flex-1 w-full">
      <div className="p-4 space-y-4 min-w-0">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <div className="flex items-center gap-2">
            <Youtube size={20} className="text-red-500" />
            <h2 className="text-sm font-semibold text-text-primary">
              Video2Video – Traducción y doblaje
            </h2>
          </div>
          <button
            onClick={() => {
              const next = !showTokenSettings;
              setShowTokenSettings(next);
              if (next) {
                loadTokensAndModels();
              }
            }}
            className={`p-1.5 rounded-lg border transition-all flex items-center gap-1.5 text-xs font-medium ${
              showTokenSettings 
                ? "bg-primary/10 border-primary/20 text-primary shadow-sm" 
                : "bg-background-tertiary border-border text-text-muted hover:text-text-primary hover:bg-background-secondary"
            }`}
            title="Configurar tokens de Fish Audio y Gemini"
          >
            <Settings size={13} className={showTokenSettings ? "animate-spin" : ""} style={{ animationDuration: "3s" }} />
            Tokens
          </button>
        </div>

        {showTokenSettings && (
          <TokensConfigSection
            backendUrl={backendUrl}
            setBackendUrl={setBackendUrl}
            fishApiKey={fishApiKey}
            setFishApiKey={setFishApiKey}
            googleApiKey={googleApiKey}
            setGoogleApiKey={setGoogleApiKey}
            titleModel={titleModel}
            setTitleModel={setTitleModel}
            customTitleModel={customTitleModel}
            setCustomTitleModel={setCustomTitleModel}
            translationModel={translationModel}
            setTranslationModel={setTranslationModel}
            customTranslationModel={customTranslationModel}
            setCustomTranslationModel={setCustomTranslationModel}
            isSavingTokens={isSavingTokens}
            onSaveTokens={handleSaveTokens}
            onClose={() => setShowTokenSettings(false)}
          />
        )}

        <div>
          <label className="text-[10px] text-text-muted block mb-1">
            URLs de YouTube (una por línea)
          </label>
          <textarea
            className="w-full h-24 px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-primary whitespace-pre overflow-x-auto"
            placeholder="https://www.youtube.com/watch?v=..."
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
            disabled={isProcessing}
          />
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="text-[10px] text-text-muted block mb-1">Idioma</label>
            <select
              className="w-full px-2.5 py-2 text-xs bg-background-tertiary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
              value={translateLang}
              onChange={(e) => setTranslateLang(e.target.value)}
              disabled={isProcessing}
            >
              {TRANSLATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <SpeakerSelector
            speaker={speaker}
            setSpeaker={setSpeaker}
            speakers={speakers}
            initialEmotion={initialEmotion}
            setInitialEmotion={setInitialEmotion}
            disabled={isProcessing}
          />
        </div>

        {/* Opciones modulares de inferencia */}
        <div className="bg-background-tertiary/60 border border-border/80 rounded-lg p-2.5 space-y-2">
          <div className="text-[10px] font-semibold text-text-muted flex items-center justify-between">
            <span>Opciones de Inferencia</span>
            <span className="text-[9px] text-primary/80 font-mono">Configuración</span>
          </div>

          <div className="pt-0.5">
            {/* Re-inferir sin sobrescribir */}
            <label
              className="flex items-center gap-2 p-1 rounded-md hover:bg-background/50 cursor-pointer select-none text-[11px] text-text-secondary transition-colors"
              title="Permite volver a inferir una URL ya procesada creando una carpeta/proyecto nuevo (_v2, _v3) sin alterar el original."
            >
              <input
                type="checkbox"
                checked={forceReprocess}
                onChange={(e) => setForceReprocess(e.target.checked)}
                disabled={isProcessing}
                className="rounded border-border text-primary focus:ring-0 focus:ring-offset-0 cursor-pointer w-3.5 h-3.5 accent-primary"
              />
              <span className="flex items-center gap-1 truncate">
                <RefreshCw size={12} className="text-emerald-400 shrink-0" />
                <span>Re-inferir (+Versión)</span>
              </span>
            </label>
          </div>
        </div>

        <Button
          onClick={handleProcess}
          disabled={isProcessing || Object.values(importStatusByKey).some((s) => s === "in_progress")}
          className="w-full"
        >
          {(() => {
            const hasImportsInFlight = Object.values(importStatusByKey).some(
              (s) => s === "in_progress",
            );

            const order: Record<string, number> = {
              downloading: 1,
              cached: 2,
              transcribing: 3,
              tts: 4,
              audio_ready: 5,
              ready: 6,
              done: 100,
              error: 101,
              pending: 1000,
            };

            // Si hay varias URLs, mostramos el "estado más activo" (menor prioridad)
            // entre las que no estén done/error/pending.
            const activeCandidates = urlItems
              .filter((it: any) => it.status && it.status !== "done" && it.status !== "error" && it.status !== "pending");

            const importingCandidates = hasImportsInFlight
              ? urlItems.filter(
                  (it: any) =>
                    typeof it.index === "number" &&
                    importStatusByKey[importKeyFor(it.url, it.index)] === "in_progress",
                )
              : [];

            const activeUrlState =
              importingCandidates.length > 0
                ? importingCandidates[0]
                : activeCandidates.length > 0
                  ? activeCandidates.sort(
                      (a: any, b: any) => (order[a.status] ?? 999) - (order[b.status] ?? 999),
                    )[0]
                  : null;

            const activeStatus = activeUrlState?.status || jobPhase;
            const tagText =
              hasImportsInFlight
                ? "Importando a Media"
                : activeStatus && activeStatus !== "idle"
                  ? STATUS_LABEL[activeStatus] || activeStatus
                  : "Empezar";

            const activePos = activeUrlState
              ? urlItems.findIndex(
                  (it: any) => it.url === activeUrlState.url && it.index === activeUrlState.index,
                )
              : -1;
            const x = urlItems.length || 1;
            const prefix = activePos >= 0 ? `[${activePos + 1}/${x}] ` : "";
            const tag = `${prefix}${tagText}`;

            const showSpin = isProcessing || hasImportsInFlight;
            return (
              <>
                {showSpin && <Loader2 size={14} className="animate-spin mr-2" />}
                {tag}
              </>
            );
          })()}
        </Button>

        {error && (
          <div className="flex items-center gap-2 p-2 rounded-lg bg-red-500/10 text-red-500 text-xs">
            <AlertCircle size={14} />
            {error}
          </div>
        )}

        <JobProgressIndicator
          urlItems={urlItems}
          importStatusByKey={importStatusByKey}
          isProcessing={isProcessing}
          onDeleteFolder={handleDeleteFolder}
          log={log}
          urlLogs={urlLogs}
        />

        {videos.length > 0 && (
          <>
            <div>
              <label className="text-[10px] text-text-muted block mb-1">Video procesado</label>
              <div className="flex gap-2">
                <select
                  className="flex-1 min-w-0 truncate px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg"
                  value={effectiveDropdownValue}
                  onChange={(e) => {
                    const val = parseInt(e.target.value, 10);
                    if (val >= 0) handleVideoSelect(val);
                  }}
                >
                  {effectiveDropdownValue < 0 && (
                    <option value={-1}>— Seleccionar video —</option>
                  )}
                  {videos.map((v: any, i: number) => (
                    <option key={i} value={i}>
                      {v.output_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Generación de voz TTS (N+1) */}
            <div className="pt-2">
              <V2VGenerateTTSSection inDrawer={_embedInDrawer} />
            </div>
          </>
        )}



        {/* Exportación Colab */}
        <div className="pt-4 mt-4 border-t border-border">
          <ColabExportTab />
        </div>
      </div>
    </ScrollArea>
    </>
  );
};

