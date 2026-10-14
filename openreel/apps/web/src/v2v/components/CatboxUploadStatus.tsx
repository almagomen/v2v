import React from "react";
import { CheckCircle, Link as LinkIcon, Copy, ExternalLink } from "lucide-react";
import type { CatboxVideoResult } from "../stores/colab-export-store";

export interface CatboxUploadStatusProps {
  catboxUrl?: string | null;
  catboxVideos: CatboxVideoResult[];
  isBatch?: boolean;
  onCopyUrl: (url: string, index?: number) => void;
  copiedIndex: number | null;
}

export const CatboxUploadStatus: React.FC<CatboxUploadStatusProps> = ({
  catboxUrl,
  catboxVideos,
  isBatch = false,
  onCopyUrl,
  copiedIndex,
}) => {
  if (!isBatch && catboxUrl) {
    return (
      <div className="space-y-2 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
        <div className="flex items-center gap-2">
          <CheckCircle size={14} className="text-green-400" />
          <span className="text-xs text-green-300 font-medium">Video subido a Catbox</span>
          <span className="text-[10px] text-text-muted ml-auto">Expira en 24h</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex-1 flex items-center gap-2 px-2 py-1.5 bg-background-secondary rounded border border-border">
            <LinkIcon size={12} className="text-text-muted shrink-0" />
            <span className="text-[10px] text-text-primary truncate flex-1">{catboxUrl}</span>
          </div>
          <button
            onClick={() => onCopyUrl(catboxUrl)}
            className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors"
            title="Copiar enlace"
          >
            {copiedIndex !== null ? (
              <CheckCircle size={12} className="text-green-400" />
            ) : (
              <Copy size={12} className="text-text-muted" />
            )}
          </button>
          <a
            href={catboxUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors"
            title="Abrir enlace"
          >
            <ExternalLink size={12} className="text-text-muted" />
          </a>
        </div>
      </div>
    );
  }

  if (isBatch && catboxVideos.length > 0) {
    return (
      <div className="space-y-2 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
        <div className="flex items-center gap-2 mb-2">
          <CheckCircle size={14} className="text-green-400" />
          <span className="text-xs text-green-300 font-medium">
            {catboxVideos.length} video(s) subido(s) a Catbox
          </span>
          <span className="text-[10px] text-text-muted ml-auto">Expira en 24h</span>
        </div>
        <div className="space-y-1.5 max-h-48 overflow-y-auto">
          {catboxVideos.map((v, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="flex-1 min-w-0">
                <p className="text-[10px] text-text-secondary truncate">{v.filename}</p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <LinkIcon size={10} className="text-text-muted shrink-0" />
                  <span className="text-[10px] text-text-primary truncate">{v.url}</span>
                </div>
              </div>
              <button
                onClick={() => onCopyUrl(v.url, i)}
                className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors shrink-0"
                title="Copiar enlace"
              >
                {copiedIndex === i ? (
                  <CheckCircle size={12} className="text-green-400" />
                ) : (
                  <Copy size={12} className="text-text-muted" />
                )}
              </button>
              <a
                href={v.url}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 bg-background-secondary border border-border rounded hover:bg-background-tertiary transition-colors shrink-0"
                title="Abrir enlace"
              >
                <ExternalLink size={12} className="text-text-muted" />
              </a>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return null;
};
