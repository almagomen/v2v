import React from "react";
import { AlertCircle, Loader2, RefreshCw, RotateCcw, Scissors, Sparkles, X } from "lucide-react";
import { Button } from "@openreel/ui";

import {
  v2vApi,
  type SegmentationApplyMode,
  type SegmentationPreviewResponse,
  type SegmentationStatus,
} from "../api/v2v-api";
import { useTimelineStore } from "@/stores/timeline-store";
import { useV2VStore } from "../stores/v2v-store";
import { toast } from "@/stores/notification-store";
import { rebuildSegmentationTracks } from "../utils/v2v-segmentation-timeline";

/**
 * Banco de cortes: enseña cómo quedaría la segmentación al mover los umbrales
 * que deciden dónde se corta el audio, sobre el timeline real de OpenReel.
 *
 * El overlay no toca el core: se dibuja con `position: fixed` encima del
 * contenedor `[data-testid="timeline-tracks-scroll"]` y usa el zoom y el scroll
 * del propio `useTimelineStore` para quedar pixel-alineado. Todo lo que no es
 * interactivo va con `pointer-events: none`, así que arrastrar clips debajo
 * sigue funcionando.
 */

type Level = "basico" | "avanzado";

interface FieldMeta {
  label: string;
  min: number;
  max: number;
  step: number;
  hint: string;
}

const BASIC_ORDER = [
  "hard_gap",
  "min_duration",
  "lead_max",
  "tail_max",
] as const;

const ADVANCED_ORDER = [
  "min_sentence_gap",
  "jitter_max_gap",
  "orphan_absorb_gap",
  "orphan_absorb_max_dur",
  "merge_max_gap",
] as const;

const FIELD_META: Record<string, FieldMeta> = {
  hard_gap: {
    label: "Pausa que corta",
    min: 0.2,
    max: 3,
    step: 0.05,
    hint: "Silencio que siempre abre un segmento nuevo: el corte de escena.",
  },
  min_duration: {
    label: "Duración mínima",
    min: 0.5,
    max: 8,
    step: 0.1,
    hint: "Antes de este tiempo no se aplican las reglas de corte. Por debajo, el segmento se fusiona con su vecino.",
  },
  lead_max: {
    label: "Margen inicial",
    min: 0,
    max: 0.8,
    step: 0.01,
    hint: "Silencio que el clip toma por delante.",
  },
  tail_max: {
    label: "Margen final",
    min: 0,
    max: 1.2,
    step: 0.01,
    hint: "Silencio que el clip toma por detrás.",
  },
  min_sentence_gap: {
    label: "Respiro de frase",
    min: 0,
    max: 0.8,
    step: 0.02,
    hint: "Pausa mínima tras un signo de cierre. Cuando el ASR capitaliza sin puntuar se exige 1.78× este respiro.",
  },
  jitter_max_gap: {
    label: "Tolerancia de cambio de voz",
    min: 0,
    max: 1.5,
    step: 0.05,
    hint: "Pausa máxima para corregir una palabra aislada de otro hablante.",
  },
  orphan_absorb_gap: {
    label: "Absorber cola (hueco)",
    min: 0,
    max: 2,
    step: 0.05,
    hint: "Hueco máximo para pegar una cola huérfana al segmento.",
  },
  orphan_absorb_max_dur: {
    label: "Absorber cola (duración)",
    min: 0,
    max: 6,
    step: 0.1,
    hint: "Duración máxima de la cola que se absorbe.",
  },
  merge_max_gap: {
    label: "Fusionar micro (hueco)",
    min: 0,
    max: 2,
    step: 0.05,
    hint: "Hueco máximo para unir un micro-segmento al vecino.",
  },
};

const STATUS_STYLE: Record<SegmentationStatus, { block: string; dot: string; label: string }> = {
  igual: { block: "bg-emerald-500/35 border-emerald-400/70", dot: "bg-emerald-400", label: "Igual" },
  ajustado: { block: "bg-sky-500/35 border-sky-400/70", dot: "bg-sky-400", label: "Ajustado" },
  partido: { block: "bg-violet-500/35 border-violet-400/70", dot: "bg-violet-400", label: "Partido" },
  ampliado: { block: "bg-amber-500/35 border-amber-400/70", dot: "bg-amber-400", label: "Ampliado" },
  fusionado: { block: "bg-orange-500/35 border-orange-400/70", dot: "bg-orange-400", label: "Fusionado" },
  modificado: { block: "bg-rose-500/35 border-rose-400/70", dot: "bg-rose-400", label: "Modificado" },
  nuevo: { block: "bg-fuchsia-500/35 border-fuchsia-400/70", dot: "bg-fuchsia-400", label: "Nuevo" },
  eliminado: { block: "bg-zinc-500/30 border-zinc-400/60", dot: "bg-zinc-400", label: "Eliminado" },
};

const TRACKS_SCROLL_SELECTOR = '[data-testid="timeline-tracks-scroll"]';

/**
 * Coste real de cada acción, escrito en el diálogo de confirmación para que
 * nadie lance una resíntesis completa creyendo que re-corta el audio.
 */
const MODE_PROMPT: Record<SegmentationApplyMode, (data: SegmentationPreviewResponse) => string> = {
  resync: (data) =>
    `Re-sincronizar: re-corta el audio original y reajusta ${data.summary.changed} clips ` +
    `desde el máster ya sintetizado. No llama a Fish ni a Gemini: tarda segundos.`,
  regenerate_changed: (data) =>
    `Regenerar lo que cambia: ${data.summary.retranslate} segmentos nuevos se retraducen y ` +
    `${data.summary.resynthesize} se vuelven a sintetizar. El resto reutiliza su audio.`,
  regenerate_all: (data) =>
    `Regenerar todo: se retraducen y re-sintetizan los ${data.proposed.metrics.count} segmentos. ` +
    `Puede tardar varios minutos y consume cuota de Fish y Gemini.`,
};

function useTracksRect(active: boolean): DOMRect | null {
  const [rect, setRect] = React.useState<DOMRect | null>(null);
  const pixelsPerSecond = useTimelineStore((s) => s.pixelsPerSecond);
  const scrollX = useTimelineStore((s) => s.scrollX);

  React.useEffect(() => {
    if (!active) {
      setRect(null);
      return;
    }
    let frame = 0;
    const update = () => {
      const el = document.querySelector(TRACKS_SCROLL_SELECTOR);
      setRect(el ? el.getBoundingClientRect() : null);
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("resize", schedule);
    const el = document.querySelector(TRACKS_SCROLL_SELECTOR);
    el?.addEventListener("scroll", schedule, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      el?.removeEventListener("scroll", schedule);
    };
  }, [active, pixelsPerSecond, scrollX]);

  return rect;
}

interface OverlayProps {
  data: SegmentationPreviewResponse;
  rect: DOMRect;
}

const TimelineOverlay: React.FC<OverlayProps> = ({ data, rect }) => {
  const pixelsPerSecond = useTimelineStore((s) => s.pixelsPerSecond);
  const scrollX = useTimelineStore((s) => s.scrollX);

  const toPx = React.useCallback(
    (seconds: number) => seconds * pixelsPerSecond - scrollX,
    [pixelsPerSecond, scrollX],
  );

  const statusByProposed = React.useMemo(() => {
    const map = new Map<number, SegmentationStatus>();
    for (const row of data.rows) {
      if (row.index != null) map.set(row.index, row.status);
    }
    return map;
  }, [data.rows]);

  const laneHeight = 22;
  const laneGap = 4;

  return (
    <div
      className="fixed z-[190] pointer-events-none overflow-hidden rounded-sm"
      style={{
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      }}
    >
      {/* Franja de comparación: actual arriba, propuesta debajo. */}
      <div
        className="absolute left-0 right-0 top-0 bg-background/70 backdrop-blur-[1px] border-b border-border/60"
        style={{ height: laneHeight * 2 + laneGap + 4 }}
      >
        <div className="absolute left-1 top-0 text-[9px] uppercase tracking-wide text-fg-muted/80 leading-none pt-[2px]">
          actual
        </div>
        <div
          className="absolute left-0 right-0"
          style={{ top: 2, height: laneHeight }}
        >
          {data.current.clips.map((clip, i) => {
            const left = toPx(clip.start);
            const width = Math.max(2, (clip.end - clip.start) * pixelsPerSecond);
            return (
              <div
                key={`cur-${i}`}
                className="absolute rounded-[3px] border bg-sky-500/20 border-sky-400/50"
                style={{ left, width, top: 0, height: laneHeight - 2 }}
                title={`Actual #${i + 1} · ${clip.start.toFixed(2)}–${clip.end.toFixed(2)}s`}
              />
            );
          })}
        </div>
        <div
          className="absolute left-1 text-[9px] uppercase tracking-wide text-fg-muted/80 leading-none"
          style={{ top: laneHeight + 2 }}
        >
          propuesto
        </div>
        <div
          className="absolute left-0 right-0"
          style={{ top: laneHeight + laneGap + 2, height: laneHeight }}
        >
          {data.proposed.clips.map((clip, i) => {
            const status = statusByProposed.get(i + 1) ?? "igual";
            const style = STATUS_STYLE[status];
            const left = toPx(clip.start);
            const width = Math.max(2, (clip.end - clip.start) * pixelsPerSecond);
            return (
              <div
                key={`prop-${i}`}
                className={`absolute rounded-[3px] border ${style.block}`}
                style={{ left, width, top: 0, height: laneHeight - 2 }}
                title={`${style.label} #${i + 1} · ${clip.start.toFixed(2)}–${clip.end.toFixed(2)}s · ${clip.text}`}
              />
            );
          })}
        </div>
      </div>

      {/* Líneas de corte propuestas, de arriba abajo del timeline. */}
      {data.proposed.clips.map((clip, i) => {
        const left = toPx(clip.start);
        return (
          <div
            key={`cut-${i}`}
            className="absolute top-0 bottom-0 border-l border-dashed border-fuchsia-400/25"
            style={{ left }}
          />
        );
      })}
    </div>
  );
};

interface PanelProps {
  jobId: string;
  videoIndex: number;
  onClose: () => void;
}

export const V2VSegmentationPreview: React.FC<PanelProps> = ({ jobId, videoIndex, onClose }) => {
  const [level, setLevel] = React.useState<Level>("basico");
  const [overrides, setOverrides] = React.useState<Record<string, number>>({});
  const [data, setData] = React.useState<SegmentationPreviewResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [applying, setApplying] = React.useState<SegmentationApplyMode | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  const rect = useTracksRect(true);

  React.useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      v2vApi
        .previewSegmentation(jobId, videoIndex, overrides, controller.signal)
        .then((res) => setData(res))
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setError(err instanceof Error ? err.message : "Error al simular la segmentación");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [jobId, videoIndex, overrides, reloadKey]);

  const params = data?.params ?? {};
  const fields = level === "basico" ? BASIC_ORDER : [...BASIC_ORDER, ...ADVANCED_ORDER];

  const setParam = (name: string, value: number) => {
    setOverrides((prev) => ({ ...prev, [name]: value }));
  };

  const reset = () => setOverrides({});

  const applyMode = async (mode: SegmentationApplyMode) => {
    if (!data || applying) return;
    const prompt = MODE_PROMPT[mode](data);
    if (!window.confirm(`${prompt}\n\n¿Aplicar al video abierto?`)) return;

    setApplying(mode);
    setError(null);
    try {
      const res = await v2vApi.applySegmentation(jobId, videoIndex, overrides, mode);
      useV2VStore.getState().setSegments(res.segments);
      const rebuild = await rebuildSegmentationTracks(jobId, videoIndex);
      if (!rebuild.success) throw new Error(rebuild.message);

      // La variación ya es la producción: los sliders vuelven a reflejar el
      // estado real y el diff se recalcula contra lo aplicado.
      setOverrides({});
      setReloadKey((k) => k + 1);
      toast.success(
        "Cortes aplicados",
        `${res.summary.count} segmentos · ${rebuild.message}`,
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error al aplicar la segmentación";
      setError(msg);
      toast.error("No se pudo aplicar", msg);
    } finally {
      setApplying(null);
    }
  };

  const summary = data?.summary;
  const cur = data?.current.metrics;
  const prop = data?.proposed.metrics;
  const groupingChanged = Boolean(data?.rows.some((row) => row.needs_retranslation));
  const busy = applying !== null;

  return (
    <>
      {rect && data && <TimelineOverlay data={data} rect={rect} />}

      <div className="fixed bottom-3 right-3 z-[210] w-[420px] max-h-[72vh] bg-bg-1 border border-border shadow-2xl rounded-xl flex flex-col overflow-hidden pointer-events-auto">
        <div className="flex items-start justify-between gap-2 px-4 py-3 border-b border-border shrink-0">
          <div className="min-w-0">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">
              <Scissors size={15} className="text-accent" />
              Banco de cortes
            </h3>
            <p className="text-[11px] text-fg-muted mt-0.5">
              Mueve un umbral y mira el efecto sobre el timeline. No regenera nada.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-bg-2 text-fg-muted hover:text-fg transition-colors shrink-0"
            title="Cerrar banco de cortes"
          >
            <X size={15} />
          </button>
        </div>

        <div className="px-4 py-2 border-b border-border shrink-0 flex items-center justify-between gap-2">
          <div className="inline-flex rounded-lg border border-border overflow-hidden">
            {(["basico", "avanzado"] as Level[]).map((lvl) => (
              <button
                key={lvl}
                type="button"
                onClick={() => setLevel(lvl)}
                className={`px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  level === lvl ? "bg-accent text-white" : "bg-bg-2 text-fg-2 hover:bg-bg-3"
                }`}
              >
                {lvl === "basico" ? "Básico" : "Avanzado"}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {(loading || busy) && <Loader2 size={13} className="animate-spin text-fg-muted" />}
            <Button
              variant="ghost"
              size="sm"
              onClick={reset}
              disabled={busy}
              className="h-6 px-2 text-[11px]"
            >
              <RotateCcw size={11} className="mr-1" />
              Restablecer
            </Button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="px-4 py-2 space-y-2.5">
            {fields.map((name) => {
              const meta = FIELD_META[name];
              if (!meta) return null;
              const value = params[name] ?? 0;
              return (
                <label key={name} className="block">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-medium text-fg-2">{meta.label}</span>
                    <span className="text-[11px] tabular-nums text-fg-muted">
                      {value.toFixed(2)}s
                    </span>
                  </div>
                  <input
                    type="range"
                    min={meta.min}
                    max={meta.max}
                    step={meta.step}
                    value={value}
                    onChange={(e) => setParam(name, Number(e.target.value))}
                    className="w-full h-1.5 mt-1 accent-accent cursor-pointer"
                  />
                  <span className="block text-[10px] text-fg-muted/80 leading-tight">{meta.hint}</span>
                </label>
              );
            })}
          </div>

          {error && (
            <div className="mx-4 mb-2 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-2 text-[11px] text-red-300">
              <AlertCircle size={13} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {data && (
            <div className="px-4 pb-3 space-y-3">
              {data.words_source !== "assigned" && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[10px] text-amber-300">
                  {data.words_source === "raw"
                    ? "Hablantes aproximados por solape (video procesado antes de guardar la asignación exacta)."
                    : "Sin transcripción por palabra: la re-agrupación no puede moverse, solo los márgenes."}
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                {cur && prop && (
                  <>
                    <Metric label="Clips" current={String(cur.count)} proposed={String(prop.count)} />
                    <Metric
                      label="Slot medio"
                      current={`${cur.avg_slot.toFixed(2)}s`}
                      proposed={`${prop.avg_slot.toFixed(2)}s`}
                    />
                    <Metric
                      label="Clips < 2 s"
                      current={`${Math.round(cur.short_ratio * 100)}%`}
                      proposed={`${Math.round(prop.short_ratio * 100)}%`}
                    />
                    <Metric
                      label="Aire muerto"
                      current={`${cur.dead_air.toFixed(2)}s`}
                      proposed={`${prop.dead_air.toFixed(2)}s`}
                    />
                  </>
                )}
              </div>

              {summary && (
                <div className="flex flex-wrap gap-1.5 text-[10px]">
                  <Chip tone="muted">cambian {summary.changed}</Chip>
                  <Chip tone="sky">re-sincronizar {summary.resync}</Chip>
                  <Chip tone="orange">re-sintetizar {summary.resynthesize}</Chip>
                  <Chip tone="rose">retraducir {summary.retranslate}</Chip>
                  {summary.phonemes_dropped > 0 && (
                    <Chip tone="rose">phonemes perdidos {summary.phonemes_dropped}</Chip>
                  )}
                </div>
              )}

              <div className="space-y-1.5">
                <div className="grid grid-cols-3 gap-1.5">
                  <ActionButton
                    icon={<RefreshCw size={11} />}
                    label="Re-sincronizar"
                    hint="Re-corta y reajusta desde el máster. Sin Fish ni Gemini."
                    disabled={busy || summary?.changed === 0 || groupingChanged}
                    loading={applying === "resync"}
                    onClick={() => applyMode("resync")}
                  />
                  <ActionButton
                    icon={<Sparkles size={11} />}
                    label="Lo que cambia"
                    hint="Retraduce y resintetiza solo los segmentos nuevos."
                    disabled={busy || summary?.changed === 0}
                    loading={applying === "regenerate_changed"}
                    onClick={() => applyMode("regenerate_changed")}
                  />
                  <ActionButton
                    icon={<RotateCcw size={11} />}
                    label="Todo"
                    hint="Rehace la traducción y la voz de todos los segmentos."
                    disabled={busy}
                    loading={applying === "regenerate_all"}
                    onClick={() => applyMode("regenerate_all")}
                  />
                </div>
                <p className="text-[10px] leading-tight text-fg-muted/80">
                  {groupingChanged
                    ? "La agrupación cambió: «Re-sincronizar» queda desactivado porque el máster ya no corresponde al texto."
                    : "Aplicar reescribe los audios del video abierto y recoloca sus clips en el timeline."}
                </p>
              </div>

              <div className="rounded-lg border border-border overflow-hidden">
                <div className="grid grid-cols-[38px_1fr_58px_58px] gap-1 bg-bg-2 px-2 py-1 text-[10px] font-semibold text-fg-muted">
                  <span>#</span>
                  <span>Estado</span>
                  <span className="text-right">Inicio</span>
                  <span className="text-right">Slot</span>
                </div>
                <div className="max-h-52 overflow-y-auto">
                  {data.rows.map((row, i) => {
                    const style = STATUS_STYLE[row.status];
                    const clip = row.proposed ?? row.current;
                    return (
                      <div
                        key={`${row.status}-${row.index ?? "x"}-${i}`}
                        className="grid grid-cols-[38px_1fr_58px_58px] gap-1 px-2 py-1 text-[10px] border-t border-border/50 items-center"
                      >
                        <span className="text-fg-muted tabular-nums">
                          {row.index ?? row.current_index ?? "—"}
                        </span>
                        <span className="flex items-center gap-1.5 min-w-0">
                          <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${style.dot}`} />
                          <span className="truncate text-fg-2">{style.label}</span>
                          {row.needs_retranslation && (
                            <span className="shrink-0 rounded bg-rose-500/15 px-1 text-[9px] text-rose-300">
                              retrad.
                            </span>
                          )}
                        </span>
                        <span className="text-right tabular-nums text-fg-muted">
                          {clip ? `${clip.start.toFixed(2)}s` : "—"}
                        </span>
                        <span className="text-right tabular-nums text-fg-muted">
                          {clip ? `${clip.slot.toFixed(2)}s` : "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
};

const Metric: React.FC<{ label: string; current: string; proposed: string }> = ({
  label,
  current,
  proposed,
}) => {
  const changed = current !== proposed;
  return (
    <div className="rounded-lg border border-border bg-bg-2 px-2 py-1.5">
      <div className="text-[10px] text-fg-muted">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[11px] text-fg-muted line-through">{current}</span>
        <span className={`text-[12px] font-semibold ${changed ? "text-accent" : "text-fg-2"}`}>
          {proposed}
        </span>
      </div>
    </div>
  );
};

const Chip: React.FC<{ tone: "muted" | "sky" | "orange" | "rose"; children: React.ReactNode }> = ({
  tone,
  children,
}) => {
  const tones: Record<string, string> = {
    muted: "bg-bg-2 text-fg-muted border-border",
    sky: "bg-sky-500/10 text-sky-300 border-sky-500/25",
    orange: "bg-orange-500/10 text-orange-300 border-orange-500/25",
    rose: "bg-rose-500/10 text-rose-300 border-rose-500/25",
  };
  return (
    <span className={`rounded-full border px-2 py-0.5 ${tones[tone]}`}>{children}</span>
  );
};

const ActionButton: React.FC<{
  icon: React.ReactNode;
  label: string;
  hint: string;
  disabled?: boolean;
  loading?: boolean;
  onClick: () => void;
}> = ({ icon, label, hint, disabled, loading, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    title={hint}
    className="flex items-center justify-center gap-1 rounded-lg border border-border bg-bg-2 px-1.5 py-1.5 text-[10px] font-medium text-fg-2 transition-colors hover:bg-bg-3 hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
  >
    {loading ? <Loader2 size={11} className="animate-spin" /> : icon}
    <span className="truncate">{label}</span>
  </button>
);
