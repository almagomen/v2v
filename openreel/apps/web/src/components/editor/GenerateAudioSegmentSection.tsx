import React, { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2, RefreshCw, X } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@openreel/ui";

import { v2vApi } from "../../lib/v2v-api";
import { useProjectStore } from "../../stores/project-store";
import { useV2VStore } from "../../stores/v2v-store";
import { importMultipleMediaIntoProject } from "../../utils/import-media-into-project";
import { toSafeToken } from "../../utils/v2v-utils";

export const GenerateAudioSegmentSection: React.FC<{
  folder: string;
  onClose: () => void;
}> = ({ folder, onClose }) => {
  const { forceSave } = useProjectStore();
  const { speakers, fetchSpeakers, getFolderRef } = useV2VStore();

  useEffect(() => {
    if (speakers.length === 0) {
      fetchSpeakers();
    }
  }, [speakers.length, fetchSpeakers]);

  const folderRef = getFolderRef(folder);

  const [selectedVoice, setSelectedVoice] = useState<string>("");
  const [segmentText, setSegmentText] = useState<string>("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const getNextSegmentIndex = useCallback((items: any[]) => {
    let maxIdx = 0;
    for (const item of items) {
      const idx = item.name.indexOf("/");
      if (idx <= 0) continue;
      if (item.name.slice(0, idx) !== folder) continue;
      const displayName = item.name.slice(idx + 1);
      const match = displayName.match(/^gen_.+_(\d{3})\.wav$/);
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
      const speakerToken = toSafeToken(
        speakers.find((s) => s.value === selectedVoice)?.label || selectedVoice
      );

      const regenBlob = await v2vApi.generateNewAudioSegment(
        folderRef.jobId,
        folderRef.videoIndex,
        segmentText,
        selectedVoice
      );

      const currentProject = useProjectStore.getState().project;
      const segIdx = getNextSegmentIndex(currentProject.mediaLibrary.items);

      const newFileName = `gen_${speakerToken}_${String(segIdx).padStart(3, "0")}.wav`;
      const newMediaName = `${folder}/${newFileName}`;

      const file = new File([regenBlob], newMediaName, { type: "audio/wav" });

      const batchRes = await importMultipleMediaIntoProject(
        currentProject,
        [file],
        { quick: false }
      );

      if (!batchRes.success) {
        throw new Error("Error al importar el audio generado");
      }

      useProjectStore.setState({ project: batchRes.project });
      await forceSave();

      setStatus(`Segmento "${newFileName}" generado y añadido a Media`);
      setSegmentText("");

      setTimeout(() => {
        onClose();
      }, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al generar audio");
    } finally {
      setIsGenerating(false);
    }
  }, [segmentText, selectedVoice, folderRef, speakers, folder, getNextSegmentIndex, forceSave, onClose]);

  return (
    <div className="space-y-3 p-3 bg-background-secondary border border-border rounded-lg">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RefreshCw size={14} className="text-primary" />
          <span className="text-[11px] font-medium text-text-primary">Generar Segmento de Audio</span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-background-tertiary text-text-muted"
        >
          <X size={14} />
        </button>
      </div>

      <div className="space-y-2">
        <label className="text-[10px] text-text-secondary block mb-1">
          Speaker (voz LMNT)
        </label>
        <Select
          value={selectedVoice}
          onValueChange={(v) => setSelectedVoice(v)}
          disabled={isGenerating || speakers.length === 0}
        >
          <SelectTrigger className="w-full bg-background-tertiary border-border text-text-primary text-[11px]">
            <SelectValue placeholder={speakers.length === 0 ? "Cargando voces..." : "Seleccionar voz..."} />
          </SelectTrigger>
          <SelectContent className="bg-background-secondary border-border">
            {speakers.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-[10px] text-text-secondary block mb-1">
          Texto
        </label>
        <textarea
          value={segmentText}
          onChange={(e) => setSegmentText(e.target.value)}
          className="w-full min-h-[80px] px-3 py-2 bg-background-tertiary border border-border rounded-lg text-xs text-text-primary resize-none focus:outline-none focus:border-primary"
          placeholder="Escribe el texto para generar el audio..."
          disabled={isGenerating}
        />
      </div>

      <div className="space-y-2">
        {error && (
          <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30 rounded-lg">
            <AlertCircle size={14} className="text-red-400" />
            <span className="text-[10px] text-red-400">{error}</span>
          </div>
        )}

        {status && (
          <div className="flex items-center gap-2 p-2 bg-green-500/10 border border-green-500/30 rounded-lg">
            <span className="text-[10px] text-green-400">{status}</span>
          </div>
        )}

        <button
          onClick={handleGenerate}
          disabled={isGenerating || !segmentText.trim() || !selectedVoice}
          className="w-full py-2.5 bg-primary hover:bg-primary/80 text-black rounded-lg text-[11px] font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isGenerating ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Generando...
            </>
          ) : (
            <>
              <RefreshCw size={14} />
              Generar Audio
            </>
          )}
        </button>
      </div>
    </div>
  );
};
