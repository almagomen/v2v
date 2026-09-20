import React, { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Button,
} from "@openreel/ui";

import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";
import { importMultipleMediaIntoProject } from "../../utils/import-media-into-project";
import { toSafeToken } from "../../utils/v2v-utils";

export const GenerateAudioSegmentSection: React.FC<{
  folder: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}> = ({ folder, open, onOpenChange }) => {
  const { forceSave } = useProjectStore();
  const { speakers, fetchSpeakers, getFolderRef, syncFolderAssets } = useV2VStore();

  useEffect(() => {
    if (open && speakers.length === 0) {
      fetchSpeakers();
    }
  }, [open, speakers.length, fetchSpeakers]);

  // Obtenemos la referencia del folder cada vez que abre o cambia
  const folderRef = getFolderRef(folder);

  const [selectedVoice, setSelectedVoice] = useState<string>("");
  const [segmentText, setSegmentText] = useState<string>("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  // Cuenta el máximo índice de segmentos ya generados por AI Generator en esta carpeta
  // Ahora el backend usa prefijo tts_ para todo, por lo que buscamos ambos por compatibilidad
  const getNextSegmentIndex = useCallback((items: any[]) => {
    let maxIdx = 0;
    for (const item of items) {
      const idx = item.name.indexOf("/");
      if (idx <= 0) continue;
      if (item.name.slice(0, idx) !== folder) continue;
      
      const displayName = item.name.slice(idx + 1);
      // Verifica gen_ (legacy) y tts_ (nuevo estándar)
      const match = displayName.match(/^(?:gen_|tts_).+_(\d{3})\.wav$/);
      if (match) {
        const idxNum = parseInt(match[1], 10);
        if (!Number.isNaN(idxNum) && idxNum > maxIdx) {
          maxIdx = idxNum;
        }
      }
    }
    return maxIdx + 1;
  }, [folder]);

  const handleGenerate = useCallback(async () => {
    if (!segmentText.trim()) {
      setError("El texto no puede estar vacío");
      return;
    }

    if (!selectedVoice) {
      setError("Selecciona una voz");
      return;
    }

    if (!folderRef) {
      setError("No se encontró referencia del job para esta carpeta");
      return;
    }

    setIsGenerating(true);
    setError(null);
    setStatus(null);

    try {
      // Llamar al backend — devuelve el archivo con su nombre real en Content-Disposition
      const apiBase = (import.meta.env.VITE_V2V_API_URL || "").replace(/\/$/, "");
      const isLocalhostLikeHost = (h: string) => h === "localhost" || h === "127.0.0.1" || h === "0.0.0.0";
      const apiBaseTargetsLocalhost = (base: string) => /\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?/i.test(base);
      const resolveUrl = (path: string) => {
        if (apiBase && typeof window !== "undefined") {
          if (apiBaseTargetsLocalhost(apiBase) && !isLocalhostLikeHost(window.location.hostname)) return path;
          return `${apiBase}${path}`;
        }
        return path;
      };

      const res = await fetch(resolveUrl("/api/generate-audio-segment"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: folderRef.jobId,
          video_index: folderRef.videoIndex,
          text: segmentText,
          speaker: selectedVoice,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Error al generar audio");
      }

      const regenBlob = await res.blob();

      // Leer el nombre real que asignó el backend desde Content-Disposition
      let backendFileName: string | null = null;
      const cd = res.headers.get("content-disposition") || "";
      const cdMatch = cd.match(/filename[^;=\n]*=(?:(['"])([\s\S]*?)\1|([^;\n]*))/i);
      if (cdMatch) {
        backendFileName = (cdMatch[2] || cdMatch[3] || "").trim();
      }

      const speakerLabel = speakers.find((s) => s.value === selectedVoice)?.label || selectedVoice;
      const speakerToken = toSafeToken(speakerLabel);

      // Si el backend devuelve el nombre, lo usamos; si no, construimos con el mismo patrón tts_
      const currentProject = useProjectStore.getState().project;
      const segIdx = getNextSegmentIndex(currentProject.mediaLibrary.items);
      const fallbackName = `tts_${speakerToken}_${String(segIdx).padStart(3, "0")}.wav`;
      const newFileName = backendFileName || fallbackName;
      const logicalName = `${folder}/${newFileName}`;

      const file = new File([regenBlob], logicalName, { type: "audio/wav" });

      // Importar a la biblioteca de medios del proyecto actual
      const batchRes = await importMultipleMediaIntoProject(
        currentProject,
        [file],
        { quick: false }
      );

      if (!batchRes.success || !batchRes.project) {
        throw new Error("Error al importar el audio generado");
      }

      useProjectStore.setState({ project: batchRes.project });
      await forceSave();

      // Sincronizar activos con el backend para que Colab reconozca el nuevo archivo
      await syncFolderAssets(folderRef.jobId, folderRef.videoIndex, folder);

      setStatus(`✅ ¡Generado! "${newFileName}"`);
      setSegmentText("");

      setTimeout(() => {
        onOpenChange(false);
      }, 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al generar audio");
    } finally {
      setIsGenerating(false);
    }
  }, [segmentText, selectedVoice, folderRef, speakers, folder, getNextSegmentIndex, forceSave, onOpenChange, syncFolderAssets]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md bg-background-secondary border-border shadow-2xl p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-2 border-b border-white/5 bg-gradient-to-br from-primary/10 to-transparent">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center text-primary shadow-inner">
              <Sparkles size={20} />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold text-white tracking-tight">AI Audio Generator</DialogTitle>
              <DialogDescription className="text-xs text-text-muted mt-0.5">
                Genera nuevos segmentos de voz usando Fish Audio (s2.1-pro-free).
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="p-6 space-y-6">
          <div className="space-y-2">
            <label className="text-[11px] font-semibold text-text-secondary uppercase tracking-wider">
              Voz del Speaker
            </label>
            <Select
              value={selectedVoice}
              onValueChange={(v) => setSelectedVoice(v)}
              disabled={isGenerating || speakers.length === 0}
            >
              <SelectTrigger className="w-full h-11 bg-background-tertiary border-white/5 text-text-primary text-sm hover:border-primary/50 transition-colors shadow-sm">
                <SelectValue placeholder={speakers.length === 0 ? "Cargando voces..." : "Seleccionar una voz..."} />
              </SelectTrigger>
              <SelectContent className="bg-background-secondary border-border border-white/10 shadow-2xl max-h-[300px]">
                {speakers.map((s) => (
                  <SelectItem key={s.value} value={s.value} className="focus:bg-primary/20 focus:text-white cursor-pointer">
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <label className="text-[11px] font-semibold text-text-secondary uppercase tracking-wider">
              Texto a generar
            </label>
            <textarea
              value={segmentText}
              onChange={(e) => setSegmentText(e.target.value)}
              className="w-full min-h-[120px] px-4 py-3 bg-background-tertiary border border-white/5 rounded-xl text-sm text-text-primary resize-none focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-all placeholder:text-text-muted/50"
              placeholder="Escribe el guion aquí..."
              disabled={isGenerating}
            />
          </div>

          {error && (
            <div className="flex items-center gap-3 p-3 bg-red-500/10 border border-red-500/20 rounded-xl animate-in fade-in slide-in-from-top-2">
              <AlertCircle size={18} className="text-red-400 shrink-0" />
              <span className="text-xs text-red-400 font-medium">{error}</span>
            </div>
          )}

          {status && (
            <div className="flex items-center gap-3 p-3 bg-green-500/10 border border-green-500/20 rounded-xl animate-in fade-in slide-in-from-top-2">
              <div className="w-5 h-5 rounded-full bg-green-500/20 flex items-center justify-center">
                <div className="w-2 h-2 bg-green-400 rounded-full" />
              </div>
              <span className="text-xs text-green-400 font-semibold">{status}</span>
            </div>
          )}
        </div>

        <div className="p-6 pt-2 pb-8 flex gap-3">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isGenerating}
            className="flex-1 h-11 border-white/5 hover:bg-white/5 text-text-secondary text-sm font-semibold"
          >
            Cancelar
          </Button>
          <Button
            onClick={handleGenerate}
            disabled={isGenerating || !segmentText.trim() || !selectedVoice}
            className="flex-[2] h-11 bg-primary hover:bg-primary/90 text-black text-sm font-bold shadow-lg shadow-primary/20 flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          >
            {isGenerating ? (
              <>
                <Loader2 size={18} className="animate-spin" />
                Procesando Audio...
              </>
            ) : (
              <>
                <RefreshCw size={18} />
                Generar Audio
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
