import React, { useEffect, useCallback, useMemo } from "react";
import { Youtube, Loader2, AlertCircle, Trash2, ListChecks, Settings, Eye, EyeOff, ChevronDown, Terminal, Copy, Check } from "lucide-react";
import {
  ScrollArea,
  Button,
} from "@openreel/ui";
import { toast } from "../../stores/notification-store";
import { v2vApi } from "../../lib/v2v-api";
import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";
import { autoSaveManager } from "../../services/auto-save";
import {
  folderNameFromTitle,
  importKeyFor,
} from "../../utils/v2v-utils";
import { ColabExportTab } from "./ColabExportTab";
import { useColabExportStore } from "../../stores/colab-export-store";
import { V2VGenerateTTSSection } from "./v2v/V2VGenerateTTSSection";
import {
  V2V_EMOTIONS,
  DEFAULT_EMOTION_TAG,
  EMOTION_CATEGORIES,
  getEmotionsByCategory,
  formatEmotionLabel,
} from "../../utils/v2v-emotions";

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

function statusToBadgeClass(status: string): string {
  switch (status) {
    case "done":
      return "bg-primary/15 text-primary border border-primary/30";
    case "audio_ready":
    case "tts":
    case "transcribing":
    case "downloading":
      return "bg-blue-500/10 text-blue-400 border border-blue-500/20";
    case "cached":
      return "bg-purple-500/10 text-purple-400 border border-purple-500/20";
    case "error":
      return "bg-red-500/10 text-red-400 border border-red-500/20";
    default:
      return "bg-background-tertiary text-text-muted border border-border";
  }
}

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
    setIsV2VOpen,
  } = useV2VStore();

  const [fishApiKey, setFishApiKey] = React.useState("");
  const [googleApiKey, setGoogleApiKey] = React.useState("");
  const [titleModel, setTitleModel] = React.useState<string>("gemini-flash-lite-latest");
  const [customTitleModel, setCustomTitleModel] = React.useState<string>("");
  const [translationModel, setTranslationModel] = React.useState<string>("gemini-flash-latest");
  const [customTranslationModel, setCustomTranslationModel] = React.useState<string>("");
  const [initialEmotion, setInitialEmotion] = React.useState<string>(DEFAULT_EMOTION_TAG);
  const [showTokenSettings, setShowTokenSettings] = React.useState(false);
  const [isSavingTokens, setIsSavingTokens] = React.useState(false);
  const [showFishApiKey, setShowFishApiKey] = React.useState(false);
  const [showGoogleApiKey, setShowGoogleApiKey] = React.useState(false);
  const [isLogsOpen, setIsLogsOpen] = React.useState(false);
  const [titleDisplayModes, setTitleDisplayModes] = React.useState<Record<string, number>>({});
  const [copiedUrlKey, setCopiedUrlKey] = React.useState<string | null>(null);

  const cycleTitleMode = (itemKey: string) => {
    setTitleDisplayModes((prev) => {
      const current = prev[itemKey] || 0;
      return { ...prev, [itemKey]: (current + 1) % 3 };
    });
  };

  useEffect(() => {
    // Cargar tokens y modelos al montar
    const loadTokensAndModels = async () => {
      try {
        const res = await v2vApi.getTokens();
        setFishApiKey(res.fish_api_key || "");
        setGoogleApiKey(res.google_api_key || "");

        const knownModels = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemma-4-31b-it"];

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
      } catch (err) {
        console.error("Error cargando configuración:", err);
      }
    };
    loadTokensAndModels();
  }, []);

  const handleSaveTokens = useCallback(async () => {
    setIsSavingTokens(true);
    try {
      const effTitle = titleModel === "custom"
        ? (customTitleModel.trim() || "gemini-flash-lite-latest")
        : titleModel;
      const effTrans = translationModel === "custom"
        ? (customTranslationModel.trim() || "gemini-flash-latest")
        : translationModel;

      await v2vApi.saveTokens(fishApiKey, googleApiKey, effTitle, effTrans);

      // Sincronizar también con colab-export-store para exportación coherente
      useColabExportStore.getState().setGeminiModel(titleModel);
      if (titleModel === "custom" && customTitleModel.trim()) {
        useColabExportStore.getState().setCustomGeminiModel(customTitleModel.trim());
      }

      toast.success("Configuración guardada", "Tokens y modelos de IA actualizados correctamente.");
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

    // Identificar URLs nuevas que no estén ya en urlItems
    const currentUrls = new Set(urlItems.map(it => it.url));
    const newUrls = normalized.filter(u => !currentUrls.has(u));

    if (newUrls.length === 0) {
      toast.info("Sin URLs nuevas", "Todas las URLs ya han sido procesadas o están en cola.");
      return;
    }

    const signature = normalized.map((u: string) => encodeURIComponent(u)).join("|");
    // Si la firma es igual, es probable que solo estemos re-arrancando o recuperando
    const keepItems = true; 

    useV2VStore.getState().clearJobRunState({ keepImports: true, keepItems });
    useV2VStore.setState({ lastUrlsSignature: signature });
    setError(null);
    setLog("");
    setIsProcessing(true);
    setJobPhase("downloading");
    try {
      const res = await v2vApi.processUrls(
        newUrls,
        translateLang === "None" ? null : translateLang,
        speaker,
        initialEmotion === "none" ? null : initialEmotion
      );
      setJobId(res.job_id);
      startPolling(res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al iniciar");
      setIsProcessing(false);
    }
  }, [urls, translateLang, speaker, initialEmotion, urlItems, startPolling, setJobId, setError, setLog, setIsProcessing, setJobPhase]);

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


  const handleDeleteFolder = useCallback(async (folderName: string, urlToRemove?: string) => {
    if (!confirm(`¿Estás seguro de borrar físicamente la carpeta "${folderName}"? Se perderá el caché de descarga y procesamiento para este vídeo.`)) {
      return;
    }

    try {
      setIsProcessing(true);
      await v2vApi.deleteVideo(folderName);
      toast.success("Borrado completo", `Carpeta ${folderName} eliminada del disco.`);
      
      // Si se proporciona una URL, la quitamos también de la lista de items para permitir re-intento
      if (urlToRemove) {
        useV2VStore.setState((state) => ({
          urlItems: state.urlItems.filter(it => it.url !== urlToRemove)
        }));
      } else {
        // Si es un video de la lista final, refrescamos el job para que desaparezca
        if (jobId) startPolling(jobId);
      }
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
            onClick={() => setShowTokenSettings(!showTokenSettings)}
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
          <div className="p-3.5 rounded-xl border border-primary/20 bg-primary/5 space-y-3.5 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-24 h-24 bg-primary/10 rounded-full blur-2xl pointer-events-none" />
            
            <div className="relative">
              <h3 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                Configurar Tokens y Modelos IA (Fish Audio / Google)
              </h3>
              <p className="text-[10px] text-text-muted mt-0.5 leading-normal">
                Configura tus credenciales de API y los modelos de Gemini/Gemma para doblaje, traducción y títulos virales.
              </p>
            </div>

            <div className="space-y-2.5 relative">
              <div>
                <label className="text-[9px] text-text-muted block mb-1 font-medium">
                  FISH_API_KEY (Fish Audio)
                </label>
                <div className="relative flex items-center">
                  <input
                    type={showFishApiKey ? "text" : "password"}
                    className="w-full px-2.5 py-1.5 pr-8 text-[11px] font-mono bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                    placeholder="Pega tu API Key de Fish Audio aquí..."
                    value={fishApiKey}
                    onChange={(e) => setFishApiKey(e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={() => setShowFishApiKey(!showFishApiKey)}
                    className="absolute right-2.5 text-text-muted hover:text-text-primary transition-colors focus:outline-none"
                  >
                    {showFishApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>

              <div>
                <label className="text-[9px] text-text-muted block mb-1 font-medium">
                  GOOGLE_API_KEY (Gemini / Gemma)
                </label>
                <div className="relative flex items-center">
                  <input
                    type={showGoogleApiKey ? "text" : "password"}
                    className="w-full px-2.5 py-1.5 pr-8 text-[11px] font-mono bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                    placeholder="Pega tu GOOGLE_API_KEY (admite varias separadas por coma)..."
                    value={googleApiKey}
                    onChange={(e) => setGoogleApiKey(e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={() => setShowGoogleApiKey(!showGoogleApiKey)}
                    className="absolute right-2.5 text-text-muted hover:text-text-primary transition-colors focus:outline-none"
                  >
                    {showGoogleApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>

              {/* Selección de Modelos IA */}
              <div className="pt-2 border-t border-border/60 space-y-2">
                <div className="text-[10px] font-semibold text-text-primary flex items-center gap-1.5">
                  <span className="w-1 h-1 rounded-full bg-primary" />
                  Modelos de Lenguaje por Defecto (Google)
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {/* Modelo de Traducción */}
                  <div>
                    <label className="text-[9px] text-text-muted block mb-1 font-medium flex items-center justify-between">
                      <span>Modelo de Traducción</span>
                      <span className="text-[8px] text-primary font-mono">Diálogos</span>
                    </label>
                    <select
                      className="w-full px-2.5 py-1.5 text-[11px] bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
                      value={translationModel}
                      onChange={(e) => setTranslationModel(e.target.value)}
                    >
                      <option value="gemini-flash-latest">gemini-flash-latest (Recomendado)</option>
                      <option value="gemini-flash-lite-latest">gemini-flash-lite-latest (Rápido)</option>
                      <option value="gemma-4-31b-it">gemma-4-31b-it (Fallback)</option>
                      <option value="custom">Otro modelo personalizado...</option>
                    </select>
                    {translationModel === "custom" && (
                      <input
                        type="text"
                        className="mt-1.5 w-full px-2.5 py-1 text-[10px] font-mono bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                        placeholder="Ej: gemini-1.5-pro..."
                        value={customTranslationModel}
                        onChange={(e) => setCustomTranslationModel(e.target.value)}
                      />
                    )}
                  </div>

                  {/* Modelo de Título Viral */}
                  <div>
                    <label className="text-[9px] text-text-muted block mb-1 font-medium flex items-center justify-between">
                      <span>Modelo de Título Viral</span>
                      <span className="text-[8px] text-primary font-mono">TikTok</span>
                    </label>
                    <select
                      className="w-full px-2.5 py-1.5 text-[11px] bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
                      value={titleModel}
                      onChange={(e) => setTitleModel(e.target.value)}
                    >
                      <option value="gemini-flash-lite-latest">gemini-flash-lite-latest (Recomendado)</option>
                      <option value="gemini-flash-latest">gemini-flash-latest (Completo)</option>
                      <option value="gemma-4-31b-it">gemma-4-31b-it (Fallback)</option>
                      <option value="custom">Otro modelo personalizado...</option>
                    </select>
                    {titleModel === "custom" && (
                      <input
                        type="text"
                        className="mt-1.5 w-full px-2.5 py-1 text-[10px] font-mono bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                        placeholder="Ej: gemini-2.0-flash..."
                        value={customTitleModel}
                        onChange={(e) => setCustomTitleModel(e.target.value)}
                      />
                    )}
                  </div>
                </div>
              </div>

              <div className="flex gap-2 pt-1.5">
                <Button
                  onClick={handleSaveTokens}
                  disabled={isSavingTokens}
                  className="flex-1 text-xs h-8"
                  variant="default"
                >
                  {isSavingTokens ? (
                    <>
                      <Loader2 size={12} className="animate-spin mr-1.5" />
                      Guardando...
                    </>
                  ) : (
                    "Guardar y aplicar"
                  )}
                </Button>
                <Button
                  onClick={() => setShowTokenSettings(false)}
                  disabled={isSavingTokens}
                  className="text-xs h-8 px-3"
                  variant="secondary"
                >
                  Cancelar
                </Button>
              </div>
            </div>
          </div>
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
          <div>
            <label className="text-[10px] text-text-muted block mb-1">Voz</label>
            <select
              className="w-full px-2.5 py-2 text-xs bg-background-tertiary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
              disabled={isProcessing}
            >
              {speakers.length > 0 ? (
                speakers.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))
              ) : (
                <>
                  <option value="mrbeast">mrbeast</option>
                  <option value="default_fish">default_fish</option>
                </>
              )}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-text-muted block mb-1 flex items-center justify-between">
              <span>Emoción</span>
              <span className="text-[9px] text-primary">S2.1</span>
            </label>
            <select
              className="w-full px-2 py-2 text-xs bg-background-tertiary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
              value={initialEmotion}
              onChange={(e) => setInitialEmotion(e.target.value)}
              disabled={isProcessing}
              title="Emoción inicial que se antepondrá a los segmentos durante la generación"
            >
              <option value="none">⚪ Sin emoción previa</option>
              {EMOTION_CATEGORIES.map((cat) => (
                <optgroup key={cat.name} label={`${cat.emoji} ${cat.label}`}>
                  {getEmotionsByCategory(cat.name).map((em) => (
                    <option key={em.tag} value={em.tag}>
                      {formatEmotionLabel(em)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
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

        {urlItems.length > 0 && (
          <div className="space-y-1">
            <p className="text-[10px] text-text-muted">Estado por URL</p>
            <div className="max-h-32 overflow-y-auto border border-border rounded-lg">
              <table className="w-full text-[10px]">
                <thead className="bg-background-tertiary sticky top-0">
                  <tr>
                    <th className="px-2 py-1 text-left">#</th>
                    <th className="px-2 py-1 text-left">Título</th>
                    <th className="px-2 py-1 text-left">tag/state</th>
                    <th className="px-2 py-1 text-center">Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {urlItems.map((it: any, i: number) => {
                    const itemKey = `${it.url}_${it.index ?? i}`;
                    const importKey = typeof it.index === "number" ? importKeyFor(it.url, it.index) : null;
                    const isImported = importKey ? importStatusByKey[importKey] === "done" : false;
                    const isImporting = importKey ? importStatusByKey[importKey] === "in_progress" : false;

                    const currentMode = titleDisplayModes[itemKey] || 0; // 0: Viral, 1: Original, 2: Link
                    const viralTitle = it.output_name?.replace(/^\d+\.\s*/, "") || it.original_title || it.url;
                    const origTitle = it.original_title || it.output_name?.replace(/^\d+\.\s*/, "") || it.url;
                    const linkUrl = it.url;

                    let currentTitle = viralTitle;
                    let modeBadge = "Viral";
                    if (currentMode === 1) {
                      currentTitle = origTitle;
                      modeBadge = "Original";
                    } else if (currentMode === 2) {
                      currentTitle = linkUrl;
                      modeBadge = "Link";
                    }

                    // Estado del badge:
                    // Si backend dice "done", solo es "Completado" si ya se importó al timeline
                    let displayBadgeText = STATUS_LABEL[it.status] || it.status;
                    let displayBadgeClass = statusToBadgeClass(it.status);

                    if (it.status === "done") {
                      if (isImported) {
                        displayBadgeText = "Completado";
                        displayBadgeClass = "bg-primary/15 text-primary border border-primary/30";
                      } else if (isImporting) {
                        displayBadgeText = "Importando...";
                        displayBadgeClass = "bg-blue-500/15 text-blue-400 border border-blue-500/30 animate-pulse";
                      } else {
                        displayBadgeText = "Listo (en cola)";
                        displayBadgeClass = "bg-purple-500/10 text-purple-400 border border-purple-500/20";
                      }
                    }

                    return (
                      <tr key={itemKey} className="border-t border-border">
                        <td className="px-2 py-1 tabular-nums">{i + 1}</td>
                        <td
                          className="px-2 py-1 max-w-[220px] cursor-pointer group select-none"
                          title={currentTitle}
                          onClick={() => cycleTitleMode(itemKey)}
                        >
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span
                              className="text-[8px] font-mono uppercase px-1 py-0.5 rounded border border-border bg-background-tertiary/70 text-text-muted group-hover:border-primary/40 group-hover:text-primary shrink-0 transition-colors"
                              title={`Modo: ${modeBadge}. Clic para alternar (Viral -> Original -> Link)`}
                            >
                              {modeBadge}
                            </span>
                            <span className="truncate group-hover:text-primary transition-colors text-[11px]">
                              {currentTitle}
                            </span>
                          </div>
                        </td>
                        <td className="px-2 py-1">
                          <span
                            className={`inline-flex items-center px-1.5 py-0.5 rounded ${displayBadgeClass}`}
                          >
                            {displayBadgeText}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <button
                              className="text-text-muted hover:text-text-primary transition-colors p-1 rounded hover:bg-background-tertiary"
                              title={`Copiar ${modeBadge.toLowerCase()} al portapapeles`}
                              onClick={async (e) => {
                                e.stopPropagation();
                                try {
                                  await navigator.clipboard.writeText(currentTitle);
                                  setCopiedUrlKey(itemKey);
                                  toast.success("Copiado", `Se copió el ${modeBadge.toLowerCase()} al portapapeles.`);
                                  setTimeout(() => setCopiedUrlKey(null), 2000);
                                } catch (err) {
                                  console.error("Error al copiar:", err);
                                  toast.error("Error", "No se pudo copiar al portapapeles.");
                                }
                              }}
                            >
                              {copiedUrlKey === itemKey ? (
                                <Check size={12} className="text-emerald-400" />
                              ) : (
                                <Copy size={12} />
                              )}
                            </button>
                            <button
                              className="text-text-muted hover:text-red-500 transition-colors p-1 rounded hover:bg-background-tertiary"
                              title="Borrar carpeta y permitir re-intento"
                              disabled={isProcessing}
                              onClick={(e) => {
                                e.stopPropagation();
                                const folder = folderNameFromTitle(it.output_name || it.url);
                                handleDeleteFolder(folder, it.url);
                              }}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {log && (
          <div className="space-y-1.5 border border-border/60 rounded-lg p-2 bg-background-tertiary/40">
            <button
              type="button"
              onClick={() => setIsLogsOpen(!isLogsOpen)}
              className="w-full flex items-center justify-between text-[11px] text-text-muted hover:text-text-primary transition-colors font-medium select-none"
            >
              <div className="flex items-center gap-1.5">
                <Terminal size={12} className="text-text-muted" />
                <span>Logs del proceso</span>
              </div>
              <ChevronDown
                size={14}
                className={`transition-transform duration-200 text-text-muted ${
                  isLogsOpen ? "rotate-180" : ""
                }`}
              />
            </button>
            {isLogsOpen && (
              <pre className="mt-1.5 p-2.5 rounded-lg bg-background-tertiary font-mono text-[10px] min-h-[90px] max-h-[360px] overflow-auto resize-y whitespace-pre border border-border/50 select-text">
                {(() => {
                  let out = log || "";

                  // Import-only: mostramos lo que se registra en `urlLogs` (sin [STATE:...]).
                  const importText = urlItems
                    .map((it: any) => (it.url ? urlLogs[it.url] || "" : ""))
                    .filter(Boolean)
                    .join("\n");

                  return `${out}${importText ? `\n${importText}` : ""}`;
                })()}
              </pre>
            )}
          </div>
        )}

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

