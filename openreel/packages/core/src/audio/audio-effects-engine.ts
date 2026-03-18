import type { Effect } from "../types/timeline";
import type { AudioEffectParams, EQBand } from "../types/effects";
import { FFT } from "./fft";

export interface AudioEffectChainConfig {
  readonly effects: Effect[];
  readonly sampleRate?: number;
}

export interface ReverbConfig {
  readonly roomSize: number; // 0 to 1
  readonly damping: number; // 0 to 1
  readonly wetLevel: number; // 0 to 1
  readonly dryLevel: number; // 0 to 1
  readonly preDelay: number; // 0 to 100 ms
}

export interface SimpleNoiseProfile {
  readonly frequencyBins: Float32Array;
  readonly magnitudes: Float32Array;
  readonly sampleRate: number;
}

export interface EffectProcessingResult {
  readonly buffer: AudioBuffer;
  readonly appliedEffects: string[];
}

interface EffectNodePair {
  input: AudioNode;
  output: AudioNode;
}

export class AudioEffectsEngine {
  private audioContext: AudioContext | OfflineAudioContext | null = null;
  private impulseResponses: Map<string, AudioBuffer> = new Map();
  private noiseProfiles: Map<string, SimpleNoiseProfile> = new Map();
  private initialized = false;

  constructor(context?: AudioContext | OfflineAudioContext) {
    this.audioContext = context || null;
  }

  async initialize(
    context?: AudioContext | OfflineAudioContext,
  ): Promise<void> {
    if (context) {
      this.audioContext = context;
    }

    if (!this.audioContext) {
      this.audioContext = new AudioContext({
        latencyHint: "interactive",
        sampleRate: 48000,
      });
    }

    this.initialized = true;
  }

  isInitialized(): boolean {
    return this.initialized && this.audioContext !== null;
  }

  getAudioContext(): AudioContext | OfflineAudioContext {
    this.ensureInitialized();
    return this.audioContext!;
  }

  private ensureInitialized(): void {
    if (!this.initialized || !this.audioContext) {
      throw new Error(
        "AudioEffectsEngine not initialized. Call initialize() first.",
      );
    }
  }

  async applyEffectChain(
    buffer: AudioBuffer,
    effects: Effect[],
  ): Promise<EffectProcessingResult> {
    this.ensureInitialized();

    const enabledEffects = effects.filter((e) => e.enabled);
    if (enabledEffects.length === 0) {
      return { buffer, appliedEffects: [] };
    }
    const offlineContext = new OfflineAudioContext(
      buffer.numberOfChannels,
      buffer.length,
      buffer.sampleRate,
    );
    const source = offlineContext.createBufferSource();
    source.buffer = buffer;
    const { firstNode, lastNode, appliedEffects } = await this.buildEffectChain(
      offlineContext,
      enabledEffects,
    );
    if (firstNode && lastNode) {
      source.connect(firstNode);
      lastNode.connect(offlineContext.destination);
    } else {
      source.connect(offlineContext.destination);
    }

    source.start(0);

    const processedBuffer = await offlineContext.startRendering();

    return {
      buffer: processedBuffer,
      appliedEffects,
    };
  }

  private async buildEffectChain(
    context: BaseAudioContext,
    effects: Effect[],
  ): Promise<{
    firstNode: AudioNode | null;
    lastNode: AudioNode | null;
    appliedEffects: string[];
  }> {
    let firstNode: AudioNode | null = null;
    let lastNode: AudioNode | null = null;
    const appliedEffects: string[] = [];

    for (const effect of effects) {
      if (!effect.enabled) {
        continue;
      }

      const nodePair = await this.createEffectNode(context, effect);
      if (!nodePair) {
        continue;
      }

      appliedEffects.push(effect.type);

      if (!firstNode) {
        firstNode = nodePair.input;
      }

      if (lastNode) {
        lastNode.connect(nodePair.input);
      }

      lastNode = nodePair.output;
    }

    return { firstNode, lastNode, appliedEffects };
  }

  private async createEffectNode(
    context: BaseAudioContext,
    effect: Effect,
  ): Promise<EffectNodePair | null> {
    switch (effect.type) {
      case "eq":
        return this.createEQNodePair(context, effect);
      case "compressor":
        return this.createCompressorNodePair(context, effect);
      case "reverb":
        return await this.createReverbNode(context, effect);
      case "delay":
        return this.createDelayNode(context, effect);
      case "noiseReduction":
        return this.createNoiseReductionNodePair(context, effect);
      case "gain":
        return this.createGainNodePair(context, effect);
      default:
        return null;
    }
  }

  private createEQNodePair(
    context: BaseAudioContext,
    effect: Effect,
  ): EffectNodePair | null {
    const params = effect.params as AudioEffectParams["eq"];
    const bands = params?.bands;

    if (!bands || bands.length === 0) {
      return null;
    }

    let firstNode: BiquadFilterNode | null = null;
    let lastNode: BiquadFilterNode | null = null;

    for (const band of bands) {
      const filter = context.createBiquadFilter();
      filter.type = this.mapEQBandType(band.type);
      filter.frequency.value = Math.max(20, Math.min(20000, band.frequency));
      filter.gain.value = Math.max(-24, Math.min(24, band.gain));
      filter.Q.value = Math.max(0.1, Math.min(18, band.q));

      if (!firstNode) {
        firstNode = filter;
      }

      if (lastNode) {
        lastNode.connect(filter);
      }

      lastNode = filter;
    }

    if (!firstNode || !lastNode) return null;
    return { input: firstNode, output: lastNode };
  }

  createEQNode(context: BaseAudioContext, effect: Effect): AudioNode | null {
    const pair = this.createEQNodePair(context, effect);
    return pair?.input ?? null;
  }

  private mapEQBandType(type: EQBand["type"]): BiquadFilterType {
    const typeMap: Record<EQBand["type"], BiquadFilterType> = {
      lowshelf: "lowshelf",
      highshelf: "highshelf",
      peaking: "peaking",
      lowpass: "lowpass",
      highpass: "highpass",
      notch: "notch",
    };
    return typeMap[type] || "peaking";
  }

  private createCompressorNodePair(
    context: BaseAudioContext,
    effect: Effect,
  ): EffectNodePair {
    const compressor = this.createCompressorNode(context, effect);
    return { input: compressor, output: compressor };
  }

  createCompressorNode(
    context: BaseAudioContext,
    effect: Effect,
  ): DynamicsCompressorNode {
    const params = effect.params as AudioEffectParams["compressor"];
    const compressor = context.createDynamicsCompressor();

    compressor.threshold.value = Math.max(
      -60,
      Math.min(0, params?.threshold ?? -24),
    );
    compressor.ratio.value = Math.max(1, Math.min(20, params?.ratio ?? 4));
    compressor.attack.value = Math.max(
      0.001,
      Math.min(1, params?.attack ?? 0.003),
    );
    compressor.release.value = Math.max(
      0.01,
      Math.min(3, params?.release ?? 0.25),
    );
    compressor.knee.value = Math.max(0, Math.min(40, params?.knee ?? 30));

    return compressor;
  }

  async createReverbNode(
    context: BaseAudioContext,
    effect: Effect,
  ): Promise<EffectNodePair> {
    const params = effect.params as AudioEffectParams["reverb"];

    const inputGain = context.createGain();
    const dryGain = context.createGain();
    const wetGain = context.createGain();
    const outputGain = context.createGain();
    const convolver = context.createConvolver();

    dryGain.gain.value = params?.dryLevel ?? 0.7;
    wetGain.gain.value = params?.wetLevel ?? 0.5;

    const impulseResponse = await this.getOrCreateImpulseResponse(
      context,
      params?.roomSize ?? 0.5,
      params?.damping ?? 0.5,
    );
    convolver.buffer = impulseResponse;

    let preDelayNode: DelayNode | null = null;
    if (params?.preDelay && params.preDelay > 0) {
      preDelayNode = context.createDelay(0.1);
      preDelayNode.delayTime.value = Math.min(0.1, params.preDelay / 1000);
    }

    inputGain.connect(dryGain);
    dryGain.connect(outputGain);

    if (preDelayNode) {
      inputGain.connect(preDelayNode);
      preDelayNode.connect(convolver);
    } else {
      inputGain.connect(convolver);
    }
    convolver.connect(wetGain);
    wetGain.connect(outputGain);

    return { input: inputGain, output: outputGain };
  }

  private async getOrCreateImpulseResponse(
    context: BaseAudioContext,
    roomSize: number,
    damping: number,
  ): Promise<AudioBuffer> {
    const key = `${roomSize.toFixed(2)}_${damping.toFixed(2)}`;

    if (this.impulseResponses.has(key)) {
      return this.impulseResponses.get(key)!;
    }

    const impulseResponse = this.generateImpulseResponse(
      context,
      roomSize,
      damping,
    );
    this.impulseResponses.set(key, impulseResponse);

    return impulseResponse;
  }

  generateImpulseResponse(
    context: BaseAudioContext,
    roomSize: number,
    damping: number,
  ): AudioBuffer {
    const sampleRate = context.sampleRate;
    // Duration based on room size (0.5s to 4s)
    const duration = 0.5 + roomSize * 3.5;
    const length = Math.floor(sampleRate * duration);
    const channels = 2;

    const impulseBuffer = context.createBuffer(channels, length, sampleRate);

    for (let channel = 0; channel < channels; channel++) {
      const channelData = impulseBuffer.getChannelData(channel);

      for (let i = 0; i < length; i++) {
        const t = i / sampleRate;
        // Exponential decay
        const decay = Math.exp((-3 * t) / duration);
        // Random noise with decay
        const noise = (Math.random() * 2 - 1) * decay;
        const dampingFactor = 1 - (damping * t) / duration;
        channelData[i] = noise * dampingFactor;
      }
    }

    return impulseBuffer;
  }

  createDelayNode(context: BaseAudioContext, effect: Effect): EffectNodePair {
    const params = effect.params as AudioEffectParams["delay"];

    const inputGain = context.createGain();
    const delayNode = context.createDelay(2);
    const feedbackGain = context.createGain();
    const wetGain = context.createGain();
    const dryGain = context.createGain();
    const outputGain = context.createGain();

    delayNode.delayTime.value = Math.max(0, Math.min(2, params?.time ?? 0.5));
    feedbackGain.gain.value = Math.max(
      0,
      Math.min(0.95, params?.feedback ?? 0.3),
    );
    wetGain.gain.value = params?.wetLevel ?? 0.5;
    dryGain.gain.value = 1 - (params?.wetLevel ?? 0.5);

    inputGain.connect(dryGain);
    dryGain.connect(outputGain);

    inputGain.connect(delayNode);
    delayNode.connect(feedbackGain);
    feedbackGain.connect(delayNode);
    delayNode.connect(wetGain);
    wetGain.connect(outputGain);

    return { input: inputGain, output: outputGain };
  }

  private createGainNodePair(
    context: BaseAudioContext,
    effect: Effect,
  ): EffectNodePair {
    const gainNode = this.createGainNode(context, effect);
    return { input: gainNode, output: gainNode };
  }

  createGainNode(context: BaseAudioContext, effect: Effect): GainNode {
    const params = effect.params as AudioEffectParams["gain"];
    const gainNode = context.createGain();
    gainNode.gain.value = Math.max(0, Math.min(4, params?.value ?? 1));
    return gainNode;
  }

  private createNoiseReductionNodePair(
    context: BaseAudioContext,
    effect: Effect,
  ): EffectNodePair {
    const params = effect.params as AudioEffectParams["noiseReduction"];

    const inputGain = context.createGain();
    const outputGain = context.createGain();

    const bands = this.createNoiseReductionBands(context, params);

    for (const band of bands) {
      inputGain.connect(band.filter);
      band.filter.connect(band.gate);
      band.gate.connect(outputGain);
    }

    return { input: inputGain, output: outputGain };
  }

  createNoiseReductionNode(
    context: BaseAudioContext,
    effect: Effect,
  ): AudioNode {
    const pair = this.createNoiseReductionNodePair(context, effect);
    return pair.input;
  }

  private createNoiseReductionBands(
    context: BaseAudioContext,
    params?: AudioEffectParams["noiseReduction"],
  ): Array<{ filter: BiquadFilterNode; gate: GainNode }> {
    const threshold = params?.threshold ?? -40;
    const reduction = params?.reduction ?? 0.5;
    const thresholdLinear = Math.pow(10, threshold / 20);

    // Define frequency bands (octave-based)
    const frequencies = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
    const bands: Array<{ filter: BiquadFilterNode; gate: GainNode }> = [];

    for (let i = 0; i < frequencies.length; i++) {
      const filter = context.createBiquadFilter();
      filter.type = "peaking";
      filter.frequency.value = frequencies[i];
      filter.Q.value = 1.4; // ~1 octave bandwidth

      const gate = context.createGain();
      // Lower frequencies typically have more noise, apply more reduction
      const frequencyFactor = 1 - (i / frequencies.length) * 0.3;
      // Scale reduction by threshold sensitivity
      const thresholdScale = Math.min(1, thresholdLinear * 10);
      gate.gain.value = 1 - reduction * frequencyFactor * thresholdScale;

      bands.push({ filter, gate });
    }

    return bands;
  }

  async learnNoiseProfile(
    buffer: AudioBuffer,
    profileId: string,
  ): Promise<SimpleNoiseProfile> {
    this.ensureInitialized();

    const fftSize = 2048;
    const hopSize = fftSize / 2; // 50% overlap for better frequency resolution
    const channelData = buffer.getChannelData(0);
    const numFrames = Math.max(
      1,
      Math.floor((channelData.length - fftSize) / hopSize) + 1,
    );
    const fft = new FFT(fftSize);

    // Accumulate magnitude spectrum across all frames
    const magnitudes = new Float32Array(fftSize / 2);
    const frameBuffer = new Float32Array(fftSize);

    for (let frame = 0; frame < numFrames; frame++) {
      const start = frame * hopSize;
      for (let i = 0; i < fftSize; i++) {
        frameBuffer[i] = channelData[start + i] || 0;
      }
      const windowedFrame = fft.applyHannWindow(frameBuffer);

      // Perform FFT
      const { real, imag } = fft.forward(windowedFrame);

      // Accumulate magnitude spectrum
      const frameMagnitude = fft.getMagnitude(real, imag);
      for (let i = 0; i < magnitudes.length; i++) {
        magnitudes[i] += frameMagnitude[i];
      }
    }

    // Average the magnitudes across all frames
    for (let i = 0; i < magnitudes.length; i++) {
      magnitudes[i] /= numFrames;
    }
    const frequencyBins = new Float32Array(fftSize / 2);
    const binWidth = buffer.sampleRate / fftSize;
    for (let i = 0; i < frequencyBins.length; i++) {
      frequencyBins[i] = i * binWidth;
    }

    const profile: SimpleNoiseProfile = {
      frequencyBins,
      magnitudes,
      sampleRate: buffer.sampleRate,
    };

    this.noiseProfiles.set(profileId, profile);

    return profile;
  }

  getNoiseProfile(profileId: string): SimpleNoiseProfile | undefined {
    return this.noiseProfiles.get(profileId);
  }

  async applyNoiseReductionWithProfile(
    buffer: AudioBuffer,
    profileId: string,
    reduction: number = 0.5,
  ): Promise<AudioBuffer> {
    this.ensureInitialized();

    const profile = this.noiseProfiles.get(profileId);
    if (!profile) {
      throw new Error(`Noise profile '${profileId}' not found`);
    }
    const offlineContext = new OfflineAudioContext(
      buffer.numberOfChannels,
      buffer.length,
      buffer.sampleRate,
    );

    const source = offlineContext.createBufferSource();
    source.buffer = buffer;
    const inputGain = offlineContext.createGain();
    const outputGain = offlineContext.createGain();
    const filters = this.createProfileBasedFilters(
      offlineContext,
      profile,
      reduction,
    );

    source.connect(inputGain);

    if (filters.length > 0) {
      // Chain filters in series for cumulative noise reduction
      let lastNode: AudioNode = inputGain;
      for (const filter of filters) {
        lastNode.connect(filter);
        lastNode = filter;
      }
      lastNode.connect(outputGain);
    } else {
      inputGain.connect(outputGain);
    }

    outputGain.connect(offlineContext.destination);
    source.start(0);

    return offlineContext.startRendering();
  }

  private createProfileBasedFilters(
    context: BaseAudioContext,
    profile: SimpleNoiseProfile,
    reduction: number,
  ): BiquadFilterNode[] {
    const filters: BiquadFilterNode[] = [];
    const magnitudes = profile.magnitudes;
    const frequencyBins = profile.frequencyBins;
    const { mean, stdDev } = this.calculateNoiseStatistics(magnitudes);
    const peakThreshold = mean + stdDev * 2; // Peaks are 2 std devs above mean

    // Track which frequency regions have been addressed
    const addressedBins = new Set<number>();

    // Pass 1: Identify and filter tonal noise peaks (narrow-band noise like hum or buzz)
    // Tonal noise has narrow frequency bandwidth, so we use notch filters for surgical removal
    for (let i = 2; i < magnitudes.length - 2; i++) {
      const mag = magnitudes[i];
      const freq = frequencyBins[i];

      // Skip very low frequencies (handled separately) and already addressed bins
      if (freq < 60 || addressedBins.has(i)) continue;

      // Detect local peaks using 5-point comparison for robustness against noise
      const isPeak =
        mag > magnitudes[i - 2] &&
        mag > magnitudes[i - 1] &&
        mag > magnitudes[i + 1] &&
        mag > magnitudes[i + 2] &&
        mag > peakThreshold;

      if (isPeak) {
        const filter = context.createBiquadFilter();
        filter.type = "notch"; // Narrow-band attenuation
        filter.frequency.value = Math.max(20, Math.min(20000, freq));
        // Peak sharpness determines Q (quality factor): sharper peaks need narrower filters
        const peakSharpness =
          mag / ((magnitudes[i - 1] + magnitudes[i + 1]) / 2);
        filter.Q.value = Math.min(30, Math.max(5, peakSharpness * 10));

        filters.push(filter);

        // Mark surrounding bins as addressed to avoid overlapping filters
        for (let j = i - 2; j <= i + 2; j++) {
          addressedBins.add(j);
        }
      }
    }

    // Pass 2: Add broadband noise reduction using parametric EQ
    // Broadband noise (like air conditioning) is spread across frequencies; use gentle EQ reduction
    // Divide spectrum into musical octave-based bands for natural-sounding processing
    const bandCenters = [125, 250, 500, 1000, 2000, 4000, 8000];
    const binWidth = profile.sampleRate / (magnitudes.length * 2);

    for (const centerFreq of bandCenters) {
      const binIndex = Math.round(centerFreq / binWidth);
      if (binIndex >= magnitudes.length || addressedBins.has(binIndex))
        continue;

      // Calculate local average energy for this frequency band
      const bandStart = Math.max(0, binIndex - 5);
      const bandEnd = Math.min(magnitudes.length - 1, binIndex + 5);
      let bandAvg = 0;
      for (let i = bandStart; i <= bandEnd; i++) {
        bandAvg += magnitudes[i];
      }
      bandAvg /= bandEnd - bandStart + 1;

      // Only reduce bands with elevated noise (>20% above mean)
      if (bandAvg > mean * 1.2) {
        const filter = context.createBiquadFilter();
        filter.type = "peaking"; // Gentle reduction vs surgical notch
        filter.frequency.value = centerFreq;
        filter.Q.value = 1.4; // ~1 octave bandwidth for natural sound
        // Gain reduction proportional to noise excess above baseline
        const noiseRatio = (bandAvg - mean) / mean;
        const gainReduction = -reduction * Math.min(12, noiseRatio * 6);
        filter.gain.value = gainReduction;

        filters.push(filter);
      }
    }

    // Pass 3: Add high-pass filter for low frequency rumble (wind noise, vibration, etc.)
    // Low frequency energy concentrated <200Hz is typically noise, not signal
    const lowFreqEnergy = this.calculateLowFrequencyEnergy(
      magnitudes,
      binWidth,
    );
    if (lowFreqEnergy > mean * 1.5) {
      const highpass = context.createBiquadFilter();
      highpass.type = "highpass";
      highpass.frequency.value = 80;
      highpass.Q.value = 0.707; // Butterworth: maximally flat response
      filters.push(highpass);
    }
    // Fallback: always add minimal high-pass to remove DC/sub-bass artifacts
    if (filters.length === 0) {
      const highpass = context.createBiquadFilter();
      highpass.type = "highpass";
      highpass.frequency.value = 60;
      highpass.Q.value = 0.5;
      filters.push(highpass);
    }

    return filters;
  }

  private calculateNoiseStatistics(magnitudes: Float32Array): {
    mean: number;
    stdDev: number;
  } {
    let sum = 0;
    for (let i = 0; i < magnitudes.length; i++) {
      sum += magnitudes[i];
    }
    const mean = sum / magnitudes.length;

    let varianceSum = 0;
    for (let i = 0; i < magnitudes.length; i++) {
      const diff = magnitudes[i] - mean;
      varianceSum += diff * diff;
    }
    const stdDev = Math.sqrt(varianceSum / magnitudes.length);

    return { mean, stdDev };
  }

  private calculateLowFrequencyEnergy(
    magnitudes: Float32Array,
    binWidth: number,
  ): number {
    const maxBin = Math.min(magnitudes.length, Math.ceil(200 / binWidth));
    let energy = 0;
    for (let i = 0; i < maxBin; i++) {
      energy += magnitudes[i];
    }
    return energy / maxBin;
  }

  clearImpulseResponseCache(): void {
    this.impulseResponses.clear();
  }

  clearNoiseProfiles(): void {
    this.noiseProfiles.clear();
  }

  async dispose(): Promise<void> {
    this.clearImpulseResponseCache();
    this.clearNoiseProfiles();

    if (this.audioContext && "close" in this.audioContext) {
      await (this.audioContext as AudioContext).close();
    }

    this.audioContext = null;
    this.initialized = false;
  }
}
let audioEffectsEngineInstance: AudioEffectsEngine | null = null;

export function getAudioEffectsEngine(): AudioEffectsEngine {
  if (!audioEffectsEngineInstance) {
    audioEffectsEngineInstance = new AudioEffectsEngine();
  }
  return audioEffectsEngineInstance;
}

export async function initializeAudioEffectsEngine(
  context?: AudioContext | OfflineAudioContext,
): Promise<AudioEffectsEngine> {
  const engine = getAudioEffectsEngine();
  await engine.initialize(context);
  return engine;
}
