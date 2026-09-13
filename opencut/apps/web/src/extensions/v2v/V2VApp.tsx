import React, { useState } from 'react';
import { V2VPanel } from './V2VPanel';
import { V2VTimelineEditor } from './V2VTimelineEditor';
import type { OpenCutProject } from './types';

export const V2VApp: React.FC = () => {
  const [activeProject, setActiveProject] = useState<OpenCutProject | null>(null);

  return (
    <div className="flex h-screen w-screen bg-neutral-950 text-neutral-100 overflow-hidden font-sans">
      {/* Panel Lateral V2V */}
      <V2VPanel onLoadProjectToTimeline={(project) => setActiveProject(project)} />

      {/* Área Principal: Timeline Editor o Placeholder */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {activeProject ? (
          <V2VTimelineEditor
            project={activeProject}
            onProjectChange={(updated) => setActiveProject(updated)}
          />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-neutral-950">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-tr from-emerald-600 to-teal-400 flex items-center justify-center text-4xl shadow-2xl mb-6 ring-1 ring-white/20">
              🎬
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-white mb-2">
              OpenCut + Video2Video
            </h1>
            <p className="text-neutral-400 max-w-md text-sm mb-8 leading-relaxed">
              Traducción y doblaje de videos con Inteligencia Artificial. Pega una URL de YouTube en el panel izquierdo para comenzar, o carga un proyecto ya procesado directamente en el timeline interactivo.
            </p>
            <div className="grid grid-cols-3 gap-4 max-w-lg text-left text-xs">
              <div className="p-3.5 bg-neutral-900 border border-neutral-800 rounded-lg">
                <div className="font-semibold text-neutral-200 mb-1">1. Whisper + Pyannote</div>
                <div className="text-neutral-500">Transcripción y diarización de hablantes.</div>
              </div>
              <div className="p-3.5 bg-neutral-900 border border-neutral-800 rounded-lg">
                <div className="font-semibold text-neutral-200 mb-1">2. Fish Audio TTS</div>
                <div className="text-neutral-500">Clonado de voz ultra-realista s2.1-pro.</div>
              </div>
              <div className="p-3.5 bg-neutral-900 border border-neutral-800 rounded-lg">
                <div className="font-semibold text-neutral-200 mb-1">3. OpenCut Timeline</div>
                <div className="text-neutral-500">Edición completa de pistas y subtítulos.</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
