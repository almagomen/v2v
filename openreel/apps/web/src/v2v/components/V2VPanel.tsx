import React, { useEffect, useCallback, useMemo } from "react";
import { Youtube, Loader2, AlertCircle, Settings, Trash2 } from "lucide-react";
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
    clearJobRunState,
    syncWithProject,
  } = useV2VStore();

  const [backendUrl, setBackendUrl] = React.useState<string>(() => v2vApi.getBackendUrl());
  const [fishApiKey, setFishApiKey] = React.useState("");
  const [googleApiKey, setGoogleApiKey] = React.useState("");
  const [titleModel, setTitleModel] = React.useState<string>("gemini-flash-lite-latest");
  const [customTitleModel, setCustomTitleModel] = React.useState<string>("");
  const [translationModel, setTranslationModel] = React.useState<string>("gemini-flash-lite-latest");
  const [customTranslationModel, setCustomTranslationModel] = React.useState<string>("");
  const [reprocessUrls, setReprocessUrls] = React.useState<Set<string>>(new Set());
  const [showTokenSettings, setShowTokenSettings] = React.useState(false);
  const [isSavingTokens, setIsSavingTokens] = React.useState(false);

  const handleToggleReprocess = useCallback((targetUrl: string) => {
    setReprocessUrls((prev) => {
      const next = new Set(prev);
      if (next.has(targetUrl)) {
        next.delete(targetUrl);
        toast.info("Re-inferencia desactivada", "Se usará el comportamiento normal (reimportar desde caché si ya existe).");
      } else {
        next.add(targetUrl);
        // Si la URL no está en el cuadro de texto `urls`, la añadimos automáticamente
        const currentUrls = useV2VStore.getState().urls || "";
        const lines = currentUrls.split("\n").map((u: string) => u.trim()).filter(Boolean);
        if (!lines.includes(targetUrl)) {
          setUrls(currentUrls.trim() ? `${currentUrls.trim()}\n${targetUrl}` : targetUrl);
        }
        toast.success("Re-inferencia activada", "Al presionar el botón de procesar se volverá a procesar este enlace (+Versión) en vez de reimportar.");
      }
      return next;
    });
  }, [setUrls]);

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

  // Sincroniza el estado de V2V con el proyecto activo en OpenReel:
  // Si es un proyecto nuevo, el panel inicia 100% limpio.
  // Si es un proyecto existente con V2V, restaura sus links, videos y logs.
  useEffect(() => {
    syncWithProject(project?.id || null);
  }, [project?.id, syncWithProject]);
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

    const currentUrls = new Set(urlItems.map((it) => it.url));
    const urlsWithReprocess = normalized.filter((u) => reprocessUrls.has(u));
    const urlsToProcess = normalized.filter((u) => !currentUrls.has(u) || reprocessUrls.has(u));

    if (urlsToProcess.length === 0) {
      toast.info(
        "URL ya procesada",
        "Esta URL ya fue procesada previamente. Haz clic en el ícono 🔄 (Re-inferir) en la columna 'Acción' para volver a procesarla (+Versión) en vez de reimportar."
      );
      return;
    }

    const isForcingReprocess = urlsWithReprocess.length > 0;
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
        null,
        {
          forceReprocess: isForcingReprocess,
          enableEmotions: useV2VStore.getState().enableEmotions,
        }
      );
      setJobId(res.job_id);
      startPolling(res.job_id);

      if (isForcingReprocess) {
        setReprocessUrls((prev) => {
          const next = new Set(prev);
          urlsWithReprocess.forEach((u) => next.delete(u));
          return next;
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al iniciar");
      setIsProcessing(false);
    }
  }, [
    urls,
    urlItems,
    translateLang,
    speaker,
    reprocessUrls,
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

      if (urlToRemove) {
        setReprocessUrls((prev) => {
          const next = new Set(prev);
          next.delete(urlToRemove);
          return next;
        });
      }

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
            title="Configurar tokens, modelos IA, modulación de emociones y pistas del timeline"
          >
            <Settings size={13} className={showTokenSettings ? "animate-spin" : ""} style={{ animationDuration: "3s" }} />
            Ajustes
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
          <div className="flex items-center justify-between mb-1">
            <label className="text-[10px] text-text-muted block">
              URLs de YouTube (una por línea)
            </label>
            {(urls || videos.length > 0) && (
              <button
                type="button"
                onClick={() => {
                  setUrls("");
                  clearJobRunState();
                }}
                disabled={isProcessing}
                className="text-[10px] text-text-muted hover:text-red-400 flex items-center gap-1 transition-colors disabled:opacity-50"
                title="Limpiar URLs y estado de la cola"
              >
                <Trash2 className="w-3 h-3" />
                Limpiar
              </button>
            )}
          </div>
          <textarea
            className="w-full h-24 px-3 py-2 text-xs bg-background-tertiary border border-border rounded-lg resize-none focus:outline-none focus:ring-1 focus:ring-primary whitespace-pre overflow-x-auto"
            placeholder="https://www.youtube.com/watch?v=..."
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
            disabled={isProcessing}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
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
            disabled={isProcessing}
          />
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
          reprocessUrls={reprocessUrls}
          onToggleReprocess={handleToggleReprocess}
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

