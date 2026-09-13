import { JobResponse, OpenCutProject, ProcessRequest, ProjectSummary } from './types';

export class V2VApiClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    // Si no se especifica, busca en localStorage o usa el puerto 8000 en el mismo host
    if (baseUrl) {
      this.baseUrl = baseUrl.replace(/\/$/, '');
    } else if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('v2v_api_url');
      if (saved) {
        this.baseUrl = saved.replace(/\/$/, '');
      } else {
        const protocol = window.location.protocol;
        const hostname = window.location.hostname;
        this.baseUrl = `${protocol}//${hostname}:8000`;
      }
    } else {
      this.baseUrl = 'http://localhost:8000';
    }
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  setBaseUrl(url: string) {
    this.baseUrl = url.replace(/\/$/, '');
    if (typeof window !== 'undefined') {
      localStorage.setItem('v2v_api_url', this.baseUrl);
    }
  }

  async checkHealth(): Promise<{ status: string; gpu_available: boolean; device: string }> {
    const res = await fetch(`${this.baseUrl}/`);
    if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
    return res.json();
  }

  async listSpeakers(): Promise<string[]> {
    try {
      const res = await fetch(`${this.baseUrl}/api/speakers`);
      if (!res.ok) return ['mrbeast', 'Dionisio Schuyler'];
      const data = await res.json();
      return data.speakers || ['mrbeast'];
    } catch {
      return ['mrbeast', 'Dionisio Schuyler'];
    }
  }

  async startProcess(req: ProcessRequest): Promise<JobResponse> {
    const res = await fetch(`${this.baseUrl}/api/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Error al iniciar procesamiento');
    }
    return res.json();
  }

  async getJobStatus(jobId: string) {
    const res = await fetch(`${this.baseUrl}/api/status/${jobId}`);
    if (!res.ok) throw new Error(`Error al obtener estado del job: ${res.statusText}`);
    return res.json();
  }

  async listProjects(): Promise<ProjectSummary[]> {
    const res = await fetch(`${this.baseUrl}/api/projects`);
    if (!res.ok) throw new Error(`Error al listar proyectos: ${res.statusText}`);
    return res.json();
  }

  async getOpenCutProject(projectId: string): Promise<OpenCutProject> {
    const res = await fetch(`${this.baseUrl}/api/projects/${projectId}/opencut`);
    if (!res.ok) throw new Error(`Error al cargar proyecto OpenCut: ${res.statusText}`);
    return res.json();
  }

  getFileUrl(projectId: string, filename: string): string {
    return `${this.baseUrl}/api/projects/${projectId}/files/${filename}`;
  }

  createLogWebSocket(
    jobId: string,
    onLog: (line: string, status?: string, progress?: number) => void,
    onFinish: (status: string, error?: string) => void
  ): WebSocket {
    const wsUrl = this.baseUrl.replace(/^http/, 'ws') + `/api/ws/logs/${jobId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'log') {
          onLog(data.line, data.status, data.progress);
        } else if (data.type === 'finished') {
          onFinish(data.status, data.error);
        }
      } catch {
        onLog(event.data);
      }
    };

    return ws;
  }
}

export const api = new V2VApiClient();
