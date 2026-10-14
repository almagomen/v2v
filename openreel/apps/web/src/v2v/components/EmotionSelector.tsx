import React from "react";
import {
  EMOTION_CATEGORIES,
  getEmotionsByCategory,
  formatEmotionLabel,
} from "../utils/v2v-emotions";

export interface EmotionSelectorProps {
  value?: string;
  onChange: (tag: string) => void;
  className?: string;
  placeholder?: string;
  title?: string;
  disabled?: boolean;
}

export const EmotionSelector: React.FC<EmotionSelectorProps> = ({
  value = "",
  onChange,
  className = "h-6 text-[10px] px-1.5 bg-background-tertiary border border-border rounded text-text-primary focus:outline-none focus:border-primary cursor-pointer max-w-[210px] truncate font-medium",
  placeholder = "✨ Insertar...",
  title = "Selecciona una emoción para insertarla en la posición del cursor",
  disabled = false,
}) => {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={className}
      title={title}
      disabled={disabled}
    >
      <option value="" disabled>
        {placeholder}
      </option>
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
  );
};
