import axios from 'axios';
import { Project, ProjectCreate, AudioSegment, VideoClip } from '@/types';

const BASE_URL = '/api';

export const api = {
  async getProjects(): Promise<Project[]> {
    const res = await axios.get(`${BASE_URL}/projects`);
    return res.data;
  },

  async getProject(id: string): Promise<Project> {
    const res = await axios.get(`${BASE_URL}/projects/${id}`);
    return res.data;
  },

  async createProject(data: ProjectCreate): Promise<Project> {
    const res = await axios.post(`${BASE_URL}/projects`, data);
    return res.data;
  },

  async deleteProject(id: string): Promise<void> {
    await axios.delete(`${BASE_URL}/projects/${id}`);
  },

  async updateSegment(id: string, data: Partial<AudioSegment>): Promise<AudioSegment> {
    const res = await axios.patch(`${BASE_URL}/segments/${id}`, data);
    return res.data;
  },

  async regenerateSegment(id: string): Promise<{ audio_path: string }> {
    const res = await axios.post(`${BASE_URL}/segments/${id}/regenerate`);
    return res.data;
  },

  async exportProject(id: string): Promise<{ message: string }> {
    const res = await axios.post(`${BASE_URL}/projects/${id}/export`);
    return res.data;
  },

  async getDownloadUrl(id: string): Promise<{ video_url: string }> {
    const res = await axios.get(`${BASE_URL}/projects/${id}/download`);
    return res.data;
  },
};

export function connectWebSocket(
  projectId: string,
  onMessage: (data: any) => void
): WebSocket {
  const ws = new WebSocket(`ws://localhost:8000/ws/${projectId}`);
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    onMessage(data);
  };
  
  ws.onerror = (error) => {
    console.error('WebSocket error:', error);
  };
  
  return ws;
}
