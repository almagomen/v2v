import type { StateCreator } from "zustand";
import { v2vApi, type Segment } from "../api/v2v-api";
import type { V2VState, SegmentsSlice } from "./v2v-types";
import { loadJobStateFromStorage, saveJobStateToStorage } from "./v2v-storage";

let isFetchingSpeakers = false;

export const createSegmentsSlice: StateCreator<V2VState, [], [], SegmentsSlice> = (set, get) => {
  const saved = loadJobStateFromStorage();
  return {
    segments: saved.segments ?? [],
    selectedRowIndex: null,
    regenStatus: "",
    translateLang: saved.translateLang ?? "None",
    speaker: saved.speaker ?? "mrbeast",
    speakers: [],
    speakerMap: {},
    detectedSpeakers: [],

    setSegments: (segments) =>
      set((state) => {
        const next = typeof segments === "function" ? (segments as (prev: Segment[]) => Segment[])(state.segments) : segments;
        saveJobStateToStorage({ segments: next });
        return { segments: next };
      }),
    setSelectedRowIndex: (selectedRowIndex) => set({ selectedRowIndex }),
    setRegenStatus: (regenStatus) => set({ regenStatus }),
    setTranslateLang: (translateLang) => {
      set({ translateLang });
      saveJobStateToStorage({ translateLang });
    },
    setSpeaker: (speaker) => {
      set({ speaker });
      saveJobStateToStorage({ speaker });
    },

    setSpeakerMap: (speakerMap) => set({ speakerMap }),

    updateSpeakerMapEntry: (origSpeaker, voice) =>
      set((state) => ({
        speakerMap: {
          ...state.speakerMap,
          [origSpeaker]: voice,
        },
      })),

    fetchVideoSpeakers: async (jobId: string, videoIndex: number) => {
      try {
        const res = await v2vApi.getVideoSpeakers(jobId, videoIndex);
        set({
          detectedSpeakers: res.detected_speakers,
          speakerMap: res.speaker_map,
        });
      } catch (err) {
        console.warn("[V2V] Error cargando speakers del video:", err);
      }
    },

    saveVideoSpeakerMap: async (jobId: string, videoIndex: number, map: Record<string, string>) => {
      try {
        const res = await v2vApi.updateSpeakerMap(jobId, videoIndex, map);
        set({
          detectedSpeakers: res.detected_speakers,
          speakerMap: res.speaker_map,
        });
      } catch (err) {
        console.error("[V2V] Error guardando speaker map:", err);
        throw err;
      }
    },

    fetchSpeakers: async () => {
      if (get().speakers.length > 0 || isFetchingSpeakers) return;
      isFetchingSpeakers = true;
      try {
        const list = await v2vApi.getSpeakers();
        set({ speakers: list });
      } catch {
        // ignore
      } finally {
        isFetchingSpeakers = false;
      }
    },
  };
};
