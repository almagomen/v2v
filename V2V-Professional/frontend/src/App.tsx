import { useEffect, useState, useCallback } from 'react';
import { useProjectStore } from '@/store/useProjectStore';
import { TimelineEditor } from '@/components/Timeline/TimelineEditor';
import { VideoPreview } from '@/components/VideoPlayer/VideoPreview';
import { connectWebSocket } from '@/api/client';
import { Video, Plus, Loader2 } from 'lucide-react';

const SPEAKER_OPTIONS = [
  { value: 'mrbeast_lmnt', label: 'MrBeast (LMNT)' },
  { value: 'Dionisio Schuyler', label: 'Dionisio Schuyler' },
  { value: 'en-US-AndrewMultilingualNeural', label: 'Andrew (Multilingual)' },
  { value: 'Chatterbox', label: 'Chatterbox' },
];

const LANG_OPTIONS = [
  { value: '', label: 'Sin traducción' },
  { value: 'es', label: 'Español' },
  { value: 'en', label: 'Inglés' },
  { value: 'pt', label: 'Portugués' },
  { value: 'fr', label: 'Francés' },
  { value: 'de', label: 'Alemán' },
];

function App() {
  const {
    projects,
    currentProject,
    isLoading,
    progress,
    logs,
    fetchProjects,
    createProject,
    selectProject,
    setProgress,
    addLog,
    clearLogs,
  } = useProjectStore();

  const [url, setUrl] = useState('');
  const [speakerId, setSpeakerId] = useState('mrbeast_lmnt');
  const [translateLang, setTranslateLang] = useState('');

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    if (currentProject) {
      const ws = connectWebSocket(currentProject.id, (data) => {
        if (data.type === 'progress') {
          setProgress(data);
        } else if (data.type === 'log') {
          addLog(data.message);
        } else if (data.type === 'complete') {
          fetchProjects();
        }
      });

      return () => ws.close();
    }
  }, [currentProject, setProgress, addLog, fetchProjects]);

  const handleCreateProject = useCallback(async () => {
    if (!url.trim()) return;
    clearLogs();
    const project = await createProject(url, translateLang || undefined, speakerId);
    if (project) {
      selectProject(project.id);
    }
  }, [url, translateLang, speakerId, createProject, selectProject, clearLogs]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ready': return 'bg-green-500';
      case 'processing':
      case 'downloading': return 'bg-yellow-500';
      case 'error': return 'bg-red-500';
      default: return 'bg-gray-500';
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Video className="w-8 h-8 text-primary" />
            <h1 className="text-2xl font-bold">V2V Professional</h1>
          </div>
        </div>
      </header>

      <div className="flex h-[calc(100vh-73px)]">
        {/* Sidebar - Project List */}
        <aside className="w-80 border-r flex flex-col">
          {/* New Project Form */}
          <div className="p-4 border-b space-y-3">
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="URL de YouTube..."
              className="w-full px-3 py-2 border rounded-md bg-background"
            />
            <div className="flex gap-2">
              <select
                value={translateLang}
                onChange={(e) => setTranslateLang(e.target.value)}
                className="flex-1 px-3 py-2 border rounded-md bg-background text-sm"
              >
                {LANG_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <select
                value={speakerId}
                onChange={(e) => setSpeakerId(e.target.value)}
                className="flex-1 px-3 py-2 border rounded-md bg-background text-sm"
              >
                {SPEAKER_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <button
              onClick={handleCreateProject}
              disabled={isLoading || !url.trim()}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Nuevo Proyecto
            </button>
          </div>

          {/* Project List */}
          <div className="flex-1 overflow-auto p-2">
            {projects.map(project => (
              <button
                key={project.id}
                onClick={() => selectProject(project.id)}
                className={`w-full text-left p-3 rounded-lg mb-2 transition-colors ${
                  currentProject?.id === project.id
                    ? 'bg-primary/10 border border-primary'
                    : 'hover:bg-secondary'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium truncate flex-1">{project.output_name}</span>
                  <span className={`w-2 h-2 rounded-full ${getStatusColor(project.status)}`} />
                </div>
                <p className="text-xs text-muted-foreground truncate mt-1">{project.url}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {project.audio_segments.length} segmentos
                </p>
              </button>
            ))}
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 flex flex-col">
          {currentProject ? (
            <>
              {/* Video Preview */}
              <div className="p-4 border-b">
                <VideoPreview />
              </div>

              {/* Progress & Logs */}
              {progress && (
                <div className="px-4 py-2 border-b bg-muted/30">
                  <div className="flex items-center gap-2 mb-1">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm font-medium">{progress.message}</span>
                    <span className="text-sm text-muted-foreground">
                      {progress.progress ? `${Math.round(progress.progress * 100)}%` : ''}
                    </span>
                  </div>
                  {progress.progress !== undefined && (
                    <div className="h-1 bg-secondary rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary transition-all"
                        style={{ width: `${progress.progress * 100}%` }}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Logs */}
              {logs.length > 0 && (
                <div className="px-4 py-2 border-b max-h-32 overflow-auto bg-muted/20">
                  {logs.slice(-5).map((log, i) => (
                    <p key={i} className="text-xs font-mono text-muted-foreground">{log}</p>
                  ))}
                </div>
              )}

              {/* Timeline Editor */}
              <div className="flex-1">
                <TimelineEditor />
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Video className="w-16 h-16 mx-auto text-muted-foreground mb-4" />
                <h2 className="text-xl font-semibold mb-2">Bienvenido a V2V Professional</h2>
                <p className="text-muted-foreground">
                  Crea un nuevo proyecto o selecciona uno existente para comenzar
                </p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
