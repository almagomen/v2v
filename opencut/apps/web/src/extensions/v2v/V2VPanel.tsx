import React, { useState, useEffect, useRef } from 'react';
import { api } from './api-client';
import { ProjectSummary, OpenCutProject } from './types';

interface V2VPanelProps {
  onLoadProjectToTimeline?: (project: OpenCutProject) => void;
}

export const V2VPanel: React.FC<V2VPanelProps> = ({ onLoadProjectToTimeline }) => {
  const [apiUrl, setApiUrl] = useState(api.getBaseUrl());
  const [showSettings, setShowSettings] = useState(false);
  const [serverHealthy, setServerHealthy] = useState<boolean | null>(null);
  const [gpuInfo, setGpuInfo] = useState<string>('');

  const [urlsText, setUrlsText] = useState('');
  const [translateLang, setTranslateLang] = useState('es');
  const [speaker, setSpeaker] = useState('mrbeast');
  const [speakersList, setSpeakersList] = useState<string[]>(['mrbeast']);

  const [isProcessing, setIsProcessing] = useState(false);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string>('');
  const [jobProgress, setJobProgress] = useState<number>(0);
  const [jobStep, setJobStep] = useState<string>('');
  const [logs, setLogs] = useState<string[]>([]);

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);

  const logsEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    checkServer();
    refreshProjects();
    loadSpeakers();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const checkServer = async () => {
    try {
      const h = await api.checkHealth();
      setServerHealthy(h.status === 'ok');
      setGpuInfo(h.gpu_available ? `GPU Activa (${h.device})` : 'Modo CPU');
    } catch {
      setServerHealthy(false);
      setGpuInfo('Desconectado');
    }
  };

  const loadSpeakers = async () => {
    try {
      const list = await api.listSpeakers();
      setSpeakersList(list);
    } catch {
      // fallback
    }
  };

  const refreshProjects = async () => {
    setLoadingProjects(true);
    try {
      const list = await api.listProjects();
      setProjects(list);
    } catch {
      // ignore
    } finally {
      setLoadingProjects(false);
    }
  };

  const handleSaveApiUrl = () => {
    api.setBaseUrl(apiUrl);
    setShowSettings(false);
    checkServer();
    refreshProjects();
    loadSpeakers();
  };

  const handleStartProcess = async () => {
    const urls = urlsText
      .split('\n')
      .map((u) => u.trim())
      .filter((u) => u.length > 0);

    if (urls.length === 0) {
      alert('Por favor ingresa al menos una URL de YouTube.');
      return;
    }

    setIsProcessing(true);
    setLogs([]);
    setJobProgress(0);
    setJobStatus('iniciando');
    setJobStep('Enviando solicitud...');

    try {
      const res = await api.startProcess({
        urls,
        translate_lang: translateLang,
        speaker,
      });

      setCurrentJobId(res.job_id);
      setJobStatus(res.status);

      if (wsRef.current) wsRef.current.close();

      wsRef.current = api.createLogWebSocket(
        res.job_id,
        (line, status, progress) => {
          setLogs((prev) => [...prev, line]);
          if (status) setJobStatus(status);
          if (typeof progress === 'number') setJobProgress(progress);
        },
        (finalStatus, error) => {
          setIsProcessing(false);
          setJobStatus(finalStatus);
          if (error) {
            setLogs((prev) => [...prev, `❌ Error: ${error}`]);
          } else {
            setLogs((prev) => [...prev, '✅ Procesamiento completado con éxito.']);
            refreshProjects();
          }
        }
      );
    } catch (err: any) {
      setIsProcessing(false);
      setJobStatus('error');
      alert(`Error al iniciar el proceso: ${err.message}`);
    }
  };

  const handleLoadToTimeline = async (projectId: string) => {
    try {
      const opencutProject = await api.getOpenCutProject(projectId);
      if (onLoadProjectToTimeline) {
        onLoadProjectToTimeline(opencutProject);
      } else {
        alert(`Proyecto "${opencutProject.metadata.name}" cargado.`);
      }
    } catch (err: any) {
      alert(`Error al cargar el proyecto en OpenCut: ${err.message}`);
    }
  };

  return (
    <div className="flex flex-col h-full bg-neutral-900 text-neutral-100 border-r border-neutral-800 w-96 p-4 overflow-y-auto">
      <div className="flex items-center justify-between pb-3 border-b border-neutral-800 mb-4">
        <div className="flex items-center space-x-2">
          <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
          <h2 className="text-lg font-bold tracking-wide">V2V AI Dubbing</h2>
        </div>
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="text-xs text-neutral-400 hover:text-white px-2 py-1 bg-neutral-800 rounded"
        >
          {showSettings ? 'Cerrar' : 'Config API'}
        </button>
      </div>

      {showSettings && (
        <div className="p-3 bg-neutral-800/80 rounded-lg mb-4 text-xs space-y-2 border border-neutral-700">
          <label className="block text-neutral-300 font-semibold">URL del Backend FastAPI:</label>
          <input
            type="text"
            value={apiUrl}
            onChange={(e) => setApiUrl(e.target.value)}
            className="w-full px-2 py-1.5 bg-neutral-950 border border-neutral-700 rounded text-neutral-200"
            placeholder="http://localhost:8000 o url de ngrok"
          />
          <div className="flex justify-between items-center pt-1">
            <span className={serverHealthy ? 'text-emerald-400' : 'text-rose-400'}>
              {serverHealthy ? `● Conectado (${gpuInfo})` : '● Sin conexión'}
            </span>
            <button
              onClick={handleSaveApiUrl}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium"
            >
              Guardar
            </button>
          </div>
        </div>
      )}

      <div className="space-y-4 mb-6">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-neutral-400 mb-1">
            URLs de YouTube (una por línea):
          </label>
          <textarea
            rows={3}
            value={urlsText}
            onChange={(e) => setUrlsText(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-md text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-emerald-500 font-mono text-xs"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-neutral-400 mb-1">Idioma Destino:</label>
            <select
              value={translateLang}
              onChange={(e) => setTranslateLang(e.target.value)}
              className="w-full px-2.5 py-1.5 bg-neutral-950 border border-neutral-800 rounded text-sm text-neutral-200 focus:outline-none focus:border-emerald-500"
            >
              <option value="es">Español (es)</option>
              <option value="en">Inglés (en)</option>
              <option value="pt">Portugués (pt)</option>
              <option value="fr">Francés (fr)</option>
              <option value="None">Sin traducir (Original)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-neutral-400 mb-1">Voz / Speaker:</label>
            <select
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
              className="w-full px-2.5 py-1.5 bg-neutral-950 border border-neutral-800 rounded text-sm text-neutral-200 focus:outline-none focus:border-emerald-500"
            >
              {speakersList.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          onClick={handleStartProcess}
          disabled={isProcessing}
          className={`w-full py-2.5 px-4 rounded-md font-semibold text-sm transition-all shadow-md ${
            isProcessing
              ? 'bg-neutral-800 text-neutral-500 cursor-not-allowed'
              : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white'
          }`}
        >
          {isProcessing ? '⏳ Procesando con IA...' : '🚀 Iniciar Pipeline V2V'}
        </button>
      </div>

      {isProcessing && (
        <div className="p-3 bg-neutral-950 rounded-lg border border-neutral-800 mb-4 space-y-2">
          <div className="flex justify-between text-xs text-neutral-400 font-medium">
            <span>{jobStep || jobStatus}</span>
            <span>{Math.round(jobProgress * 100)}%</span>
          </div>
          <div className="w-full bg-neutral-800 rounded-full h-2 overflow-hidden">
            <div
              className="bg-emerald-500 h-2 transition-all duration-300"
              style={{ width: `${Math.max(5, Math.min(100, jobProgress * 100))}%` }}
            />
          </div>
        </div>
      )}

      {logs.length > 0 && (
        <div className="mb-6">
          <div className="flex justify-between items-center text-xs text-neutral-400 font-semibold mb-1">
            <span>Terminal de Ejecución:</span>
            <button
              onClick={() => setLogs([])}
              className="text-[10px] text-neutral-500 hover:text-neutral-300"
            >
              Limpiar
            </button>
          </div>
          <div className="bg-black/90 border border-neutral-800 rounded-md p-2.5 h-36 overflow-y-auto font-mono text-[11px] text-emerald-400/90 leading-relaxed">
            {logs.map((log, index) => (
              <div key={index} className="whitespace-pre-wrap">
                {log}
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}

      <div className="flex-1">
        <div className="flex items-center justify-between pb-2 mb-2 border-b border-neutral-800">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
            Proyectos Disponibles
          </h3>
          <button
            onClick={refreshProjects}
            className="text-xs text-neutral-400 hover:text-white"
          >
            🔄 Actualizar
          </button>
        </div>

        {loadingProjects ? (
          <p className="text-xs text-neutral-500 italic py-2">Cargando proyectos...</p>
        ) : projects.length === 0 ? (
          <p className="text-xs text-neutral-500 italic py-2">
            No hay proyectos procesados aún.
          </p>
        ) : (
          <div className="space-y-2">
            {projects.map((proj) => (
              <div
                key={proj.id}
                className="p-3 bg-neutral-950 border border-neutral-800/80 rounded-lg hover:border-neutral-700 transition"
              >
                <div className="flex justify-between items-start mb-1">
                  <span className="font-medium text-sm text-neutral-200 truncate pr-2">
                    {proj.name}
                  </span>
                  {proj.has_video && (
                    <span className="text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                      Video Listo
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-neutral-500 mb-2">
                  {proj.segment_count} segmentos • {proj.src_lang?.toUpperCase() || 'ES'}
                </div>
                <button
                  onClick={() => handleLoadToTimeline(proj.id)}
                  className="w-full py-1.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 text-xs font-medium rounded transition flex items-center justify-center space-x-1"
                >
                  <span>🎬 Cargar en Timeline OpenCut</span>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
