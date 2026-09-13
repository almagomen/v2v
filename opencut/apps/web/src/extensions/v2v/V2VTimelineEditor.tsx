import React, { useState, useRef, useEffect } from 'react';
import type { OpenCutProject, OpenCutTrack, OpenCutTimelineElement } from './types';

interface V2VTimelineEditorProps {
  project: OpenCutProject;
  onProjectChange?: (project: OpenCutProject) => void;
}

export const V2VTimelineEditor: React.FC<V2VTimelineEditorProps> = ({
  project: initialProject,
  onProjectChange,
}) => {
  const [project, setProject] = useState<OpenCutProject>(initialProject);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [zoom, setZoom] = useState<number>(50);
  const [selectedElement, setSelectedElement] = useState<OpenCutTimelineElement | null>(null);
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const timelineContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setProject(initialProject);
  }, [initialProject]);

  const activeScene = project.scenes[0] || { tracks: [] };
  const tracks = activeScene.tracks;
  const duration = project.metadata.duration || 60;

  const videoAsset = project.mediaAssets.find((a) => a.type === 'video');
  const videoUrl = videoAsset?.url;

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    } else {
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const seekTo = (time: number) => {
    const boundedTime = Math.max(0, Math.min(duration, time));
    setCurrentTime(boundedTime);
    if (videoRef.current) {
      videoRef.current.currentTime = boundedTime;
    }
  };

  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const newTime = clickX / zoom;
    seekTo(newTime);
  };

  const updateSelectedElement = (updates: Partial<OpenCutTimelineElement>) => {
    if (!selectedElement || !selectedTrackId) return;

    const updatedTracks = tracks.map((track) => {
      if (track.id !== selectedTrackId) return track;
      return {
        ...track,
        elements: track.elements.map((el) => {
          if (el.id !== selectedElement.id) return el;
          const updated = { ...el, ...updates };
          setSelectedElement(updated);
          return updated;
        }),
      };
    });

    const updatedProject: OpenCutProject = {
      ...project,
      scenes: [
        {
          ...activeScene,
          tracks: updatedTracks,
        },
      ],
    };

    setProject(updatedProject);
    if (onProjectChange) onProjectChange(updatedProject);
  };

  const toggleTrackMute = (trackId: string) => {
    const updatedTracks = tracks.map((t) => {
      if (t.id === trackId) {
        return { ...t, muted: !t.muted };
      }
      return t;
    });

    const updatedProject = {
      ...project,
      scenes: [{ ...activeScene, tracks: updatedTracks }],
    };
    setProject(updatedProject);
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 10);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms}`;
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-neutral-950 text-neutral-200 overflow-hidden select-none">
      <div className="h-12 border-b border-neutral-800 px-4 flex items-center justify-between bg-neutral-900/90">
        <div className="flex items-center space-x-3">
          <span className="font-semibold text-sm text-neutral-100">{project.metadata.name}</span>
          <span className="text-xs bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded">
            Timeline OpenCut
          </span>
        </div>

        <div className="flex items-center space-x-2 text-xs">
          {videoUrl && (
            <a
              href={videoUrl}
              download
              className="px-3 py-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 rounded font-medium transition"
            >
              📥 Descargar Video Renderizado
            </a>
          )}
        </div>
      </div>

      <div className="flex-1 flex min-h-0 border-b border-neutral-800">
        <div className="flex-1 flex flex-col items-center justify-center bg-black/60 p-4 relative">
          {videoUrl ? (
            <div className="relative max-w-full max-h-full flex items-center justify-center rounded overflow-hidden shadow-2xl bg-black border border-neutral-800">
              <video
                ref={videoRef}
                src={videoUrl}
                onTimeUpdate={handleTimeUpdate}
                onEnded={() => setIsPlaying(false)}
                className="max-h-[420px] max-w-full rounded"
              />

              {(() => {
                const subTrack = tracks.find((t) => t.type === 'text');
                const activeSub = subTrack?.elements.find(
                  (el) => currentTime >= el.startTime && currentTime <= el.startTime + el.duration
                );
                if (activeSub && activeSub.text) {
                  return (
                    <div className="absolute bottom-6 px-4 py-1.5 bg-black/75 backdrop-blur-sm text-yellow-300 font-semibold text-center text-sm rounded-md max-w-[85%] border border-yellow-500/20 shadow-lg">
                      {activeSub.text}
                    </div>
                  );
                }
                return null;
              })()}
            </div>
          ) : (
            <div className="text-neutral-500 text-sm flex flex-col items-center space-y-2">
              <div className="text-4xl">🎬</div>
              <p>Sin video previsualizado</p>
            </div>
          )}

          <div className="mt-3 flex items-center space-x-4 bg-neutral-900/90 px-4 py-1.5 rounded-full border border-neutral-800 shadow-md">
            <button
              onClick={() => seekTo(0)}
              className="text-neutral-400 hover:text-white text-sm"
              title="Volver al inicio"
            >
              ⏮
            </button>
            <button
              onClick={togglePlay}
              className="w-8 h-8 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white flex items-center justify-center font-bold text-sm shadow"
            >
              {isPlaying ? '⏸' : '▶'}
            </button>
            <button
              onClick={() => seekTo(duration)}
              className="text-neutral-400 hover:text-white text-sm"
              title="Ir al final"
            >
              ⏭
            </button>
            <div className="font-mono text-xs text-neutral-300 pl-2">
              <span className="text-emerald-400 font-bold">{formatTime(currentTime)}</span> /{' '}
              {formatTime(duration)}
            </div>
          </div>
        </div>

        <div className="w-80 bg-neutral-900 border-l border-neutral-800 p-4 flex flex-col overflow-y-auto">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-neutral-400 mb-3 pb-2 border-b border-neutral-800">
            Inspector de Clip
          </h3>

          {selectedElement ? (
            <div className="space-y-4 text-xs">
              <div>
                <label className="block text-neutral-400 mb-1">Nombre:</label>
                <input
                  type="text"
                  value={selectedElement.name}
                  onChange={(e) => updateSelectedElement({ name: e.target.value })}
                  className="w-full px-2 py-1 bg-neutral-950 border border-neutral-700 rounded text-neutral-200"
                />
              </div>

              {selectedElement.type === 'text' && (
                <div>
                  <label className="block text-neutral-400 mb-1">Texto Traducido:</label>
                  <textarea
                    rows={4}
                    value={selectedElement.text || ''}
                    onChange={(e) => updateSelectedElement({ text: e.target.value })}
                    className="w-full px-2.5 py-2 bg-neutral-950 border border-neutral-700 rounded text-neutral-100 text-xs leading-relaxed"
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-neutral-400 mb-1">Inicio (seg):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={selectedElement.startTime}
                    onChange={(e) => updateSelectedElement({ startTime: parseFloat(e.target.value) || 0 })}
                    className="w-full px-2 py-1 bg-neutral-950 border border-neutral-700 rounded text-neutral-200 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-neutral-400 mb-1">Duración (seg):</label>
                  <input
                    type="number"
                    step="0.1"
                    value={selectedElement.duration}
                    onChange={(e) => updateSelectedElement({ duration: parseFloat(e.target.value) || 0.1 })}
                    className="w-full px-2 py-1 bg-neutral-950 border border-neutral-700 rounded text-neutral-200 font-mono"
                  />
                </div>
              </div>

              {selectedElement.type === 'audio' && (
                <div>
                  <label className="block text-neutral-400 mb-1">
                    Volumen: {Math.round((selectedElement.volume ?? 1) * 100)}%
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="1.5"
                    step="0.05"
                    value={selectedElement.volume ?? 1}
                    onChange={(e) => updateSelectedElement({ volume: parseFloat(e.target.value) })}
                    className="w-full accent-emerald-500"
                  />
                </div>
              )}

              <button
                onClick={() => seekTo(selectedElement.startTime)}
                className="w-full py-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 rounded text-xs font-medium"
              >
                🎯 Saltar al clip en el video
              </button>
            </div>
          ) : (
            <p className="text-xs text-neutral-500 italic">
              Haz clic en cualquier clip o subtítulo del timeline para editar sus propiedades y texto.
            </p>
          )}
        </div>
      </div>

      <div className="h-9 bg-neutral-900 border-b border-neutral-800 px-4 flex items-center justify-between text-xs">
        <div className="flex items-center space-x-2">
          <span className="text-neutral-400 font-semibold">Pistas ({tracks.length})</span>
        </div>
        <div className="flex items-center space-x-3">
          <span className="text-neutral-400">Zoom Timeline:</span>
          <button
            onClick={() => setZoom((z) => Math.max(20, z - 15))}
            className="px-2 py-0.5 bg-neutral-800 hover:bg-neutral-700 rounded text-neutral-300"
          >
            -
          </button>
          <span className="font-mono text-neutral-400 w-12 text-center">{zoom}px/s</span>
          <button
            onClick={() => setZoom((z) => Math.min(200, z + 15))}
            className="px-2 py-0.5 bg-neutral-800 hover:bg-neutral-700 rounded text-neutral-300"
          >
            +
          </button>
        </div>
      </div>

      <div
        ref={timelineContainerRef}
        className="flex-1 overflow-x-auto overflow-y-auto bg-neutral-950 p-2 relative"
      >
        <div style={{ width: `${Math.max(800, duration * zoom + 200)}px` }} className="relative">
          <div
            onClick={handleTimelineClick}
            className="h-6 border-b border-neutral-800 relative cursor-pointer bg-neutral-900/40 select-none mb-1"
          >
            {Array.from({ length: Math.ceil(duration / 5) + 1 }).map((_, i) => {
              const sec = i * 5;
              return (
                <div
                  key={sec}
                  className="absolute top-0 bottom-0 border-l border-neutral-700 text-[10px] text-neutral-500 pl-1"
                  style={{ left: `${sec * zoom}px` }}
                >
                  {formatTime(sec)}
                </div>
              );
            })}
          </div>

          <div
            className="absolute top-0 bottom-0 w-0.5 bg-rose-500 pointer-events-none z-30 shadow-md"
            style={{ left: `${currentTime * zoom}px` }}
          >
            <div className="w-3 h-3 bg-rose-500 rotate-45 -ml-1.5 -mt-1 shadow" />
          </div>

          <div className="space-y-1.5">
            {tracks.map((track) => {
              const isVideo = track.type === 'video';
              const isAudio = track.type === 'audio';
              const isText = track.type === 'text';

              const trackColor = isVideo
                ? 'bg-blue-900/30 border-blue-700/50'
                : isAudio
                ? 'bg-emerald-900/30 border-emerald-700/50'
                : 'bg-amber-900/30 border-amber-700/50';

              const badgeColor = isVideo
                ? 'bg-blue-500/20 text-blue-400'
                : isAudio
                ? 'bg-emerald-500/20 text-emerald-400'
                : 'bg-amber-500/20 text-amber-400';

              return (
                <div
                  key={track.id}
                  className={`flex items-center h-16 border rounded bg-neutral-900/60 relative ${
                    track.muted ? 'opacity-40' : ''
                  }`}
                >
                  <div className="w-44 shrink-0 px-3 flex flex-col justify-center border-r border-neutral-800 bg-neutral-900 z-10 h-full">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-xs text-neutral-200 truncate pr-1">
                        {track.name}
                      </span>
                      {isAudio && (
                        <button
                          onClick={() => toggleTrackMute(track.id)}
                          className={`text-[10px] px-1.5 py-0.5 rounded ${
                            track.muted
                              ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                              : 'bg-neutral-800 text-neutral-400'
                          }`}
                        >
                          {track.muted ? 'Muted' : 'Mute'}
                        </button>
                      )}
                    </div>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded w-fit mt-1 ${badgeColor}`}>
                      {track.type.toUpperCase()}
                    </span>
                  </div>

                  <div
                    onClick={handleTimelineClick}
                    className="flex-1 h-full relative cursor-pointer overflow-hidden"
                  >
                    {track.elements.map((elem) => {
                      const isSelected = selectedElement?.id === elem.id;
                      return (
                        <div
                          key={elem.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedElement(elem);
                            setSelectedTrackId(track.id);
                            seekTo(elem.startTime);
                          }}
                          style={{
                            left: `${elem.startTime * zoom}px`,
                            width: `${Math.max(20, elem.duration * zoom)}px`,
                          }}
                          className={`absolute top-1.5 bottom-1.5 rounded p-1.5 border text-xs cursor-pointer transition overflow-hidden ${trackColor} ${
                            isSelected
                              ? 'ring-2 ring-emerald-400 border-emerald-400 z-20'
                              : 'hover:border-neutral-500'
                          }`}
                        >
                          <div className="font-semibold text-[11px] truncate text-neutral-100">
                            {elem.text ? `"${elem.text}"` : elem.name}
                          </div>
                          <div className="text-[9px] text-neutral-400 font-mono mt-0.5">
                            {elem.duration.toFixed(1)}s
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
