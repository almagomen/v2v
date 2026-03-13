import { useCallback, useRef, useState } from 'react';
import { Timeline, TimelineState } from '@xzdarcy/react-timeline-editor';
import { useProjectStore } from '@/store/useProjectStore';
import { motion } from 'framer-motion';
import { Play, Pause, SkipBack, ZoomIn, ZoomOut, Download, Volume2 } from 'lucide-react';

export function TimelineEditor() {
  const { currentProject, updateSegment, regenerateSegment, exportProject } = useProjectStore();
  const timelineRef = useRef<TimelineState>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [scale, setScale] = useState(1);
  const [selectedSegment, setSelectedSegment] = useState<string | null>(null);
  const [editingText, setEditingText] = useState<string>('');
  const [showEditModal, setShowEditModal] = useState(false);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 100);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
  };

  const convertToTimelineData = useCallback(() => {
    if (!currentProject) return [];

    const videoTrack = {
      id: 'video-track',
      actions: currentProject.video_clips.map((clip) => ({
        id: clip.id,
        start: clip.start_timeline,
        end: clip.end_timeline,
        effectId: 'video',
      })),
    };

    const audioTrack = {
      id: 'audio-track',
      actions: currentProject.audio_segments.map((seg) => ({
        id: seg.id,
        start: seg.start_timeline,
        end: seg.end_timeline,
        effectId: 'audio',
      })),
    };

    return [videoTrack, audioTrack];
  }, [currentProject]);

  const effects = {
    video: {
      id: 'video',
      name: 'Video',
    },
    audio: {
      id: 'audio',
      name: 'Audio Segment',
    },
  };

  const handleTimelineChange = useCallback((data: any[]) => {
    if (!currentProject) return;

    data.forEach((row) => {
      row.actions.forEach((action: { id: string; start: number; end: number }) => {
        if (row.id === 'audio-track') {
          updateSegment(action.id, {
            start_timeline: action.start,
            end_timeline: action.end,
          });
        }
      });
    });
  }, [currentProject, updateSegment]);

  const handleDoubleClickAction = useCallback((action: any, row: any) => {
    if (row.id === 'audio-track') {
      const segment = currentProject?.audio_segments.find((s) => s.id === action.id);
      if (segment) {
        setSelectedSegment(action.id);
        setEditingText(segment.text);
        setShowEditModal(true);
      }
    }
  }, [currentProject]);

  const handleSaveEdit = useCallback(() => {
    if (selectedSegment) {
      updateSegment(selectedSegment, { text: editingText });
      setShowEditModal(false);
      setSelectedSegment(null);
      setEditingText('');
    }
  }, [selectedSegment, editingText, updateSegment]);

  const handlePlayPause = useCallback(() => {
    if (timelineRef.current) {
      if (isPlaying) {
        timelineRef.current.pause();
      } else {
        timelineRef.current.play({ autoEnd: true });
      }
      setIsPlaying(!isPlaying);
    }
  }, [isPlaying]);

  const handleExport = useCallback(() => {
    if (currentProject) {
      exportProject(currentProject.id);
    }
  }, [currentProject, exportProject]);

  if (!currentProject) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-muted-foreground">Selecciona un proyecto para editar</p>
      </div>
    );
  }

  const dirtySegments = currentProject.audio_segments.filter((s) => s.is_dirty);

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b">
        <div className="flex items-center gap-2">
          <button
            onClick={() => timelineRef.current?.setTime(0)}
            className="p-2 hover:bg-secondary rounded-md"
          >
            <SkipBack className="w-4 h-4" />
          </button>
          <button
            onClick={handlePlayPause}
            className="p-2 hover:bg-secondary rounded-md"
          >
            {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </button>
          <span className="text-sm font-mono">{formatTime(currentTime)}</span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setScale((s) => Math.max(0.5, s - 0.25))}
            className="p-2 hover:bg-secondary rounded-md"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-xs">{scale}x</span>
          <button
            onClick={() => setScale((s) => Math.min(4, s + 0.25))}
            className="p-2 hover:bg-secondary rounded-md"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
        </div>

        <button
          onClick={handleExport}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
        >
          <Download className="w-4 h-4" />
          Exportar
        </button>
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-auto">
        <Timeline
          ref={timelineRef}
          editorData={convertToTimelineData()}
          effects={effects}
          onChange={handleTimelineChange}
          scale={scale}
          scaleWidth={100}
          scaleSplitCount={10}
          rowHeight={60}
          gridSnap={true}
          autoScroll={true}
          getActionRender={(action: any, row: any) => {
            const segment = currentProject?.audio_segments.find((s) => s.id === action.id);
            const isDirty = segment?.is_dirty ?? false;
            
            return (
              <div
                className={`h-full flex items-center px-2 text-xs text-white truncate ${
                  row.id === 'video-track' ? 'bg-blue-500' : 'bg-green-500'
                }`}
                style={{ opacity: row.id === 'audio-track' && isDirty ? 0.7 : 1 }}
              >
                {row.id === 'audio-track' ? (
                  <span className="truncate">{segment?.text || 'Sin texto'}</span>
                ) : (
                  <span>Video</span>
                )}
              </div>
            );
          }}
          onDoubleClickAction={handleDoubleClickAction}
        />
      </div>

      {/* Status bar */}
      <div className="px-4 py-2 border-t text-xs text-muted-foreground">
        {dirtySegments.length > 0 && (
          <span className="text-yellow-500">
            {dirtySegments.length} segmento(s) modificado(s) - Regenerar audio
          </span>
        )}
      </div>

      {/* Edit Modal */}
      {showEditModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-card p-6 rounded-lg w-full max-w-md"
          >
            <h3 className="text-lg font-semibold mb-4">Editar Texto del Segmento</h3>
            <textarea
              value={editingText}
              onChange={(e) => setEditingText(e.target.value)}
              className="w-full h-32 p-2 border rounded-md bg-background"
              placeholder="Texto del segmento..."
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setShowEditModal(false)}
                className="px-4 py-2 border rounded-md hover:bg-secondary"
              >
                Cancelar
              </button>
              <button
                onClick={handleSaveEdit}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-md"
              >
                Guardar
              </button>
            </div>
            {selectedSegment && (
              <button
                onClick={() => {
                  regenerateSegment(selectedSegment);
                  setShowEditModal(false);
                }}
                className="w-full mt-2 px-4 py-2 bg-yellow-500 text-white rounded-md hover:bg-yellow-600"
              >
                <Volume2 className="w-4 h-4 inline mr-2" />
                Regenerar Audio
              </button>
            )}
          </motion.div>
        </div>
      )}
    </div>
  );
}
