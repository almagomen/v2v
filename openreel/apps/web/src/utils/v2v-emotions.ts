/**
 * Módulo de emociones para Fish Audio (s2.1).
 * Proporciona el catálogo unificado y funciones para anteponer/reemplazar
 * la emoción al principio del texto de cada segmento TTS.
 */

export interface EmotionOption {
  tag: string;
  label: string;
  emoji: string;
  category: "Básicas" | "Tonos" | "Efectos" | "Pausas" | "Especial";
}

export const V2V_EMOTIONS: EmotionOption[] = [
  { tag: "[excited]", label: "Emocionado", emoji: "🤩", category: "Básicas" },
  { tag: "[happy]", label: "Feliz", emoji: "😊", category: "Básicas" },
  { tag: "[confident]", label: "Confiado/Seguro", emoji: "😎", category: "Básicas" },
  { tag: "[calm]", label: "Calmado", emoji: "😌", category: "Básicas" },
  { tag: "[surprised]", label: "Sorprendido", emoji: "😮", category: "Básicas" },
  { tag: "[sad]", label: "Triste", emoji: "😢", category: "Básicas" },
  { tag: "[angry]", label: "Enojado", emoji: "😡", category: "Básicas" },
  { tag: "[scared]", label: "Asustado", emoji: "😨", category: "Básicas" },
  { tag: "[whispering]", label: "Susurro", emoji: "🤫", category: "Tonos" },
  { tag: "[emphasis]", label: "Énfasis", emoji: "🗣️", category: "Tonos" },
  { tag: "[in a hurry tone]", label: "Apurado", emoji: "⚡", category: "Tonos" },
  { tag: "[soft tone]", label: "Tono Suave", emoji: "🍃", category: "Tonos" },
  { tag: "[shouting]", label: "Gritando", emoji: "📢", category: "Tonos" },
  { tag: "[laughing]", label: "Risa", emoji: "😂", category: "Efectos" },
  { tag: "[sighing]", label: "Suspiro", emoji: "🥱", category: "Efectos" },
  { tag: "[gasping]", label: "Jadeo", emoji: "😲", category: "Efectos" },
  { tag: "[yawning]", label: "Bostezo", emoji: "🥱", category: "Efectos" },
  { tag: "[break]", label: "Pausa breve", emoji: "⏸️", category: "Pausas" },
  { tag: "[long-break]", label: "Pausa larga", emoji: "⏹️", category: "Pausas" },
  { tag: "none", label: "Sin emoción", emoji: "⚪", category: "Especial" },
];

export const DEFAULT_EMOTION_TAG = "[excited]";

/**
 * Aplica o reemplaza la emoción al principio del texto.
 * Si emotionTag es 'none' o vacío, remueve cualquier tag inicial.
 */
export function applyEmotionToText(text: string, emotionTag: string): string {
  // Remueve tag de emoción existente al inicio ej: [happy], [excited], etc.
  const clean = text.replace(/^\[[a-zA-Z0-9\s_-]+\]\s*/, "").trim();
  if (!emotionTag || emotionTag === "none") {
    return clean;
  }
  const tag = emotionTag.startsWith("[") ? emotionTag : `[${emotionTag}]`;
  return `${tag} ${clean}`.trim();
}

/**
 * Extrae la emoción inicial del texto si existe.
 */
export function extractEmotionFromText(text: string): {
  emotionTag: string;
  cleanText: string;
} {
  const match = text.match(/^(\[[a-zA-Z0-9\s_-]+\])\s*/);
  if (match) {
    const rawTag = match[1];
    const exists = V2V_EMOTIONS.some((e) => e.tag.toLowerCase() === rawTag.toLowerCase());
    return {
      emotionTag: exists ? rawTag.toLowerCase() : rawTag,
      cleanText: text.replace(match[0], "").trim(),
    };
  }
  return {
    emotionTag: DEFAULT_EMOTION_TAG,
    cleanText: text,
  };
}
