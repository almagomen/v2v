export {
  TrackManager,
  createTrack,
  cloneTrack,
  getTrackClips,
  canAcceptMediaType,
  type TrackManagerOptions,
  type CreateTrackParams,
  type TrackOperationResult,
} from "./track-manager";

export {
  ClipManager,
  createClip,
  cloneClip,
  getClipEndTime,
  clipsOverlap,
  getGapBetweenClips,
  type ClipManagerOptions,
  type AddClipParams,
  type MoveClipParams,
  type ClipOperationResult,
  type SnapResult,
} from "./clip-manager";

export {
  NestedSequenceEngine,
  getNestedSequenceEngine,
  resetNestedSequenceEngine,
  type CompoundClip,
  type CompoundClipContent,
  type CompoundClipInstance,
  type CreateCompoundClipOptions,
  type FlattenResult,
} from "./nested-sequence-engine";
