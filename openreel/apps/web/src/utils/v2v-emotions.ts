/**
 * Módulo de emociones para Fish Audio (s2.1).
 * Proporciona el catálogo unificado y funciones para anteponer/reemplazar
 * la emoción en el texto de cada segmento TTS.
 */

export interface EmotionOption {
  tag: string;
  label: string;
  emoji: string;
  category: "Básicas" | "Avanzadas" | "Tonos" | "Efectos" | "Pausas" | "Especial";
  description?: string;
  context?: string; // Example Context / When to Use / Suggested Text
}

export const V2V_EMOTIONS: EmotionOption[] = [
  // --- Emociones Básicas (24 expresiones) ---
  {
    tag: "[happy]",
    label: "Feliz",
    emoji: "😊",
    category: "Básicas",
    description: "Alegre, tono optimista",
    context: "Buenas noticias, saludos",
  },
  {
    tag: "[excited]",
    label: "Emocionado",
    emoji: "🤩",
    category: "Básicas",
    description: "Enérgico, entusiasta",
    context: "Anuncios, celebraciones",
  },
  {
    tag: "[confident]",
    label: "Confiado",
    emoji: "😎",
    category: "Básicas",
    description: "Seguro, asertivo",
    context: "Presentaciones, ventas",
  },
  {
    tag: "[calm]",
    label: "Calmado",
    emoji: "😌",
    category: "Básicas",
    description: "Tranquilo, relajado",
    context: "Instrucciones, meditación",
  },
  {
    tag: "[surprised]",
    label: "Sorprendido",
    emoji: "😮",
    category: "Básicas",
    description: "Asombrado, en shock",
    context: "Reacciones, descubrimientos",
  },
  {
    tag: "[satisfied]",
    label: "Satisfecho",
    emoji: "🥰",
    category: "Básicas",
    description: "Complacido, contento",
    context: "Confirmaciones, reseñas",
  },
  {
    tag: "[delighted]",
    label: "Encantado",
    emoji: "✨",
    category: "Básicas",
    description: "Muy alegre, gozoso",
    context: "Celebraciones, elogios",
  },
  {
    tag: "[proud]",
    label: "Orgulloso",
    emoji: "🦚",
    category: "Básicas",
    description: "Satisfecho con logro",
    context: "Logros, reconocimientos",
  },
  {
    tag: "[relaxed]",
    label: "Relajado",
    emoji: "🧘",
    category: "Básicas",
    description: "Despreocupado, casual",
    context: "Conversación informal",
  },
  {
    tag: "[grateful]",
    label: "Agradecido",
    emoji: "🙏",
    category: "Básicas",
    description: "Con gratitud",
    context: "Agradecimientos, aprecio",
  },
  {
    tag: "[curious]",
    label: "Curioso",
    emoji: "🤔",
    category: "Básicas",
    description: "Inquisitivo, intrigado",
    context: "Preguntas, exploración",
  },
  {
    tag: "[moved]",
    label: "Conmovido",
    emoji: "🥺",
    category: "Básicas",
    description: "Emocionalmente tocado",
    context: "Momentos emotivos",
  },
  {
    tag: "[empathetic]",
    label: "Empático",
    emoji: "🤝",
    category: "Básicas",
    description: "Comprensivo, cercano",
    context: "Apoyo, contención",
  },
  {
    tag: "[sad]",
    label: "Triste",
    emoji: "😢",
    category: "Básicas",
    description: "Melancólico, desanimado",
    context: "Empatía, malas noticias",
  },
  {
    tag: "[depressed]",
    label: "Deprimido",
    emoji: "😞",
    category: "Básicas",
    description: "Muy triste, abatido",
    context: "Temas serios",
  },
  {
    tag: "[angry]",
    label: "Enojado",
    emoji: "😡",
    category: "Básicas",
    description: "Agresivo, molesto",
    context: "Quejas, advertencias",
  },
  {
    tag: "[frustrated]",
    label: "Frustrado",
    emoji: "😤",
    category: "Básicas",
    description: "Exasperado, contrariado",
    context: "Problemas técnicos, retrasos",
  },
  {
    tag: "[upset]",
    label: "Disgustado",
    emoji: "😣",
    category: "Básicas",
    description: "Afligido, alterado",
    context: "Quejas, inconvenientes",
  },
  {
    tag: "[scared]",
    label: "Asustado",
    emoji: "😨",
    category: "Básicas",
    description: "Atemorizado",
    context: "Advertencias, misterio",
  },
  {
    tag: "[worried]",
    label: "Preocupado",
    emoji: "😟",
    category: "Básicas",
    description: "Inquieto, afligido",
    context: "Dudas, preocupaciones",
  },
  {
    tag: "[nervous]",
    label: "Nervioso",
    emoji: "😰",
    category: "Básicas",
    description: "Ansioso, inseguro",
    context: "Disculpas, dudas",
  },
  {
    tag: "[embarrassed]",
    label: "Avergonzado",
    emoji: "😳",
    category: "Básicas",
    description: "Incómodo, apenado",
    context: "Disculpas, errores",
  },
  {
    tag: "[disgusted]",
    label: "Disgusto",
    emoji: "🤢",
    category: "Básicas",
    description: "Repugnado, con rechazo",
    context: "Reseñas negativas",
  },
  {
    tag: "[sarcastic]",
    label: "Sarcástico",
    emoji: "😏",
    category: "Básicas",
    description: "Irónico, burlón",
    context: "Humor, crítica",
  },

  // --- Emociones Avanzadas (25 expresiones) ---
  {
    tag: "[disdainful]",
    label: "Despectivo",
    emoji: "😒",
    category: "Avanzadas",
    description: "Con desprecio, desdeñoso",
    context: "Crítica, rechazo",
  },
  {
    tag: "[unhappy]",
    label: "Infeliz",
    emoji: "🙁",
    category: "Avanzadas",
    description: "Descontento, insatisfecho",
    context: "Quejas, reclamos",
  },
  {
    tag: "[anxious]",
    label: "Ansioso",
    emoji: "😬",
    category: "Avanzadas",
    description: "Muy preocupado, intranquilo",
    context: "Asuntos urgentes",
  },
  {
    tag: "[hysterical]",
    label: "Histérico",
    emoji: "😫",
    category: "Avanzadas",
    description: "Emoción descontrolada",
    context: "Reacciones extremas",
  },
  {
    tag: "[indifferent]",
    label: "Indiferente",
    emoji: "😐",
    category: "Avanzadas",
    description: "Desinteresado, neutro",
    context: "Respuestas neutras",
  },
  {
    tag: "[uncertain]",
    label: "Incierto",
    emoji: "🤷",
    category: "Avanzadas",
    description: "Dudoso, inseguro",
    context: "Especulaciones, dudas",
  },
  {
    tag: "[doubtful]",
    label: "Escéptico",
    emoji: "🤨",
    category: "Avanzadas",
    description: "Desconfiado, suspicaz",
    context: "Incredulidad, objeciones",
  },
  {
    tag: "[confused]",
    label: "Confundido",
    emoji: "😕",
    category: "Avanzadas",
    description: "Perplejo, desorientado",
    context: "Petición de aclaración",
  },
  {
    tag: "[disappointed]",
    label: "Decepcionado",
    emoji: "🙍",
    category: "Avanzadas",
    description: "Desilusionado, insatisfecho",
    context: "Expectativas no cumplidas",
  },
  {
    tag: "[regretful]",
    label: "Arrepentido",
    emoji: "😔",
    category: "Avanzadas",
    description: "Con remordimiento, pesar",
    context: "Disculpas, errores",
  },
  {
    tag: "[guilty]",
    label: "Culpable",
    emoji: "🙇",
    category: "Avanzadas",
    description: "Responsable de falta",
    context: "Confesiones, disculpas",
  },
  {
    tag: "[ashamed]",
    label: "Apenado profundo",
    emoji: "🤦",
    category: "Avanzadas",
    description: "Vergüenza grave",
    context: "Errores graves",
  },
  {
    tag: "[jealous]",
    label: "Celoso",
    emoji: "😠",
    category: "Avanzadas",
    description: "Resentido, con celos",
    context: "Comparaciones",
  },
  {
    tag: "[envious]",
    label: "Envidioso",
    emoji: "👀",
    category: "Avanzadas",
    description: "Deseando lo ajeno",
    context: "Admiración con deseo",
  },
  {
    tag: "[hopeful]",
    label: "Esperanzado",
    emoji: "🤞",
    category: "Avanzadas",
    description: "Optimista del futuro",
    context: "Planes futuros",
  },
  {
    tag: "[optimistic]",
    label: "Optimista",
    emoji: "🌟",
    category: "Avanzadas",
    description: "Actitud positiva",
    context: "Ánimo, aliento",
  },
  {
    tag: "[pessimistic]",
    label: "Pesimista",
    emoji: "🌧️",
    category: "Avanzadas",
    description: "Visión negativa",
    context: "Advertencias, dudas",
  },
  {
    tag: "[nostalgic]",
    label: "Nostálgico",
    emoji: "🕰️",
    category: "Avanzadas",
    description: "Añoranza del pasado",
    context: "Recuerdos, anécdotas",
  },
  {
    tag: "[lonely]",
    label: "Solitario",
    emoji: "🍂",
    category: "Avanzadas",
    description: "Aislado, en soledad",
    context: "Contenido emotivo",
  },
  {
    tag: "[bored]",
    label: "Aburrido",
    emoji: "🥱",
    category: "Avanzadas",
    description: "Hastiado, cansado",
    context: "Desinterés",
  },
  {
    tag: "[contemptuous]",
    label: "Desdén",
    emoji: "🙄",
    category: "Avanzadas",
    description: "Mostrando desprecio",
    context: "Crítica fuerte",
  },
  {
    tag: "[sympathetic]",
    label: "Condolencia",
    emoji: "🤍",
    category: "Avanzadas",
    description: "Empatía cálida",
    context: "Condolencias, pésame",
  },
  {
    tag: "[compassionate]",
    label: "Compasivo",
    emoji: "🕊️",
    category: "Avanzadas",
    description: "Cuidado y amor profundo",
    context: "Apoyo, ayuda solidaria",
  },
  {
    tag: "[determined]",
    label: "Determinado",
    emoji: "✊",
    category: "Avanzadas",
    description: "Resuelto, decidido",
    context: "Metas, compromisos",
  },
  {
    tag: "[resigned]",
    label: "Resignado",
    emoji: "🏳️",
    category: "Avanzadas",
    description: "Aceptando derrota",
    context: "Rendición, aceptación",
  },

  // --- Tonos y Entrega (6 expresiones) ---
  {
    tag: "[in a hurry tone]",
    label: "Apurado / Urgente",
    emoji: "⚡",
    category: "Tonos",
    description: "Rápido, urgente",
    context: "Información urgente",
  },
  {
    tag: "[shouting]",
    label: "Gritando",
    emoji: "📢",
    category: "Tonos",
    description: "Voz alta, llamada",
    context: "Llamar la atención",
  },
  {
    tag: "[screaming]",
    label: "Chillando",
    emoji: "😱",
    category: "Tonos",
    description: "Grito intenso de miedo",
    context: "Emergencias, pánico",
  },
  {
    tag: "[whispering]",
    label: "Susurro",
    emoji: "🤫",
    category: "Tonos",
    description: "Muy suave, secreto",
    context: "Secretos, escenas íntimas",
  },
  {
    tag: "[soft tone]",
    label: "Tono Suave",
    emoji: "🍃",
    category: "Tonos",
    description: "Calmante, apacible",
    context: "Consuelo, serenidad",
  },
  {
    tag: "[emphasis]",
    label: "Énfasis",
    emoji: "🗣️",
    category: "Tonos",
    description: "Acentúa la palabra o frase",
    context: "Resaltar ideas clave",
  },

  // --- Efectos de Audio y Expresión (11 expresiones) ---
  {
    tag: "[laughing]",
    label: "Risa",
    emoji: "😂",
    category: "Efectos",
    description: "Risa completa",
    context: "Texto: Ha, ha, ha",
  },
  {
    tag: "[chuckling]",
    label: "Risita",
    emoji: "🤭",
    category: "Efectos",
    description: "Risa leve contenida",
    context: "Texto: Heh, heh",
  },
  {
    tag: "[sighing]",
    label: "Suspiro",
    emoji: "😮‍💨",
    category: "Efectos",
    description: "Alivio o cansancio",
    context: "Texto: sigh",
  },
  {
    tag: "[sobbing]",
    label: "Sollozo",
    emoji: "😭",
    category: "Efectos",
    description: "Llanto entrecortado",
    context: "Opcional en texto",
  },
  {
    tag: "[crying loudly]",
    label: "Llanto fuerte",
    emoji: "😿",
    category: "Efectos",
    description: "Llanto intenso",
    context: "Opcional en texto",
  },
  {
    tag: "[groaning]",
    label: "Gemido / Queja",
    emoji: "😩",
    category: "Efectos",
    description: "Sonido de frustración",
    context: "Texto: ugh",
  },
  {
    tag: "[panting]",
    label: "Jadeo",
    emoji: "🫁",
    category: "Efectos",
    description: "Falta de aire",
    context: "Texto: huff, puff",
  },
  {
    tag: "[gasping]",
    label: "Boqueada",
    emoji: "😲",
    category: "Efectos",
    description: "Inspiración brusca",
    context: "Texto: gasp",
  },
  {
    tag: "[yawning]",
    label: "Bostezo",
    emoji: "🥱",
    category: "Efectos",
    description: "Sonido de sueño",
    context: "Texto: yawn",
  },
  {
    tag: "[snoring]",
    label: "Ronquido",
    emoji: "💤",
    category: "Efectos",
    description: "Sonido al dormir",
    context: "Texto: zzz",
  },
  {
    tag: "[clear throat]",
    label: "Carraspera",
    emoji: "🎙️",
    category: "Efectos",
    description: "Aclarar la garganta",
    context: "Texto: ahem",
  },

  // --- Pausas y Ambiente (5 expresiones) ---
  {
    tag: "[break]",
    label: "Pausa breve",
    emoji: "⏸️",
    category: "Pausas",
    description: "Silencio corto",
    context: "Breve pausa en el discurso",
  },
  {
    tag: "[long-break]",
    label: "Pausa larga",
    emoji: "⏹️",
    category: "Pausas",
    description: "Silencio extendido",
    context: "Pausa extendida en el discurso",
  },
  {
    tag: "[audience laughing]",
    label: "Risa de audiencia",
    emoji: "👏",
    category: "Pausas",
    description: "Sonido de público riendo",
    context: "Risas del público",
  },
  {
    tag: "[background laughter]",
    label: "Risa de fondo",
    emoji: "🎭",
    category: "Pausas",
    description: "Risa ambiental",
    context: "Risas de fondo",
  },
  {
    tag: "[crowd laughing]",
    label: "Risa multitud",
    emoji: "👥",
    category: "Pausas",
    description: "Multitud riendo",
    context: "Grupo grande riendo",
  },
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
 * Formatea la etiqueta de emoción según la solicitud del usuario:
 * emoji Emocion [EMOTION] - descripcion - example/use-suggested
 */
export function formatEmotionLabel(em: EmotionOption): string {
  const parts = [`${em.emoji} ${em.label} ${em.tag}`];
  if (em.description) parts.push(em.description);
  if (em.context) parts.push(em.context);
  return parts.join(" - ");
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
