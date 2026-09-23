/**
 * Módulo de emociones para Fish Audio (s2.1).
 * Proporciona el catálogo unificado y funciones para anteponer/reemplazar
 * la emoción al principio del texto de cada segmento TTS.
 */

export interface EmotionOption {
  tag: string;
  label: string;
  emoji: string;
  category: "Básicas" | "Avanzadas" | "Tonos" | "Efectos" | "Pausas" | "Especial";
  description?: string;
}

export const V2V_EMOTIONS: EmotionOption[] = [
  // --- Emociones Básicas (24 expresiones) ---
  { tag: "[excited]", label: "Emocionado", emoji: "🤩", category: "Básicas", description: "Enérgico, entusiasta" },
  { tag: "[happy]", label: "Feliz", emoji: "😊", category: "Básicas", description: "Alegre, tono optimista" },
  { tag: "[confident]", label: "Confiado", emoji: "😎", category: "Básicas", description: "Seguro, asertivo" },
  { tag: "[calm]", label: "Calmado", emoji: "😌", category: "Básicas", description: "Tranquilo, relajado" },
  { tag: "[surprised]", label: "Sorprendido", emoji: "😮", category: "Básicas", description: "Asombrado, en shock" },
  { tag: "[satisfied]", label: "Satisfecho", emoji: "🥰", category: "Básicas", description: "Complacido, contento" },
  { tag: "[delighted]", label: "Encantado", emoji: "✨", category: "Básicas", description: "Muy alegre, gozoso" },
  { tag: "[proud]", label: "Orgulloso", emoji: "🦚", category: "Básicas", description: "Satisfecho con logro" },
  { tag: "[relaxed]", label: "Relajado", emoji: "🧘", category: "Básicas", description: "Despreocupado, casual" },
  { tag: "[grateful]", label: "Agradecido", emoji: "🙏", category: "Básicas", description: "Con gratitud" },
  { tag: "[curious]", label: "Curioso", emoji: "🤔", category: "Básicas", description: "Inquisitivo, intrigado" },
  { tag: "[moved]", label: "Conmovido", emoji: "🥺", category: "Básicas", description: "Emocionalmente tocado" },
  { tag: "[empathetic]", label: "Empático", emoji: "🤝", category: "Básicas", description: "Comprensivo, cercano" },
  { tag: "[sad]", label: "Triste", emoji: "😢", category: "Básicas", description: "Melancólico, desanimado" },
  { tag: "[depressed]", label: "Deprimido", emoji: "😞", category: "Básicas", description: "Muy triste, abatido" },
  { tag: "[angry]", label: "Enojado", emoji: "😡", category: "Básicas", description: "Agresivo, molesto" },
  { tag: "[frustrated]", label: "Frustrado", emoji: "😤", category: "Básicas", description: "Exasperado, contrariado" },
  { tag: "[upset]", label: "Disgustado", emoji: "😣", category: "Básicas", description: "Afligido, alterado" },
  { tag: "[scared]", label: "Asustado", emoji: "😨", category: "Básicas", description: "Atemorizado" },
  { tag: "[worried]", label: "Preocupado", emoji: "😟", category: "Básicas", description: "Inquieto" },
  { tag: "[nervous]", label: "Nervioso", emoji: "😰", category: "Básicas", description: "Ansioso, inseguro" },
  { tag: "[embarrassed]", label: "Avergonzado", emoji: "😳", category: "Básicas", description: "Incómodo, apenado" },
  { tag: "[disgusted]", label: "Disgusto/Repulsión", emoji: "🤢", category: "Básicas", description: "Repugnado" },
  { tag: "[sarcastic]", label: "Sarcástico", emoji: "😏", category: "Básicas", description: "Irónico, burlón" },

  // --- Emociones Avanzadas (25 expresiones) ---
  { tag: "[hopeful]", label: "Esperanzado", emoji: "🤞", category: "Avanzadas", description: "Optimista del futuro" },
  { tag: "[optimistic]", label: "Optimista", emoji: "🌟", category: "Avanzadas", description: "Actitud positiva" },
  { tag: "[determined]", label: "Determinado", emoji: "✊", category: "Avanzadas", description: "Resuelto, firme" },
  { tag: "[compassionate]", label: "Compasivo", emoji: "🕊️", category: "Avanzadas", description: "Solidario, cariñoso" },
  { tag: "[sympathetic]", label: "Empatía cálida", emoji: "🤍", category: "Avanzadas", description: "Condolencia" },
  { tag: "[nostalgic]", label: "Nostálgico", emoji: "🕰️", category: "Avanzadas", description: "Recuerdos pasados" },
  { tag: "[anxious]", label: "Ansioso", emoji: "😬", category: "Avanzadas", description: "Muy intranquilo" },
  { tag: "[unhappy]", label: "Infeliz", emoji: "🙁", category: "Avanzadas", description: "Descontento" },
  { tag: "[disappointed]", label: "Decepcionado", emoji: "🙍", category: "Avanzadas", description: "Desilusionado" },
  { tag: "[regretful]", label: "Arrepentido", emoji: "😔", category: "Avanzadas", description: "Con remordimiento" },
  { tag: "[guilty]", label: "Culpable", emoji: "🙇", category: "Avanzadas", description: "Responsable de falta" },
  { tag: "[ashamed]", label: "Apenado profundo", emoji: "🤦", category: "Avanzadas", description: "Vergüenza grave" },
  { tag: "[uncertain]", label: "Incierto", emoji: "🤷", category: "Avanzadas", description: "Dudoso, inseguro" },
  { tag: "[doubtful]", label: "Escéptico", emoji: "🤨", category: "Avanzadas", description: "Desconfiado" },
  { tag: "[confused]", label: "Confundido", emoji: "😕", category: "Avanzadas", description: "Perplejo" },
  { tag: "[indifferent]", label: "Indiferente", emoji: "😐", category: "Avanzadas", description: "Desinteresado" },
  { tag: "[bored]", label: "Aburrido", emoji: "🥱", category: "Avanzadas", description: "Hastiado" },
  { tag: "[lonely]", label: "Solitario", emoji: "🍂", category: "Avanzadas", description: "Aislado" },
  { tag: "[pessimistic]", label: "Pesimista", emoji: "🌧️", category: "Avanzadas", description: "Visión negativa" },
  { tag: "[jealous]", label: "Celoso", emoji: "😠", category: "Avanzadas", description: "Resentido" },
  { tag: "[envious]", label: "Envidioso", emoji: "👀", category: "Avanzadas", description: "Con envidia" },
  { tag: "[disdainful]", label: "Despectivo", emoji: "😒", category: "Avanzadas", description: "Con desprecio" },
  { tag: "[contemptuous]", label: "Desdén", emoji: "🙄", category: "Avanzadas", description: "Con desprecio crítico" },
  { tag: "[hysterical]", label: "Histérico", emoji: "😫", category: "Avanzadas", description: "Descontrolado" },
  { tag: "[resigned]", label: "Resignado", emoji: "🏳️", category: "Avanzadas", description: "Aceptando derrota" },

  // --- Tonos y Entrega (6 expresiones) ---
  { tag: "[in a hurry tone]", label: "Apurado / Urgente", emoji: "⚡", category: "Tonos", description: "Rápido, urgente" },
  { tag: "[emphasis]", label: "Énfasis", emoji: "🗣️", category: "Tonos", description: "Destacar palabra/frase" },
  { tag: "[whispering]", label: "Susurro", emoji: "🤫", category: "Tonos", description: "Muy suave, secreto" },
  { tag: "[soft tone]", label: "Tono Suave", emoji: "🍃", category: "Tonos", description: "Calmante, apacible" },
  { tag: "[shouting]", label: "Gritando", emoji: "📢", category: "Tonos", description: "Voz alta, llamada" },
  { tag: "[screaming]", label: "Chillando / Pánico", emoji: "😱", category: "Tonos", description: "Grito intenso de miedo" },

  // --- Efectos de Audio y Expresión (11 expresiones) ---
  { tag: "[laughing]", label: "Risa", emoji: "😂", category: "Efectos", description: "Risa abierta (ha, ha)" },
  { tag: "[chuckling]", label: "Risita", emoji: "🤭", category: "Efectos", description: "Risa leve contenida" },
  { tag: "[sighing]", label: "Suspiro", emoji: "😮‍💨", category: "Efectos", description: "Alivio o cansancio" },
  { tag: "[sobbing]", label: "Sollozo", emoji: "😭", category: "Efectos", description: "Llanto entrecortado" },
  { tag: "[crying loudly]", label: "Llanto fuerte", emoji: "😿", category: "Efectos", description: "Llanto intenso" },
  { tag: "[groaning]", label: "Gemido / Queja", emoji: "😩", category: "Efectos", description: "Sonido de frustración" },
  { tag: "[panting]", label: "Jadeo", emoji: "🫁", category: "Efectos", description: "Falta de aire" },
  { tag: "[gasping]", label: "Boqueada", emoji: "😲", category: "Efectos", description: "Inspiración brusca" },
  { tag: "[yawning]", label: "Bostezo", emoji: "🥱", category: "Efectos", description: "Sonido de sueño" },
  { tag: "[snoring]", label: "Ronquido", emoji: "💤", category: "Efectos", description: "Sonido de dormir" },
  { tag: "[clear throat]", label: "Carraspera", emoji: "🎙️", category: "Efectos", description: "Aclarar la garganta" },

  // --- Pausas y Ambiente (5 expresiones) ---
  { tag: "[break]", label: "Pausa breve", emoji: "⏸️", category: "Pausas", description: "Silencio corto" },
  { tag: "[long-break]", label: "Pausa larga", emoji: "⏹️", category: "Pausas", description: "Silencio extendido" },
  { tag: "[audience laughing]", label: "Risa de audiencia", emoji: "👏", category: "Pausas", description: "Público riendo" },
  { tag: "[background laughter]", label: "Risa de fondo", emoji: "🎭", category: "Pausas", description: "Risa ambiental" },
  { tag: "[crowd laughing]", label: "Risa multitud", emoji: "👥", category: "Pausas", description: "Multitud riendo" },
];

export const DEFAULT_EMOTION_TAG = "[excited]";

export const EMOTION_CATEGORIES: { name: EmotionOption["category"]; label: string; emoji: string }[] = [
  { name: "Básicas", label: "Emociones Básicas (24)", emoji: "😊" },
  { name: "Avanzadas", label: "Emociones Avanzadas (25)", emoji: "🎭" },
  { name: "Tonos", label: "Tonos y Entrega (6)", emoji: "📢" },
  { name: "Efectos", label: "Efectos de Audio (11)", emoji: "🎙️" },
  { name: "Pausas", label: "Pausas y Ambiente (5)", emoji: "⏸️" },
];

export function getEmotionsByCategory(category: EmotionOption["category"]): EmotionOption[] {
  return V2V_EMOTIONS.filter((e) => e.category === category);
}

/**
 * Aplica o reemplaza la emoción al principio del texto.
 */
export function applyEmotionToText(text: string, emotionTag: string): string {
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

