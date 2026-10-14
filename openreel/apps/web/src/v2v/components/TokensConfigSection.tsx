import React, { useState } from "react";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { Button } from "@openreel/ui";

export interface TokensConfigSectionProps {
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

  return (
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
                <span className="text-[8px] text-primary font-mono">TikTok</span>
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
