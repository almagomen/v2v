import { create } from "zustand";

interface AudioCacheState {
  invalidationTrigger: number;
  invalidateAudio: () => void;
}

const audioCacheStore = create<AudioCacheState>((set) => ({
  invalidationTrigger: 0,

  invalidateAudio: () => {
    set((state) => ({ invalidationTrigger: state.invalidationTrigger + 1 }));
  },
}));

export const useAudioCacheStore = audioCacheStore;

export function invalidateAudioCache(_mediaId: string): void {
  audioCacheStore.getState().invalidateAudio();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("openreel:preview-invalidate"));
  }
}
