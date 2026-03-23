import React, { useRef, useState, useEffect } from "react";
import { Shapes, FileCode, Smile } from "lucide-react";
import type { ShapeClip, SVGClip, StickerClip } from "@openreel/core";
import { ContextMenu, ContextMenuTrigger } from "@openreel/ui";
import { GraphicsClipContextMenu } from "./GraphicsClipContextMenu";
import { calculateSnap } from "./utils";
import { useProjectStore } from "../../../stores/project-store";
import { useTimelineStore } from "../../../stores/timeline-store";
import { useUIStore } from "../../../stores/ui-store";

type GraphicClipUnion = ShapeClip | SVGClip | StickerClip;

interface ShapeClipComponentProps {
  shapeClip: GraphicClipUnion;
  pixelsPerSecond: number;
  isSelected: boolean;
  timelineRef: React.RefObject<HTMLDivElement>;
  onSelect: (
    clipId: string,
    options?: { addToSelection?: boolean; rangeSelect?: boolean },
  ) => void;
  onTrim: (clipId: string, edge: "left" | "right", newTime: number) => void;
  onMoveClip: (clipId: string, newStartTime: number) => void;
}

const HORIZONTAL_AUTO_SCROLL_THRESHOLD = 120;
const HORIZONTAL_AUTO_SCROLL_SPEED = 14;

export const ShapeClipComponent: React.FC<ShapeClipComponentProps> = ({
  shapeClip,
  pixelsPerSecond,
  isSelected,
  timelineRef,
  onSelect,
  onTrim,
  onMoveClip,
}) => {
  const clipRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const [dragTime, setDragTime] = useState<number | null>(null);
  const pendingDropRef = useRef<{ time: number }>({ time: 0 });
  const mousePositionRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isTrimming, setIsTrimming] = useState<"left" | "right" | null>(null);
  const { snapSettings } = useUIStore();
  const { playheadPosition } = useTimelineStore();
  const trimStartRef = useRef<{
    mouseX: number;
    startTime: number;
    duration: number;
  }>({
    mouseX: 0,
    startTime: shapeClip.startTime,
    duration: shapeClip.duration,
  });

  const currentStartTime = dragTime !== null ? dragTime : shapeClip.startTime;
  const left = currentStartTime * pixelsPerSecond;
  const width = shapeClip.duration * pixelsPerSecond;

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    if (isTrimming) return;
    e.stopPropagation();

    const timelineRect = timelineRef.current?.getBoundingClientRect();
    if (!timelineRect) return;
    const scrollLeft = timelineRef.current?.scrollLeft || 0;
    const clickX = e.clientX - timelineRect.left + scrollLeft;
    const clipStartX = shapeClip.startTime * pixelsPerSecond;
    setDragOffset(clickX - clipStartX);
    setDragTime(null);
    setIsDragging(true);
    mousePositionRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleClick = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    if (isTrimming || isDragging) return;
    e.stopPropagation();
    onSelect(shapeClip.id, {
      addToSelection: e.shiftKey || e.metaKey,
      rangeSelect: e.shiftKey && e.altKey,
    });
  };

  const handleTrimStart = (e: React.MouseEvent, edge: "left" | "right") => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    setIsTrimming(edge);
    trimStartRef.current = {
      mouseX: e.clientX,
      startTime: shapeClip.startTime,
      duration: shapeClip.duration,
    };
    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
  };

  useEffect(() => {
    if (!isDragging) return;

    let animationFrameId: number | null = null;

    const scrollLoop = () => {
      if (!timelineRef.current) {
        animationFrameId = requestAnimationFrame(scrollLoop);
        return;
      }

      const timeline = timelineRef.current;
      const timelineRect = timeline.getBoundingClientRect();
      const mouseX = mousePositionRef.current.x;
      const distanceFromLeft = mouseX - timelineRect.left;
      const distanceFromRight = timelineRect.right - mouseX;
      const canScrollLeft = timeline.scrollLeft > 0;
      const canScrollRight =
        timeline.scrollLeft < timeline.scrollWidth - timeline.clientWidth;

      if (distanceFromLeft < HORIZONTAL_AUTO_SCROLL_THRESHOLD && canScrollLeft) {
        timeline.scrollLeft -= HORIZONTAL_AUTO_SCROLL_SPEED;
      } else if (
        distanceFromRight < HORIZONTAL_AUTO_SCROLL_THRESHOLD &&
        canScrollRight
      ) {
        timeline.scrollLeft += HORIZONTAL_AUTO_SCROLL_SPEED;
      }

      animationFrameId = requestAnimationFrame(scrollLoop);
    };

    animationFrameId = requestAnimationFrame(scrollLoop);

    const handleMouseMove = (e: MouseEvent) => {
      const timelineRect = timelineRef.current?.getBoundingClientRect();
      if (!timelineRect) return;
      mousePositionRef.current = { x: e.clientX, y: e.clientY };
      const scrollLeft = timelineRef.current?.scrollLeft || 0;
      const x = e.clientX - timelineRect.left + scrollLeft - dragOffset;
      const rawTime = Math.max(0, x / pixelsPerSecond);
      const allTracks = useProjectStore.getState().project.timeline.tracks;
      const dragSnapSettings = { ...snapSettings, snapToPlayhead: false };
      const snapResult = calculateSnap(
        rawTime,
        shapeClip.id,
        allTracks,
        playheadPosition,
        dragSnapSettings,
        pixelsPerSecond,
        shapeClip.duration,
      );
      pendingDropRef.current = { time: snapResult.time };
      setDragTime(snapResult.time);
    };

    const handleMouseUp = () => {
      if (animationFrameId !== null) {
        cancelAnimationFrame(animationFrameId);
      }
      setIsDragging(false);
      const { time } = pendingDropRef.current;
      if (time !== shapeClip.startTime) {
        onMoveClip(shapeClip.id, time);
      }
      setDragTime(null);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    return () => {
      if (animationFrameId !== null) {
        cancelAnimationFrame(animationFrameId);
      }
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [
    isDragging,
    dragOffset,
    pixelsPerSecond,
    shapeClip.id,
    shapeClip.duration,
    shapeClip.startTime,
    onMoveClip,
    snapSettings,
    playheadPosition,
    timelineRef,
  ]);

  useEffect(() => {
    if (!isTrimming) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - trimStartRef.current.mouseX;
      const deltaTime = deltaX / pixelsPerSecond;

      if (isTrimming === "left") {
        const newStartTime = Math.max(
          0,
          trimStartRef.current.startTime + deltaTime,
        );
        const maxStartTime =
          trimStartRef.current.startTime + trimStartRef.current.duration - 0.1;
        const clampedStartTime = Math.min(newStartTime, maxStartTime);
        onTrim(shapeClip.id, "left", clampedStartTime);
      } else {
        const newEndTime =
          trimStartRef.current.startTime +
          trimStartRef.current.duration +
          deltaTime;
        const minEndTime = trimStartRef.current.startTime + 0.1;
        const clampedEndTime = Math.max(newEndTime, minEndTime);
        onTrim(shapeClip.id, "right", clampedEndTime);
      }
    };

    const handleMouseUp = () => {
      setIsTrimming(null);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isTrimming, shapeClip.id, pixelsPerSecond, onTrim]);

  const isShape = shapeClip.type === "shape";
  const isSticker = shapeClip.type === "sticker" || shapeClip.type === "emoji";
  const shapeLabel =
    isShape && "shapeType" in shapeClip
      ? shapeClip.shapeType.charAt(0).toUpperCase() +
        shapeClip.shapeType.slice(1)
      : isSticker
        ? shapeClip.type === "emoji"
          ? "Emoji"
          : "Sticker"
        : "SVG";
  const IconComponent = isShape ? Shapes : isSticker ? Smile : FileCode;
  const colorClass = isShape ? "green" : isSticker ? "pink" : "purple";

  const isInteracting = isDragging || isTrimming;
  const clipType = isShape ? "shape" : isSticker ? (shapeClip.type === "emoji" ? "emoji" : "sticker") : "svg";

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          ref={clipRef}
          onClick={handleClick}
          onMouseDown={handleMouseDown}
          className={`absolute top-1 bottom-1 rounded-lg overflow-hidden cursor-grab group ${
            isDragging ? "cursor-grabbing opacity-75" : ""
          } ${
            isSelected
              ? `ring-2 ring-${colorClass}-400 border-${colorClass}-400 z-10`
              : `border-${colorClass}-500/30 hover:border-${colorClass}-500/60 hover:brightness-110`
          } bg-${colorClass}-500/20 border`}
          style={{
            transform: `translateX(${left}px)`,
            width: `${Math.max(width, 40)}px`,
            willChange: isInteracting ? 'transform, width' : 'auto',
            transition: isInteracting ? 'none' : 'opacity 150ms, box-shadow 150ms',
          }}
        >
          <div
            className={`absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize hover:bg-${colorClass}-400/50 z-20 opacity-0 group-hover:opacity-100 transition-opacity`}
            onMouseDown={(e) => handleTrimStart(e, "left")}
            title="Drag to trim start"
          />
          <div
            className={`absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize hover:bg-${colorClass}-400/50 z-20 opacity-0 group-hover:opacity-100 transition-opacity`}
            onMouseDown={(e) => handleTrimStart(e, "right")}
            title="Drag to trim end"
          />
          <div className="w-full h-full flex items-center gap-1 px-3">
            <IconComponent
              size={12}
              className={`text-${colorClass}-400 flex-shrink-0`}
            />
            <span
              className={`text-[10px] font-medium text-${colorClass}-200 truncate`}
            >
              {shapeLabel}
            </span>
          </div>
          {isSelected && (
            <>
              <div className="absolute inset-0 border-2 border-green-400 rounded-lg pointer-events-none" />
              <div
                className="absolute left-0 top-1/2 -translate-y-1/2 w-1.5 h-6 bg-green-400 rounded-r cursor-ew-resize"
                onMouseDown={(e) => handleTrimStart(e, "left")}
              />
              <div
                className="absolute right-0 top-1/2 -translate-y-1/2 w-1.5 h-6 bg-green-400 rounded-l cursor-ew-resize"
                onMouseDown={(e) => handleTrimStart(e, "right")}
              />
            </>
          )}
        </div>
      </ContextMenuTrigger>
      <GraphicsClipContextMenu clip={shapeClip} clipType={clipType} />
    </ContextMenu>
  );
};
