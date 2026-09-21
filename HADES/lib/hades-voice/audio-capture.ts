/**
 * Browser microphone capture for HADES local voice.
 * Windows/browser-safe: secure-context checks, permission denial, clean track teardown.
 */

import type { AudioCaptureOptions, AudioDeviceInfo, MicState, VoiceCaptureMode } from "./types";

const DEFAULT_PRE_ROLL_MS = 180;
const DEFAULT_END_SILENCE_MS = 900;
const DEFAULT_SPEECH_THRESHOLD = 0.018;
const DEFAULT_TIMESLICE_MS = 250;
const METER_INTERVAL_MS = 50;

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof navigator !== "undefined";
}

export function voiceMediaSupported(): { ok: boolean; reason?: string } {
  if (!isBrowser()) return { ok: false, reason: "Geen browsermedia beschikbaar." };
  if (!window.isSecureContext) {
    return {
      ok: false,
      reason: "Microfoon vereist een beveiligde context (HTTPS of localhost). Open HADES via http://127.0.0.1.",
    };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, reason: "Deze browser ondersteunt geen microfoontoegang (getUserMedia)." };
  }
  return { ok: true };
}

export function pickRecorderMimeType(preferred?: string): string {
  if (typeof MediaRecorder === "undefined") return preferred || "audio/webm";
  const candidates = [
    preferred,
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ].filter(Boolean) as string[];
  for (const mime of candidates) {
    try {
      if (MediaRecorder.isTypeSupported(mime)) return mime;
    } catch {
      // ignore
    }
  }
  return "";
}

export async function enumerateAudioDevices(): Promise<AudioDeviceInfo[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices
      .filter((d) => d.kind === "audioinput" || d.kind === "audiooutput")
      .map((d) => ({
        deviceId: d.deviceId,
        label: d.label || (d.kind === "audioinput" ? "Microfoon" : "Luidspreker"),
        kind: d.kind,
      }));
  } catch {
    return [];
  }
}

function rmsFromTimeDomain(data: Uint8Array): number {
  if (!data.length) return 0;
  let sum = 0;
  for (let i = 0; i < data.length; i += 1) {
    const v = (data[i]! - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / data.length);
}

export type UtteranceHandler = (blob: Blob, mimeType: string) => void;

export class AudioCapture {
  private options: Required<
    Pick<
      AudioCaptureOptions,
      | "preRollMs"
      | "endSilenceMs"
      | "speechThreshold"
      | "timesliceMs"
      | "echoCancellation"
      | "noiseSuppression"
      | "autoGainControl"
    >
  > &
    AudioCaptureOptions;

  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private meterTimer: ReturnType<typeof setInterval> | null = null;
  private deviceListener: (() => void) | null = null;

  private state: MicState = "idle";
  private mode: VoiceCaptureMode = "continuous";
  private muted = false;
  private capturing = false;
  private speaking = false;
  private silenceMs = 0;
  private level = 0;

  private chunks: Blob[] = [];
  private preRoll: Blob[] = [];
  private preRollBytes = 0;
  private mimeType = "";
  private pushToTalkHeld = false;

  constructor(options: AudioCaptureOptions = {}) {
    this.options = {
      preRollMs: options.preRollMs ?? DEFAULT_PRE_ROLL_MS,
      endSilenceMs: options.endSilenceMs ?? DEFAULT_END_SILENCE_MS,
      speechThreshold: options.speechThreshold ?? DEFAULT_SPEECH_THRESHOLD,
      timesliceMs: options.timesliceMs ?? DEFAULT_TIMESLICE_MS,
      echoCancellation: options.echoCancellation ?? true,
      noiseSuppression: options.noiseSuppression ?? true,
      autoGainControl: options.autoGainControl ?? true,
      ...options,
    };
    this.mode = options.mode ?? "continuous";
  }

  getMicState(): MicState {
    return this.state;
  }

  getLevel(): number {
    return this.level;
  }

  isCapturing(): boolean {
    return this.capturing;
  }

  isMuted(): boolean {
    return this.muted;
  }

  setMode(mode: VoiceCaptureMode): void {
    this.mode = mode;
  }

  updateOptions(partial: Partial<AudioCaptureOptions>): void {
    Object.assign(this.options, partial);
    if (partial.mode) this.mode = partial.mode;
  }

  /** Must be called from a user gesture for permission prompts. */
  async requestPermissionAndStart(deviceId?: string | null): Promise<void> {
    const support = voiceMediaSupported();
    if (!support.ok) {
      this.setState(support.reason?.includes("beveiligde") ? "insecure" : "unsupported");
      this.options.onError?.(support.reason || "Microfoon niet beschikbaar.");
      throw new Error(support.reason || "Microfoon niet beschikbaar.");
    }

    this.setState("requesting");
    const constraints: MediaStreamConstraints = {
      audio: {
        echoCancellation: this.options.echoCancellation,
        noiseSuppression: this.options.noiseSuppression,
        autoGainControl: this.options.autoGainControl,
        ...(deviceId || this.options.deviceId
          ? { deviceId: { exact: deviceId || this.options.deviceId || undefined } }
          : {}),
      },
      video: false,
    };

    try {
      const gum =
        this.options.getUserMedia
        || navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      this.stream = await gum(constraints);
    } catch (err) {
      const name = err instanceof DOMException ? err.name : "";
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        this.setState("denied");
        const msg = "Microfoontoegang geweigerd. Sta de microfoon toe in de browsermeldingen of Windows-privacyinstellingen.";
        this.options.onError?.(msg);
        throw new Error(msg);
      }
      if (name === "NotFoundError" || name === "DevicesNotFoundError") {
        this.setState("error");
        const msg = "Geen microfoon gevonden. Sluit een microfoon aan en probeer opnieuw.";
        this.options.onError?.(msg);
        throw new Error(msg);
      }
      this.setState("error");
      const msg = err instanceof Error ? err.message : "Microfoon starten mislukt.";
      this.options.onError?.(msg);
      throw new Error(msg);
    }

    await this.afterStreamReady();
  }

  private async afterStreamReady(): Promise<void> {
    this.mimeType = pickRecorderMimeType(this.options.mimeType);
    this.setupMeter();
    this.setupRecorder();
    this.attachDeviceListener();
    this.capturing = true;
    this.setState(this.muted ? "muted" : "active");
    try {
      const devices = await enumerateAudioDevices();
      this.options.onDeviceChange?.(devices);
    } catch {
      // enumeration is best-effort
    }
  }

  private setupMeter(): void {
    if (!this.stream) return;
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctx) return;
      this.audioContext = new Ctx();
      this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 2048;
      this.analyser.smoothingTimeConstant = 0.8;
      this.sourceNode.connect(this.analyser);
      // Do not connect to destination — avoid feedback loop.
      const data = new Uint8Array(this.analyser.fftSize);
      this.meterTimer = setInterval(() => {
        if (!this.analyser || this.muted) {
          this.level = 0;
          this.options.onLevel?.(0);
          if (this.mode === "continuous" && this.speaking) {
            this.silenceMs += METER_INTERVAL_MS;
            if (this.silenceMs >= this.options.endSilenceMs) {
              void this.finalizeUtterance();
            }
          }
          return;
        }
        this.analyser.getByteTimeDomainData(data);
        const rms = rmsFromTimeDomain(data);
        this.level = rms;
        this.options.onLevel?.(rms);
        this.handleVad(rms);
      }, METER_INTERVAL_MS);
    } catch {
      // Meter is optional; recording can continue without it.
    }
  }

  private handleVad(rms: number): void {
    if (this.mode === "push_to_talk") {
      if (this.pushToTalkHeld && !this.speaking) {
        this.beginUtterance();
      } else if (!this.pushToTalkHeld && this.speaking) {
        void this.finalizeUtterance();
      }
      return;
    }

    // continuous energy VAD
    if (rms >= this.options.speechThreshold) {
      this.silenceMs = 0;
      if (!this.speaking) this.beginUtterance();
    } else if (this.speaking) {
      this.silenceMs += METER_INTERVAL_MS;
      if (this.silenceMs >= this.options.endSilenceMs) {
        void this.finalizeUtterance();
      }
    }
  }

  private setupRecorder(): void {
    if (!this.stream) return;
    if (typeof MediaRecorder === "undefined") {
      this.options.onError?.("MediaRecorder ontbreekt in deze browser.");
      return;
    }
    try {
      this.recorder = this.mimeType
        ? new MediaRecorder(this.stream, { mimeType: this.mimeType })
        : new MediaRecorder(this.stream);
      this.mimeType = this.recorder.mimeType || this.mimeType || "audio/webm";
    } catch (err) {
      try {
        this.recorder = new MediaRecorder(this.stream);
        this.mimeType = this.recorder.mimeType || "audio/webm";
      } catch {
        const msg = err instanceof Error ? err.message : "MediaRecorder starten mislukt.";
        this.options.onError?.(msg);
        return;
      }
    }

    this.recorder.ondataavailable = (event: BlobEvent) => {
      if (!event.data || event.data.size <= 0) return;
      if (this.speaking) {
        this.chunks.push(event.data);
        this.options.onChunk?.(event.data, this.mimeType, false);
      } else if (this.mode === "continuous") {
        this.pushPreRoll(event.data);
      }
    };

    this.recorder.onerror = () => {
      this.options.onError?.("Opnamefout van de microfoon.");
    };

    try {
      this.recorder.start(this.options.timesliceMs);
    } catch {
      try {
        this.recorder.start();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Opname starten mislukt.";
        this.options.onError?.(msg);
      }
    }
  }

  private pushPreRoll(blob: Blob): void {
    this.preRoll.push(blob);
    this.preRollBytes += blob.size;
    // Approximate time budget via chunk count * timeslice
    const maxChunks = Math.max(1, Math.ceil(this.options.preRollMs / this.options.timesliceMs));
    while (this.preRoll.length > maxChunks) {
      const dropped = this.preRoll.shift();
      if (dropped) this.preRollBytes -= dropped.size;
    }
  }

  private beginUtterance(): void {
    if (this.speaking) return;
    this.speaking = true;
    this.silenceMs = 0;
    this.chunks = this.preRoll.length ? [...this.preRoll] : [];
    this.preRoll = [];
    this.preRollBytes = 0;
    this.options.onSpeechStart?.();
  }

  private async finalizeUtterance(): Promise<void> {
    if (!this.speaking) return;
    this.speaking = false;
    this.silenceMs = 0;

    // Request a final chunk if possible
    if (this.recorder && this.recorder.state === "recording") {
      try {
        this.recorder.requestData();
      } catch {
        // optional
      }
      await new Promise((r) => setTimeout(r, 40));
    }

    const parts = this.chunks.slice();
    this.chunks = [];
    if (!parts.length) return;
    const blob = new Blob(parts, { type: this.mimeType || "audio/webm" });
    this.options.onChunk?.(blob, this.mimeType, true);
    this.options.onSpeechEnd?.(blob, this.mimeType);
  }

  /** Push-to-talk: call on pointer/key down (user gesture). */
  holdPushToTalk(down: boolean): void {
    this.mode = "push_to_talk";
    this.pushToTalkHeld = down;
    if (down) this.beginUtterance();
    else void this.finalizeUtterance();
  }

  /** Manually end current utterance (e.g. stop button in continuous mode). */
  async flushUtterance(): Promise<void> {
    await this.finalizeUtterance();
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    if (this.stream) {
      for (const track of this.stream.getAudioTracks()) {
        track.enabled = !muted;
      }
    }
    if (muted) {
      this.level = 0;
      this.options.onLevel?.(0);
      this.setState("muted");
    } else if (this.capturing) {
      this.setState("active");
    }
  }

  async switchDevice(deviceId: string): Promise<void> {
    const wasMuted = this.muted;
    const mode = this.mode;
    await this.stop();
    this.options.deviceId = deviceId;
    this.mode = mode;
    await this.requestPermissionAndStart(deviceId);
    if (wasMuted) this.setMuted(true);
  }

  private attachDeviceListener(): void {
    if (!navigator.mediaDevices?.addEventListener) return;
    this.detachDeviceListener();
    this.deviceListener = () => {
      void enumerateAudioDevices().then((devices) => this.options.onDeviceChange?.(devices));
    };
    navigator.mediaDevices.addEventListener("devicechange", this.deviceListener);
  }

  private detachDeviceListener(): void {
    if (this.deviceListener && navigator.mediaDevices?.removeEventListener) {
      navigator.mediaDevices.removeEventListener("devicechange", this.deviceListener);
    }
    this.deviceListener = null;
  }

  private setState(state: MicState): void {
    this.state = state;
    this.options.onStateChange?.(state);
  }

  async stop(): Promise<void> {
    if (this.speaking) {
      await this.finalizeUtterance();
    }
    if (this.meterTimer) {
      clearInterval(this.meterTimer);
      this.meterTimer = null;
    }
    this.detachDeviceListener();

    if (this.recorder) {
      try {
        if (this.recorder.state !== "inactive") this.recorder.stop();
      } catch {
        // ignore
      }
      this.recorder.ondataavailable = null;
      this.recorder.onerror = null;
      this.recorder = null;
    }

    try {
      this.sourceNode?.disconnect();
    } catch {
      // ignore
    }
    this.sourceNode = null;
    this.analyser = null;

    if (this.audioContext) {
      try {
        await this.audioContext.close();
      } catch {
        // ignore
      }
      this.audioContext = null;
    }

    if (this.stream) {
      for (const track of this.stream.getTracks()) {
        try {
          track.stop();
        } catch {
          // ignore
        }
      }
      this.stream = null;
    }

    this.chunks = [];
    this.preRoll = [];
    this.capturing = false;
    this.speaking = false;
    this.pushToTalkHeld = false;
    this.level = 0;
    this.options.onLevel?.(0);
    this.setState("idle");
  }
}

export async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const slice = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...slice);
  }
  return btoa(binary);
}
