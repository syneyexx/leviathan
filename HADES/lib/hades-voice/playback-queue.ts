/**
 * Ordered TTS playback queue with generation-based cancellation and barge-in.
 */

import type { PlaybackQueueOptions, VoiceAudioSegment } from "./types";

type SinkCapableAudio = HTMLAudioElement & {
  setSinkId?: (deviceId: string) => Promise<void>;
};

function base64ToBlob(b64: string, mimeType: string): Blob {
  const binary = atob(b64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mimeType || "audio/wav" });
}

export function segmentFromBase64(params: {
  sessionId: string;
  turnId: string;
  responseId: string;
  order: number;
  generation: number;
  mimeType: string;
  sampleRate?: number;
  audioBase64: string;
  text?: string;
}): VoiceAudioSegment {
  return {
    sessionId: params.sessionId,
    turnId: params.turnId,
    responseId: params.responseId,
    order: params.order,
    generation: params.generation,
    mimeType: params.mimeType,
    sampleRate: params.sampleRate,
    blob: base64ToBlob(params.audioBase64, params.mimeType),
    text: params.text,
  };
}

export class PlaybackQueue {
  private queue: VoiceAudioSegment[] = [];
  private generation = 1;
  private playing = false;
  private stopped = false;
  private volume = 1;
  private outputDeviceId: string | null = null;
  private audio: SinkCapableAudio | null = null;
  private objectUrl: string | null = null;
  private current: VoiceAudioSegment | null = null;
  private interruptStartedAt: number | null = null;
  private lastInterruptLatencyMs: number | null = null;
  private options: PlaybackQueueOptions;
  private pumpScheduled = false;

  constructor(options: PlaybackQueueOptions = {}) {
    this.options = options;
    this.volume = options.volume ?? 1;
    this.outputDeviceId = options.outputDeviceId ?? null;
  }

  getGeneration(): number {
    return this.generation;
  }

  isPlaying(): boolean {
    return this.playing;
  }

  getLastInterruptLatencyMs(): number | null {
    return this.lastInterruptLatencyMs;
  }

  getCurrent(): VoiceAudioSegment | null {
    return this.current;
  }

  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1, volume));
    if (this.audio) this.audio.volume = this.volume;
  }

  async setOutputDevice(deviceId: string | null): Promise<void> {
    this.outputDeviceId = deviceId;
    if (this.audio?.setSinkId && deviceId) {
      try {
        await this.audio.setSinkId(deviceId);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Uitvoerapparaat instellen mislukt.";
        this.options.onError?.(msg);
      }
    }
  }

  /** Cancel pending/playing audio by bumping generation; stale segments are ignored. */
  bumpGeneration(): number {
    this.generation += 1;
    this.queue = [];
    return this.generation;
  }

  /** Align local generation with server (cancels stale items when advancing). */
  alignGeneration(generation: number): number {
    if (generation > this.generation) {
      this.generation = generation;
      this.queue = [];
    } else if (generation === this.generation) {
      // already aligned
    } else {
      // Server restarted lower — reset to match.
      this.generation = Math.max(1, generation);
      this.queue = [];
    }
    return this.generation;
  }

  enqueue(segment: VoiceAudioSegment): boolean {
    if (segment.generation !== this.generation) return false;
    this.stopped = false;
    this.queue.push(segment);
    this.queue.sort((a, b) => {
      if (a.responseId === b.responseId) return a.order - b.order;
      return a.order - b.order;
    });
    this.schedulePump();
    return true;
  }

  enqueueBase64(params: {
    sessionId: string;
    turnId: string;
    responseId: string;
    order: number;
    generation: number;
    mimeType: string;
    sampleRate?: number;
    audioBase64: string;
    text?: string;
  }): boolean {
    return this.enqueue(segmentFromBase64(params));
  }

  /** Barge-in / stop within target; measures interrupt latency when possible. */
  stop(reason = "user"): number {
    this.interruptStartedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
    this.bumpGeneration();
    this.stopped = true;
    this.clearCurrentAudio();
    const ended = typeof performance !== "undefined" ? performance.now() : Date.now();
    this.lastInterruptLatencyMs = Math.max(0, Math.round(ended - this.interruptStartedAt));
    this.interruptStartedAt = null;
    this.setPlaying(false);
    this.options.onInterrupt?.(this.lastInterruptLatencyMs);
    void reason;
    return this.lastInterruptLatencyMs;
  }

  private schedulePump(): void {
    if (this.pumpScheduled) return;
    this.pumpScheduled = true;
    queueMicrotask(() => {
      this.pumpScheduled = false;
      void this.pump();
    });
  }

  private async pump(): Promise<void> {
    if (this.playing || this.stopped) return;
    const next = this.queue.shift();
    if (!next) {
      this.setPlaying(false);
      this.current = null;
      return;
    }
    if (next.generation !== this.generation) {
      this.schedulePump();
      return;
    }
    await this.playSegment(next);
  }

  private async playSegment(segment: VoiceAudioSegment): Promise<void> {
    this.current = segment;
    this.setPlaying(true);
    this.options.onSegmentStart?.(segment);

    this.clearObjectUrl();
    const url = URL.createObjectURL(segment.blob);
    this.objectUrl = url;

    const audio = document.createElement("audio") as SinkCapableAudio;
    audio.preload = "auto";
    audio.src = url;
    audio.volume = this.volume;
    this.audio = audio;

    if (this.outputDeviceId && audio.setSinkId) {
      try {
        await audio.setSinkId(this.outputDeviceId);
      } catch {
        // continue with default output
      }
    }

    const genAtStart = this.generation;

    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      audio.onended = () => finish();
      audio.onerror = () => {
        this.options.onError?.("Afspelen van spraaksegment mislukt.");
        finish();
      };
      void audio.play().catch((err) => {
        const msg = err instanceof Error ? err.message : "Afspelen geblokkeerd of mislukt.";
        this.options.onError?.(msg);
        finish();
      });
    });

    if (genAtStart === this.generation) {
      this.options.onSegmentEnd?.(segment);
    }

    this.clearCurrentAudio();
    this.current = null;
    this.setPlaying(false);

    if (genAtStart === this.generation && !this.stopped) {
      this.schedulePump();
    }
  }

  private clearCurrentAudio(): void {
    if (this.audio) {
      try {
        this.audio.pause();
        this.audio.removeAttribute("src");
        this.audio.load();
      } catch {
        // ignore
      }
      this.audio.onended = null;
      this.audio.onerror = null;
      this.audio = null;
    }
    this.clearObjectUrl();
  }

  private clearObjectUrl(): void {
    if (this.objectUrl) {
      try {
        URL.revokeObjectURL(this.objectUrl);
      } catch {
        // ignore
      }
      this.objectUrl = null;
    }
  }

  private setPlaying(playing: boolean): void {
    if (this.playing === playing) return;
    this.playing = playing;
    this.options.onPlayingChange?.(playing);
  }

  dispose(): void {
    this.stop("dispose");
  }
}

/** Play a single WAV/audio blob (one-shot), returns stop handle. */
export function playAudioBlob(
  blob: Blob,
  opts: { volume?: number; outputDeviceId?: string | null; signal?: AbortSignal } = {},
): { stop: () => number; done: Promise<void>; interruptLatencyMs: () => number | null } {
  let latency: number | null = null;
  let resolveDone: (() => void) | null = null;
  let sawPlay = false;

  const done = new Promise<void>((resolve) => {
    resolveDone = resolve;
  });

  const queue = new PlaybackQueue({
    volume: opts.volume,
    outputDeviceId: opts.outputDeviceId,
    onPlayingChange: (playing) => {
      if (playing) sawPlay = true;
      else if (sawPlay) resolveDone?.();
    },
  });

  queue.enqueue({
    sessionId: "oneshot",
    turnId: "oneshot",
    responseId: "oneshot",
    order: 0,
    generation: queue.getGeneration(),
    mimeType: blob.type || "audio/wav",
    blob,
  });

  window.setTimeout(() => {
    if (!sawPlay) resolveDone?.();
  }, 400);

  if (opts.signal) {
    const onAbort = () => {
      latency = queue.stop("abort");
      resolveDone?.();
    };
    if (opts.signal.aborted) onAbort();
    else opts.signal.addEventListener("abort", onAbort, { once: true });
  }

  return {
    stop: () => {
      latency = queue.stop("user");
      resolveDone?.();
      return latency;
    },
    done,
    interruptLatencyMs: () => latency ?? queue.getLastInterruptLatencyMs(),
  };
}
