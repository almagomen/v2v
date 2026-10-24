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
} from "lucide-react";
import { Button } from "@openreel/ui";
import { v2vApi } from "../api/v2v-api";
import { useV2VStore } from "../stores/v2v-store";

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

  const {
    enableEmotions,
    setEnableEmotions,
    importInstrumental,
    setImportInstrumental,
    importOriginalAudio,
    setImportOriginalAudio,
    importOriginalVocals,
    setImportOriginalVocals,
    importOriginalSegments,
    setImportOriginalSegments,
    importMergedVideo,
    setImportMergedVideo,
  } = useV2VStore();

  const handleTestConnection = async () => {
    setIsTestingBackend(true);
    setTestResult(null);
    try {
      v2vApi.setBackendUrl(backendUrl);
      const res = await v2vApi.checkHealth();
      if (res.ok) {
        let syncedMsg = "Conexión exitosa con el backend (GPU activa)";
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
            syncedMsg += " — Tokens de Fish Audio y Google sincronizados automáticamente desde Kaggle Secrets.";
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
            placeholder="https://xxxx.trycloudflare.com (o vacío para localhost/web)"
            value={backendUrl}
            onChange={(e) => {
              setBackendUrl(e.target.value);
              setTestResult(null);
            }}
          />
          <p className="text-[9px] text-text-muted leading-tight">
            OpenReel Desktop: URL Cloudflare | Versión Web: automático.
          </p>
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
                <option value="gemini-flash-lite-latest">gemini-flash-lite-latest (Recomendado)</option>
                <option value="gemma-4-26b-a4b-it">gemma-4-26b-a4b-it (Fallback)</option>
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
                <span className="text-[8px] text-primary font-mono">RRSS</span>
              </label>
              <select
                className="w-full px-2.5 py-1.5 text-[11px] bg-background border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
                value={titleModel}
                onChange={(e) => setTitleModel(e.target.value)}
              >
                <option value="gemini-flash-lite-latest">gemini-flash-lite-latest (Recomendado)</option>
                <option value="gemma-4-26b-a4b-it">gemma-4-26b-a4b-it (Fallback)</option>
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

          <label className="flex items-start gap-2.5 p-2 rounded-lg bg-background border border-border hover:border-border-hover cursor-pointer transition-colors">
            <input
              type="checkbox"
              checked={enableEmotions}
              onChange={(e) => setEnableEmotions(e.target.checked)}
              className="mt-0.5 rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
            />
            <div className="flex-1 text-[10px] leading-tight">
              <span className="font-medium text-text-primary block">
                Inferencia Contextual de Emociones y Prosodia
              </span>
            </div>
          </label>
        </div>

        {/* Pistas a Importar al Timeline de OpenReel */}
        <div className="pt-2.5 border-t border-border/60 space-y-2">
          <div className="text-[10px] font-semibold text-text-primary flex items-center gap-1.5">
            <Sliders size={12} className="text-primary" />
            <span>Pistas de Audio y Video en Línea de Tiempo (Importación)</span>
          </div>

          <div className="space-y-1.5">
            {/* Instrumental */}
            <label className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover cursor-pointer transition-colors">
              <div className="flex items-center gap-2">
                <Music size={13} className="text-emerald-400" />
                <div>
                  <span className="text-[10px] font-medium text-text-primary block">
                    Pista Instrumental aislada (no_vocals.wav)
                  </span>
                  <span className="text-[9px] text-text-muted block">
                    Música y efectos de fondo extraídos con Demucs (Recomendado)
                  </span>
                </div>
              </div>
              <input
                type="checkbox"
                checked={importInstrumental}
                onChange={(e) => setImportInstrumental(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
              />
            </label>

            {/* Voces originales aisladas */}
            <label className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover cursor-pointer transition-colors">
              <div className="flex items-center gap-2">
                <Mic size={13} className="text-amber-400" />
                <div>
                  <span className="text-[10px] font-medium text-text-primary block">
                    Voces originales aisladas (vocals.wav)
                  </span>
                  <span className="text-[9px] text-text-muted block">
                    Pista de voz original (silenciada por defecto para referencia)
                  </span>
                </div>
              </div>
              <input
                type="checkbox"
                checked={importOriginalVocals}
                onChange={(e) => setImportOriginalVocals(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
              />
            </label>

            {/* Segmentos de voz original recortados paralelos */}
            <label className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover cursor-pointer transition-colors">
              <div className="flex items-center gap-2">
                <Layers size={13} className="text-blue-400" />
                <div>
                  <span className="text-[10px] font-medium text-text-primary block">
                    Segmentos originales en pistas paralelas (Seqs_src/*.wav)
                  </span>
                  <span className="text-[9px] text-text-muted block">
                    Clips originales alineados en el timeline (silenciados) para comparar con la traducción en paralelo
                  </span>
                </div>
              </div>
              <input
                type="checkbox"
                checked={importOriginalSegments}
                onChange={(e) => setImportOriginalSegments(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
              />
            </label>

            {/* Audio original completo */}
            <label className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover cursor-pointer transition-colors">
              <div className="flex items-center gap-2">
                <Radio size={13} className="text-cyan-400" />
                <div>
                  <span className="text-[10px] font-medium text-text-primary block">
                    Audio original completo (original_audio.webm)
                  </span>
                  <span className="text-[9px] text-text-muted block">
                    Audio completo sin separar del video original (silenciado)
                  </span>
                </div>
              </div>
              <input
                type="checkbox"
                checked={importOriginalAudio}
                onChange={(e) => setImportOriginalAudio(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
              />
            </label>

            {/* Video renderizado */}
            <label className="flex items-center justify-between p-2 rounded-lg bg-background border border-border hover:border-border-hover cursor-pointer transition-colors">
              <div className="flex items-center gap-2">
                <Film size={13} className="text-purple-400" />
                <div>
                  <span className="text-[10px] font-medium text-text-primary block">
                    Video renderizado con audio (merged.mp4)
                  </span>
                  <span className="text-[9px] text-text-muted block">
                    Pista adicional de video con audio combinado
                  </span>
                </div>
              </div>
              <input
                type="checkbox"
                checked={importMergedVideo}
                onChange={(e) => setImportMergedVideo(e.target.checked)}
                className="rounded border-border text-primary focus:ring-primary w-3.5 h-3.5 cursor-pointer accent-primary"
              />
            </label>
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
