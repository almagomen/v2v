import { create } from 'zustand';
import { Project, AudioSegment, VideoClip, ProgressMessage } from '@/types';
import { api } from '@/api/client';

interface ProjectState {
  projects: Project[];
  currentProject: Project | null;
  isLoading: boolean;
  error: string | null;
  progress: ProgressMessage | null;
  logs: string[];
  
  fetchProjects: () => Promise<void>;
  createProject: (url: string, translateLang?: string, speakerId?: string) => Promise<Project | null>;
  selectProject: (projectId: string) => Promise<void>;
  updateSegment: (segmentId: string, data: Partial<AudioSegment>) => Promise<void>;
  regenerateSegment: (segmentId: string) => Promise<void>;
  exportProject: (projectId: string) => Promise<void>;
  setProgress: (progress: ProgressMessage | null) => void;
  addLog: (log: string) => void;
  clearLogs: () => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  currentProject: null,
  isLoading: false,
  error: null,
  progress: null,
  logs: [],

  fetchProjects: async () => {
    set({ isLoading: true, error: null });
    try {
      const projects = await api.getProjects();
      set({ projects, isLoading: false });
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false });
    }
  },

  createProject: async (url: string, translateLang?: string, speakerId?: string) => {
    set({ isLoading: true, error: null });
    try {
      const project = await api.createProject({ 
        url, 
        translate_lang: translateLang, 
        speaker_id: speakerId || 'mrbeast_lmnt' 
      });
      set(state => ({ 
        projects: [project, ...state.projects],
        isLoading: false 
      }));
      return project;
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false });
      return null;
    }
  },

  selectProject: async (projectId: string) => {
    set({ isLoading: true, error: null });
    try {
      const project = await api.getProject(projectId);
      set({ currentProject: project, isLoading: false });
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false });
    }
  },

  updateSegment: async (segmentId: string, data: Partial<AudioSegment>) => {
    try {
      const updated = await api.updateSegment(segmentId, data);
      set(state => {
        if (!state.currentProject) return state;
        const segments = state.currentProject.audio_segments.map(
          s => s.id === segmentId ? { ...s, ...updated, is_dirty: true } : s
        );
        return { currentProject: { ...state.currentProject, audio_segments: segments } };
      });
    } catch (error) {
      set({ error: (error as Error).message });
    }
  },

  regenerateSegment: async (segmentId: string) => {
    set({ isLoading: true });
    try {
      await api.regenerateSegment(segmentId);
      const { currentProject } = get();
      if (currentProject) {
        await get().selectProject(currentProject.id);
      }
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false });
    }
  },

  exportProject: async (projectId: string) => {
    set({ isLoading: true });
    try {
      await api.exportProject(projectId);
    } catch (error) {
      set({ error: (error as Error).message, isLoading: false });
    }
  },

  setProgress: (progress: ProgressMessage | null) => {
    set({ progress });
  },

  addLog: (log: string) => {
    set(state => ({ logs: [...state.logs, log] }));
  },

  clearLogs: () => {
    set({ logs: [] });
  },
}));
