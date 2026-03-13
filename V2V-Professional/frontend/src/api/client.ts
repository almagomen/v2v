import axios from 'axios';
import { Project, ProjectCreate, AudioSegment } from '@/types';

// Dynamic base URL that works in both local and production
const getBaseUrl = () => {
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.host}/api`;
  }
  return '/api';
};

export const api = {
  async getProjects(): Promise<Project[]> {
    const res = await axios.get(`${getBaseUrl()}/projects`);
    return res.data;
  },

  async getProject(id: string): Promise<Project> {
    const res = await axios.get(`${getBaseUrl()}/projects/${id}`);
    return res.data;
  },

  async createProject(data: ProjectCreate): Promise<Project> {
    const res = await axios.post(`${getBaseUrl()}/projects`, data);
    return res.data;
  },

  async deleteProject(id: string): Promise<void> {
    await axios.delete(`${getBaseUrl()}/projects/${id}`);
  },

  async updateSegment(id: string, data: Partial<AudioSegment>): Promise<AudioSegment> {
    const res = await axios.patch(`${getBaseUrl()}/segments/${id}`, data);
    return res.data;
  },

  async regenerateSegment(id: string): Promise<{ audio_path: string }> {
    const res = await axios.post(`${getBaseUrl()}/segments/${id}/regenerate`);
    return res.data;
  },

  async exportProject(id: string): Promise<{ message: string }> {
    const res = await axios.post(`${getBaseUrl()}/projects/${id}/export`);
    return res.data;
  },

  async getDownloadUrl(id: string): Promise<{ video_url: string }> {
    const res = await axios.get(`${getBaseUrl()}/projects/${id}/download`);
    return res.data;
  },
};

export function connectWebSocket(
  projectId: string,
  onMessage: (data: any) => void
): WebSocket {
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${window.location.host}/api/ws/${projectId}`;
  
  console.log('Connecting to WebSocket:', wsUrl);
  
  const ws = new WebSocket(wsUrl);
  
  ws.onopen = () => {
    console.log('WebSocket connected');
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (e) {
      console.error('Failed to parse WebSocket message:', e);
    }
  };
  
  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
  };
  
  ws.onclose = (event) => {
    console.log('WebSocket closed:', event.code, event.reason);
  };
  
  return ws;
}
