import { describe, expect, it } from "vitest";
import type { Project } from "@openreel/core";
import { analyzeProject, isInV2VFolder } from "./v2v-export-clips";

function mediaItem(
  id: string,
  name: string,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return { id, name, type: "audio", blob: undefined, ...extra };
}

function clip(
  id: string,
  mediaId: string,
  trackId: string,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id,
    mediaId,
    trackId,
    startTime: 0,
    duration: 1,
    inPoint: 0,
    outPoint: 1,
    volume: 1,
    ...extra,
  };
}

function track(
  id: string,
  type: "video" | "audio",
  clips: Record<string, unknown>[],
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id,
    type,
    name: id,
    clips,
    transitions: [],
    locked: false,
    hidden: false,
    muted: false,
    solo: false,
    ...extra,
  };
}

function makeProject(
  mediaItems: Record<string, unknown>[],
  tracks: Record<string, unknown>[],
): Project {
  return {
    mediaLibrary: { items: mediaItems },
    timeline: { tracks },
  } as unknown as Project;
}

describe("analyzeProject · mute/solo/hidden", () => {
  it("omite las pistas de audio silenciadas (cortes originales)", () => {
    const project = makeProject(
      [mediaItem("tts", "tts_mrbeast_001.m4a"), mediaItem("orig", "vocals_001.m4a")],
      [
        track("tts-track", "audio", [clip("c1", "tts", "tts-track")]),
        track("orig-track", "audio", [clip("c2", "orig", "orig-track")], {
          muted: true,
        }),
      ],
    );

    const result = analyzeProject(project, {});

    expect(result.map((c) => c.mediaName)).toEqual(["tts_mrbeast_001.m4a"]);
  });

  it("mantiene el vídeo de una pista silenciada, pero con volume 0", () => {
    const project = makeProject(
      [mediaItem("video", "video_only.mp4", { type: "video" })],
      [track("video-track", "video", [clip("c1", "video", "video-track")], { muted: true })],
    );

    const result = analyzeProject(project, {});

    expect(result).toHaveLength(1);
    expect(result[0].mediaName).toBe("video_only.mp4");
    expect(result[0].volume).toBe(0);
  });

  it("omite las pistas ocultas", () => {
    const project = makeProject(
      [mediaItem("video", "video_only.mp4", { type: "video" }), mediaItem("tts", "tts_mrbeast_001.m4a")],
      [
        track("video-track", "video", [clip("c1", "video", "video-track")], { hidden: true }),
        track("tts-track", "audio", [clip("c2", "tts", "tts-track")]),
      ],
    );

    const result = analyzeProject(project, {});

    expect(result.map((c) => c.mediaName)).toEqual(["tts_mrbeast_001.m4a"]);
  });

  it("con una pista en solo, las demás pistas de audio se silencian", () => {
    const project = makeProject(
      [mediaItem("a", "tts_a_001.m4a"), mediaItem("b", "tts_b_001.m4a")],
      [
        track("a-track", "audio", [clip("c1", "a", "a-track")], { solo: true }),
        track("b-track", "audio", [clip("c2", "b", "b-track")]),
      ],
    );

    const result = analyzeProject(project, {});

    expect(result.map((c) => c.mediaName)).toEqual(["tts_a_001.m4a"]);
  });

  it("un clip en solo no silencia el vídeo, solo su audio", () => {
    const project = makeProject(
      [mediaItem("video", "video_only.mp4", { type: "video" }), mediaItem("a", "tts_a_001.m4a")],
      [
        track("video-track", "video", [clip("c1", "video", "video-track")]),
        track("a-track", "audio", [clip("c2", "a", "a-track")], { solo: true }),
      ],
    );

    const result = analyzeProject(project, {});

    expect(result).toHaveLength(2);
    expect(result.find((c) => c.mediaName === "video_only.mp4")?.volume).toBe(0);
    expect(result.find((c) => c.mediaName === "tts_a_001.m4a")?.volume).toBe(1);
  });

  it("ignora medios de tipo imagen", () => {
    const project = makeProject(
      [mediaItem("img", "cover.png", { type: "image" })],
      [track("video-track", "video", [clip("c1", "img", "video-track")])],
    );

    expect(analyzeProject(project, {})).toEqual([]);
  });
});

describe("analyzeProject · estado de los medios", () => {
  it("marca ok los cortes originales aunque no estén en nativeFiles", () => {
    const project = makeProject(
      [mediaItem("orig", "vocals_001.m4a")],
      [track("orig-track", "audio", [clip("c1", "orig", "orig-track")])],
    );

    const result = analyzeProject(project, { job: { nativeFiles: [] } });

    expect(result[0].status).toBe("ok");
  });

  it("pide subida si el medio tiene blob y no está en el servidor", () => {
    const blob = new Blob(["x"]);
    const project = makeProject(
      [mediaItem("local", "local.wav", { blob })],
      [track("t", "audio", [clip("c1", "local", "t")])],
    );

    expect(analyzeProject(project, {})[0].status).toBe("upload_needed");
  });

  it("marca not_allowed si no está en el servidor ni tiene blob", () => {
    const project = makeProject(
      [mediaItem("missing", "missing.wav")],
      [track("t", "audio", [clip("c1", "missing", "t")])],
    );

    expect(analyzeProject(project, {})[0].status).toBe("not_allowed");
  });
});

describe("isInV2VFolder", () => {
  it("reconoce los cortes originales como medios V2V", () => {
    expect(isInV2VFolder("vocals_001.m4a", { job: { nativeFiles: [] } })).toBe(true);
  });

  it("reconoce el instrumental y la voz aislada", () => {
    expect(isInV2VFolder("no_vocals.m4a", { job: { nativeFiles: [] } })).toBe(true);
    expect(isInV2VFolder("vocals.wav", { job: { nativeFiles: [] } })).toBe(true);
  });

  it("sin carpetas V2V no adivina", () => {
    expect(isInV2VFolder("vocals_001.m4a", {})).toBe(false);
  });
});
