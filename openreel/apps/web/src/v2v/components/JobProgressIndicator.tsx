import React, { useState } from "react";
import { Terminal, ChevronDown, Copy, Check, Trash2, RefreshCw } from "lucide-react";
import { toast } from "@/stores/notification-store";
import { folderNameFromTitle, importKeyFor } from "../utils/v2v-utils";
import { useColabExportStore } from "../stores/colab-export-store";

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

export interface JobProgressIndicatorProps {
  urlItems: any[];
  importStatusByKey: Record<string, string>;
  isProcessing: boolean;
  onDeleteFolder: (displayName: string, folderName?: string, urlToRemove?: string) => Promise<void>;
  log: string;
  urlLogs: Record<string, string>;
  reprocessUrls?: Set<string>;
  onToggleReprocess?: (url: string) => void;
}

export const JobProgressIndicator: React.FC<JobProgressIndicatorProps> = ({
  urlItems,
  importStatusByKey,
  isProcessing,
  onDeleteFolder,
  log,
  urlLogs,
  reprocessUrls,
  onToggleReprocess,
}) => {
  const [titleDisplayModes, setTitleDisplayModes] = useState<Record<string, number>>({});
  const [copiedUrlKey, setCopiedUrlKey] = useState<string | null>(null);

  const exportLogs = useColabExportStore((s) => s.exportLogs);
  const isLogsOpen = useColabExportStore((s) => s.isLogsOpen);
  const setIsLogsOpen = useColabExportStore((s) => s.setIsLogsOpen);
  const logsTab = useColabExportStore((s) => s.activeLogTab);
  const setLogsTab = useColabExportStore((s) => s.setActiveLogTab);

  const cycleTitleMode = (itemKey: string) => {
    setTitleDisplayModes((prev) => {
      const current = prev[itemKey] || 0;
      return { ...prev, [itemKey]: (current + 1) % 3 };
    });
  };

  return (
    <div className="space-y-3">
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

                  const currentMode = titleDisplayModes[itemKey] || 0;
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
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded ${displayBadgeClass}`}>
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
                          {onToggleReprocess && (
                            <button
                              className={`transition-colors p-1 rounded hover:bg-background-tertiary ${
                                reprocessUrls?.has(it.url)
                                  ? "text-emerald-400 bg-emerald-500/15 ring-1 ring-emerald-500/30"
                                  : "text-text-muted hover:text-emerald-400"
                              }`}
                              title={
                                reprocessUrls?.has(it.url)
                                  ? "Re-inferencia activada (+Versión): al ejecutar se volverá a procesar creando una nueva versión en vez de reimportar (Clic para desactivar)"
                                  : "Activar re-inferencia (+Versión): al volver a ejecutar este enlace se procesará desde cero creando una nueva versión en vez de reimportar"
                              }
                              disabled={isProcessing}
                              onClick={(e) => {
                                e.stopPropagation();
                                onToggleReprocess(it.url);
                              }}
                            >
                              <RefreshCw size={12} />
                            </button>
                          )}
                          <button
                            className="text-text-muted hover:text-red-500 transition-colors p-1 rounded hover:bg-background-tertiary"
                            title="Borrar carpeta y permitir re-intento"
                            disabled={isProcessing}
                            onClick={(e) => {
                              e.stopPropagation();
                              const folder = it.output_name ? folderNameFromTitle(it.output_name) : "";
                              const displayName = currentTitle || it.output_name || it.url;
                              onDeleteFolder(displayName, folder, it.url);
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

      {(log || Object.keys(urlLogs).length > 0 || (exportLogs && exportLogs.length > 0) || isLogsOpen || logsTab === "export") && (
        <div className="space-y-1.5 border border-border/60 rounded-lg p-2 bg-background-tertiary/40">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setIsLogsOpen(!isLogsOpen)}
              className="flex items-center gap-1.5 text-[11px] text-text-muted hover:text-text-primary transition-colors font-medium select-none"
            >
              <Terminal size={12} className="text-text-muted" />
              <span>Logs {logsTab === "process" ? "del proceso" : "de exportación"}</span>
              <ChevronDown
                size={14}
                className={`transition-transform duration-200 text-text-muted ${
                  isLogsOpen ? "rotate-180" : ""
                }`}
              />
            </button>

            {isLogsOpen && (
              <div className="flex items-center gap-1">
                {(logsTab === "export" || (exportLogs && exportLogs.length > 0)) && (
                  <div className="flex items-center rounded border border-border bg-background-secondary p-0.5 text-[9px]">
                    <button
                      type="button"
                      onClick={() => setLogsTab("process")}
                      className={`px-1.5 py-0.5 rounded transition-colors ${
                        logsTab === "process"
                          ? "bg-primary text-primary-foreground font-semibold"
                          : "text-text-muted hover:text-text-primary"
                      }`}
                    >
                      Inferencia
                    </button>
                    <button
                      type="button"
                      onClick={() => setLogsTab("export")}
                      className={`px-1.5 py-0.5 rounded transition-colors ${
                        logsTab === "export"
                          ? "bg-primary text-primary-foreground font-semibold"
                          : "text-text-muted hover:text-text-primary"
                      }`}
                    >
                      Exportación {exportLogs?.length ? `(${exportLogs.length})` : ""}
                    </button>
                  </div>
                )}

                <button
                  type="button"
                  className="text-text-muted hover:text-text-primary transition-colors p-1 rounded hover:bg-background-tertiary"
                  title="Copiar logs al portapapeles"
                  onClick={async () => {
                    const textToCopy =
                      logsTab === "export"
                        ? exportLogs.join("\n")
                        : `${log || ""}${urlItems
                            .map((it: any) => (it.url ? urlLogs[it.url] || "" : ""))
                            .filter(Boolean)
                            .join("\n")}`;
                    try {
                      await navigator.clipboard.writeText(textToCopy);
                      toast.success("Logs copiados", "El contenido de los logs se copió al portapapeles.");
                    } catch {
                      toast.error("Error", "No se pudo copiar los logs.");
                    }
                  }}
                >
                  <Copy size={12} />
                </button>
              </div>
            )}
          </div>

          {isLogsOpen && (
            <pre className="mt-1.5 p-2.5 rounded-lg bg-background-tertiary font-mono text-[10px] min-h-[90px] max-h-[360px] overflow-y-auto overflow-x-hidden resize-y whitespace-pre-wrap break-words border border-border/50 select-text leading-relaxed">
              {(() => {
                if (logsTab === "export") {
                  return exportLogs && exportLogs.length > 0
                    ? exportLogs.join("\n")
                    : "Sin logs de exportación aún.";
                }

                let out = log || "";
                const importText = urlItems
                  .map((it: any) => (it.url ? urlLogs[it.url] || "" : ""))
                  .filter(Boolean)
                  .join("\n");

                return `${out}${importText ? `\n${importText}` : ""}` || "Sin logs aún.";
              })()}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};
