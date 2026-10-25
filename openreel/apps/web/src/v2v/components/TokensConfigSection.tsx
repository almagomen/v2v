import React, { useState } from "react";
import {
  Eye,
  EyeOff,
  Loader2,
  Server,
  CheckCircle2,
  XCircle,
  Sparkles,
  Sliders,
  Music,
  Mic,
  Radio,
  Film,
  Layers,
  FolderInput,
  Smile,
} from "lucide-react";
import { Button } from "@openreel/ui";
import { v2vApi } from "../api/v2v-api";
import { useV2VStore } from "../stores/v2v-store";
import { V2V_EMOTIONS } from "../utils/v2v-emotions";

export interface TokensConfigSectionProps {
  backendUrl: string;
  setBackendUrl: (url: string) => void;
  fishApiKey: string;
  setFishApiKey: (key: string) => void;
  googleApiKey: string;
  setGoogleApiKey: (key: string) => void;
  titleModel: string;
  setTitleModel: (model: string) => void;
  customTitleModel: string;
  setCustomTitleModel: (model: string) => void;
  translationModel: string;
  setTranslationModel: (model: string) => void;
  customTranslationModel: string;
  setCustomTranslationModel: (model: string) => void;
  isSavingTokens: boolean;
  onSaveTokens: () => Promise<void>;
  onClose: () => void;
}

export const TokensConfigSection: React.FC<TokensConfigSectionProps> = ({
  backendUrl,
  setBackendUrl,
  fishApiKey,
  setFishApiKey,
  googleApiKey,
  setGoogleApiKey,
  titleModel,
  setTitleModel,
  customTitleModel,
  setCustomTitleModel,
  translationModel,
  setTranslationModel,
  customTranslationModel,
  setCustomTranslationModel,
  isSavingTokens,
  onSaveTokens,
  onClose,
}) => {
  const [showFishApiKey, setShowFishApiKey] = useState(false);
  const [showGoogleApiKey, setShowGoogleApiKey] = useState(false);
  const [isTestingBackend, setIsTestingBackend] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const [importingTrackKey, setImportingTrackKey] = useState<string | null>(null);

  const {
    enableEmotions,
    setEnableEmotions,
    initialEmotionPerSentence,
    setInitialEmotionPerSentence,
    initialEmotionTag,
    setInitialEmotionTag,
    importTTSSegments,
    setImportTTSSegments,
    importMergedVideo,
    setImportMergedVideo,
    importInstrumental,
    setImportInstrumental,
    importOriginalAudio,
    setImportOriginalAudio,
    importOriginalVocals,
    setImportOriginalVocals,
    importOriginalSegments,
    setImportOriginalSegments,
    importSingleTrackToTimeline,
    jobId,
    videos,
  } = useV2VStore();

  const handleImportSingleTrack = async (trackKey: string) => {
    setImportingTrackKey(trackKey);
    try {
      await importSingleTrackToTimeline(trackKey);
    } finally {
      setImportingTrackKey(null);
    }
  };

  const handleTestConnection = async () => {
    setIsTestingBackend(true);
    setTestResult(null);
    try {
      v2vApi.setBackendUrl(backendUrl);
      const res = await v2vApi.checkHealth();
      if (res.ok) {
        let syncedMsg = "Conexión exitosa";
        try {
          const remoteTokens = await v2vApi.getTokens();
          let syncedCount = 0;
          if (remoteTokens.fish_api_key) {
            setFishApiKey(remoteTokens.fish_api_key);
            syncedCount++;
          }
          if (remoteTokens.google_api_key) {
            setGoogleApiKey(remoteTokens.google_api_key);
            syncedCount++;
          }
          if (remoteTokens.title_model) {
            const known = ["gemini-flash-lite-latest", "gemma-4-26b-a4b-it"];
            if (known.includes(remoteTokens.title_model)) {
              setTitleModel(remoteTokens.title_model);
            } else {
              setTitleModel("custom");
              setCustomTitleModel(remoteTokens.title_model);
            }
          }
          if (remoteTokens.translation_model) {
            const known = ["gemini-flash-lite-latest", "gemma-4-26b-a4b-it"];
            if (known.includes(remoteTokens.translation_model)) {
              setTranslationModel(remoteTokens.translation_model);
            } else {
              setTranslationModel("custom");
              setCustomTranslationModel(remoteTokens.translation_model);
            }
          }
          if (syncedCount > 0) {
            syncedMsg += " — Tokens sincronizados.";
          }
        } catch {
          // Mantener mensaje principal si la lectura de tokens no responde
        }
        setTestResult({ ok: true, message: syncedMsg });
      } else {
        setTestResult({ ok: false, message: res.error || "El servidor no respondió /health" });
      }
    } catch (e: any) {
      setTestResult({ ok: false, message: e?.message || "Error al conectar con la URL" });
    } finally {
      setIsTestingBackend(false);
    }
  };

  return (
    <div className="p-3.5 rounded-xl border border-primary/20 bg-primary/5 space-y-3.5 relative overflow-hidden">
      <div className="absolute top-0 right-0 w-24 h-24 bg-primary/10 rounded-full blur-2xl pointer-events-none" />

      <div className="relative">
        <h3 className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          Configurar Backend y Tokens IA
        </h3>
        <p className="text-[10px] text-text-muted mt-0.5 leading-normal">
          Configura la URL de tu servidor y las credenciales API.
        </p>
      </div>

      <div className="space-y-2.5 relative">
        {/* Backend URL para Desktop o Conexión Externa */}
        <div className="p-2.5 rounded-lg border border-border/80 bg-background/70 space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-[10px] font-semibold text-text-primary flex items-center gap-1.5">
              <Server size={12} className="text-primary" />
              URL del Backend Remoto
            </label>
            <button
              type="button"
              onClick={handleTestConnection}
              disabled={isTestingBackend}
              className="px-2 py-0.5 rounded text-[10px] font-medium bg-background-tertiary border border-border hover:bg-background-secondary text-text-primary transition-colors flex items-center gap-1 disabled:opacity-50"
            >
              {isTestingBackend ? (
                <>
                  <Loader2 size={10} className="animate-spin text-primary" />
                  Probando...
                </>
              ) : (
                "Probar conexión"
              )}
            </button>
          </div>
          <input
            type="text"
            className="w-full px-2.5 py-1.5 text-[11px] font-mono bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
            placeholder="Desktop: cloudflare - Web: automático"
            value={backendUrl}
            onChange={(e) => {
              setBackendUrl(e.target.value);
              setTestResult(null);
            }}
          />
          {testResult && (
            <div
              className={`flex items-center gap-1.5 text-[10px] p-1.5 rounded-md ${
                testResult.ok
                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                  : "bg-red-500/10 text-red-400 border border-red-500/20"
              }`}
            >
              {testResult.ok ? <CheckCircle2 size={12} className="shrink-0" /> : <XCircle size={12} className="shrink-0" />}
              <span className="truncate">{testResult.message}</span>
            </div>
          )}
        </div>
        <div>
          <label className="text-[9px] text-text-muted block mb-1 font-medium">
            TTS_API_KEY
          </label>
          <div className="relative flex items-center">
            <input
              type={showFishApiKey ? "text" : "password"}
              className="w-full px-2.5 py-1.5 pr-8 text-[11px] font-mono bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Pega tu API Model TTS audio aquí..."
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
            LLM_API_KEY
          </label>
          <div className="relative flex items-center">
            <input
              type={showGoogleApiKey ? "text" : "password"}
              className="w-full px-2.5 py-1.5 pr-8 text-[11px] font-mono bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Pega tus API LLM separadas por comas..."
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
            Modelos de Lenguaje por Defecto
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
                <option value="gemini-flash-lite-latest">gemini-flash-lite-latest</option>
                <option value="gemma-4-26b-a4b-it">gemma-4-26b-a4b-it</option>
                <option value="custom">personalizado...</option>
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
                <span className="text-[8px] text-primary font-mono">RRSS</span>
              </label>
              <select
                className="w-full px-2.5 py-1.5 text-[11px] bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
                value={titleModel}
                onChange={(e) => setTitleModel(e.target.value)}
              >
                <option value="gemini-flash-lite-latest">gemini-flash-lite-latest</option>
                <option value="gemma-4-26b-a4b-it">gemma-4-26b-a4b-it</option>
                <option value="custom">personalizado...</option>
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

        {/* Modulación de Expresión y Emociones (IA) */}
        <div className="pt-2.5 border-t border-border/60 space-y-2">
          <div className="text-[10px] font-semibold text-text-primary flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Sparkles size={12} className="text-primary" />
              <span>Modulación y Expresión de Voz (IA)</span>
            </div>
            <span className="text-[8px] font-mono px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
              Fish Audio S2.1
            </span>
          </div>

          <div className="space-y-1.5">
            {/* Inferencia contextual de emociones */}
            <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
              <div className="flex items-center gap-2">
                <Sparkles size={13} className="text-emerald-400" />
                <span className="text-[10px] font-medium text-text-primary block">
                  Inferencia Contextual de Emociones y Prosodia
                </span>
              </div>
              <input
                type="checkbox"
                checked={enableEmotions}
                onChange={(e) => setEnableEmotions(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
              />
            </div>

            {/* Incluir emoción al inicio de cada frase */}
            <div className="space-y-1">
              <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
                <div className="flex items-center gap-2">
                  <Smile size={13} className="text-amber-400" />
                  <span className="text-[10px] font-medium text-text-primary block">
                    Incluir una emoción al inicio de cada frase
                  </span>
                </div>
                <input
                  type="checkbox"
                  checked={initialEmotionPerSentence}
                  onChange={(e) => setInitialEmotionPerSentence(e.target.checked)}
                  className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
                />
              </div>

              {initialEmotionPerSentence && (
                <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-background/50 border border-border/70 text-[10px]">
                  <span className="text-text-muted">Emoción seteada:</span>
                  <select
                    value={initialEmotionTag || "[excited]"}
                    onChange={(e) => setInitialEmotionTag(e.target.value)}
                    className="px-2 py-0.5 text-[10px] bg-background border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary text-text-primary max-w-[210px] truncate"
                  >
                    <optgroup label="Emociones Básicas">
                      {V2V_EMOTIONS.filter((e) => e.category === "Básicas").map((em) => (
                        <option key={em.tag} value={em.tag}>
                          {em.emoji} {em.tag} {em.label}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label="Emociones Avanzadas">
                      {V2V_EMOTIONS.filter((e) => e.category === "Avanzadas").map((em) => (
                        <option key={em.tag} value={em.tag}>
                          {em.emoji} {em.tag} {em.label}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label="Tonos y Modulaciones">
                      {V2V_EMOTIONS.filter((e) => e.category === "Tonos").map((em) => (
                        <option key={em.tag} value={em.tag}>
                          {em.emoji} {em.tag} {em.label}
                        </option>
                      ))}
                    </optgroup>
                  </select>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Pistas a Importar al Timeline de OpenReel */}
        <div className="pt-2.5 border-t border-border/60 space-y-2">
          <div className="text-[10px] font-semibold text-text-primary flex items-center gap-1.5">
            <Sliders size={12} className="text-primary" />
            <span>Pistas de Audio y Video en Línea de Tiempo (Importación)</span>
          </div>

          <div className="space-y-1.5">
            {/* Segmentos de voz sintetizada TTS */}
            <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
              <div className="flex items-center gap-2">
                <Sparkles size={13} className="text-amber-300" />
                <span className="text-[10px] font-medium text-text-primary block">
                  Segmentos TTS (Seqs_trg/*)
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Añadir esta pista al Timeline ahora"
                  disabled={!jobId || videos.length === 0 || importingTrackKey !== null}
                  onClick={() => handleImportSingleTrack("tts_segments")}
                  className="p-1 text-text-muted hover:text-primary transition-colors disabled:opacity-25 disabled:cursor-not-allowed rounded hover:bg-background-elevated"
                >
                  {importingTrackKey === "tts_segments" ? (
                    <Loader2 size={13} className="animate-spin text-primary" />
                  ) : (
                    <FolderInput size={13} />
                  )}
                </button>
                <input
                  type="checkbox"
                  checked={importTTSSegments}
                  onChange={(e) => setImportTTSSegments(e.target.checked)}
                  title="Importación automática al finalizar inferencia"
                  className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
                />
              </div>
            </div>

            {/* Video sin audio */}
            <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
              <div className="flex items-center gap-2">
                <Film size={13} className="text-purple-400" />
                <span className="text-[10px] font-medium text-text-primary block">
                  Pista de Video (video_only.mp4)
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Añadir esta pista al Timeline ahora"
                  disabled={!jobId || videos.length === 0 || importingTrackKey !== null}
                  onClick={() => handleImportSingleTrack("video")}
                  className="p-1 text-text-muted hover:text-primary transition-colors disabled:opacity-25 disabled:cursor-not-allowed rounded hover:bg-background-elevated"
                >
                  {importingTrackKey === "video" ? (
                    <Loader2 size={13} className="animate-spin text-primary" />
                  ) : (
                    <FolderInput size={13} />
                  )}
                </button>
                <input
                  type="checkbox"
                  checked={importMergedVideo}
                  onChange={(e) => setImportMergedVideo(e.target.checked)}
                  title="Importación automática al finalizar inferencia"
                  className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
                />
              </div>
            </div>

            {/* Instrumental */}
            <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
              <div className="flex items-center gap-2">
                <Music size={13} className="text-emerald-400" />
                <span className="text-[10px] font-medium text-text-primary block">
                  Pista Instrumental (no_vocals.wav)
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Añadir esta pista al Timeline ahora"
                  disabled={!jobId || videos.length === 0 || importingTrackKey !== null}
                  onClick={() => handleImportSingleTrack("instrumental")}
                  className="p-1 text-text-muted hover:text-primary transition-colors disabled:opacity-25 disabled:cursor-not-allowed rounded hover:bg-background-elevated"
                >
                  {importingTrackKey === "instrumental" ? (
                    <Loader2 size={13} className="animate-spin text-primary" />
                  ) : (
                    <FolderInput size={13} />
                  )}
                </button>
                <input
                  type="checkbox"
                  checked={importInstrumental}
                  onChange={(e) => setImportInstrumental(e.target.checked)}
                  title="Importación automática al finalizar inferencia"
                  className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
                />
              </div>
            </div>

            {/* Voces originales aisladas */}
            <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
              <div className="flex items-center gap-2">
                <Mic size={13} className="text-amber-400" />
                <span className="text-[10px] font-medium text-text-primary block">
                  Voz original (vocals.wav)
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Añadir esta pista al Timeline ahora"
                  disabled={!jobId || videos.length === 0 || importingTrackKey !== null}
                  onClick={() => handleImportSingleTrack("vocals_original")}
                  className="p-1 text-text-muted hover:text-primary transition-colors disabled:opacity-25 disabled:cursor-not-allowed rounded hover:bg-background-elevated"
                >
                  {importingTrackKey === "vocals_original" ? (
                    <Loader2 size={13} className="animate-spin text-primary" />
                  ) : (
                    <FolderInput size={13} />
                  )}
                </button>
                <input
                  type="checkbox"
                  checked={importOriginalVocals}
                  onChange={(e) => setImportOriginalVocals(e.target.checked)}
                  title="Importación automática al finalizar inferencia"
                  className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
                />
              </div>
            </div>

            {/* Segmentos de voz original recortados paralelos */}
            <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
              <div className="flex items-center gap-2">
                <Layers size={13} className="text-blue-400" />
                <span className="text-[10px] font-medium text-text-primary block">
                  Segmentos originales (Seqs_src/*.wav)
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Añadir esta pista al Timeline ahora"
                  disabled={!jobId || videos.length === 0 || importingTrackKey !== null}
                  onClick={() => handleImportSingleTrack("original_segments")}
                  className="p-1 text-text-muted hover:text-primary transition-colors disabled:opacity-25 disabled:cursor-not-allowed rounded hover:bg-background-elevated"
                >
                  {importingTrackKey === "original_segments" ? (
                    <Loader2 size={13} className="animate-spin text-primary" />
                  ) : (
                    <FolderInput size={13} />
                  )}
                </button>
                <input
                  type="checkbox"
                  checked={importOriginalSegments}
                  onChange={(e) => setImportOriginalSegments(e.target.checked)}
                  title="Importación automática al finalizar inferencia"
                  className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
                />
              </div>
            </div>

            {/* Audio original completo */}
            <div className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover transition-colors">
              <div className="flex items-center gap-2">
                <Radio size={13} className="text-cyan-400" />
                <span className="text-[10px] font-medium text-text-primary block">
                  Pista de Audio original
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Añadir esta pista al Timeline ahora"
                  disabled={!jobId || videos.length === 0 || importingTrackKey !== null}
                  onClick={() => handleImportSingleTrack("original_audio")}
                  className="p-1 text-text-muted hover:text-primary transition-colors disabled:opacity-25 disabled:cursor-not-allowed rounded hover:bg-background-elevated"
                >
                  {importingTrackKey === "original_audio" ? (
                    <Loader2 size={13} className="animate-spin text-primary" />
                  ) : (
                    <FolderInput size={13} />
                  )}
                </button>
                <input
                  type="checkbox"
                  checked={importOriginalAudio}
                  onChange={(e) => setImportOriginalAudio(e.target.checked)}
                  title="Importación automática al finalizar inferencia"
                  className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="flex gap-2 pt-1.5">
          <Button
            onClick={onSaveTokens}
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
            onClick={onClose}
            disabled={isSavingTokens}
            className="text-xs h-8 px-3"
            variant="secondary"
          >
            Cancelar
          </Button>
        </div>
      </div>
    </div>
  );
};
