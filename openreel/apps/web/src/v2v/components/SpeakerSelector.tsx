import React from "react";

export interface SpeakerSelectorProps {
  speaker: string;
  setSpeaker: (speaker: string) => void;
  speakers: Array<{ label: string; value: string }>;
  disabled?: boolean;
}

export const SpeakerSelector: React.FC<SpeakerSelectorProps> = ({
  speaker,
  setSpeaker,
  speakers,
  disabled = false,
}) => {
  return (
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
  );
};
