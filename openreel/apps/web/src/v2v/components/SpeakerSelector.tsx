import React from "react";
import {
  EMOTION_CATEGORIES,
  getEmotionsByCategory,
  formatEmotionLabel,
} from "../utils/v2v-emotions";

export interface SpeakerSelectorProps {
  speaker: string;
  setSpeaker: (speaker: string) => void;
  speakers: Array<{ label: string; value: string }>;
  initialEmotion: string;
  setInitialEmotion: (emotion: string) => void;
  disabled?: boolean;
}

export const SpeakerSelector: React.FC<SpeakerSelectorProps> = ({
  speaker,
  setSpeaker,
  speakers,
  initialEmotion,
  setInitialEmotion,
  disabled = false,
}) => {
  return (
    <>
      <div>
        <label className="text-[10px] text-text-muted block mb-1">Voz</label>
        <select
          className="w-full px-2.5 py-2 text-xs bg-background-tertiary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
          value={speaker}
          onChange={(e) => setSpeaker(e.target.value)}
          disabled={disabled}
        >
          {speakers.length > 0 ? (
            speakers.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))
          ) : (
            <>
              <option value="mrbeast">mrbeast</option>
              <option value="default_fish">default_fish</option>
            </>
          )}
        </select>
      </div>
      <div>
        <label className="text-[10px] text-text-muted block mb-1 flex items-center justify-between">
          <span>Emoción</span>
          <span className="text-[9px] text-primary">S2.1</span>
        </label>
        <select
          className="w-full px-2 py-2 text-xs bg-background-tertiary border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-primary truncate"
          value={initialEmotion}
          onChange={(e) => setInitialEmotion(e.target.value)}
          disabled={disabled}
          title="Emoción inicial que se antepondrá a los segmentos durante la generación"
        >
          <option value="none">⚪ Sin emoción previa</option>
          {EMOTION_CATEGORIES.map((cat) => (
            <optgroup key={cat.name} label={`${cat.emoji} ${cat.label}`}>
              {getEmotionsByCategory(cat.name).map((em) => (
                <option key={em.tag} value={em.tag}>
                  {formatEmotionLabel(em)}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>
    </>
  );
};
