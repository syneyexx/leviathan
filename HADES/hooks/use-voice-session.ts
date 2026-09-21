"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ensureClientTabId, voiceApi } from "@/lib/hades-voice/api";
import { AudioCapture, blobToBase64, voiceMediaSupported } from "@/lib/hades-voice/audio-capture";
import { PlaybackQueue } from "@/lib/hades-voice/playback-queue";
import {
  VOICE_TAB_STORAGE_KEY,
  createInitialVoiceSessionState,
  type MicState,
  type VoiceCaptureMode,
  type VoiceEvent,
  type VoiceSessionState,
  type VoiceStatus,
  type VoiceUiStatus,
} from "@/lib/hades-voice/types";

export type UseVoiceSessionOptions = {
  conversationId?: string | null;
  language?: string;
  mode?: VoiceCaptureMode;
  keepAudio?: boolean;
  endSilenceMs?: number;
  speechThreshold?: number;
  bargeIn?: boolean;
  wakeWordEnabled?: boolean;
  inputDeviceId?: string | null;
  outputDeviceId?: string | null;
  volume?: number;
  idleTimeoutSeconds?: number;
  /** Called when a final user transcript should be sent as a chat message. */
  onUserUtterance?: (text: string, meta: { turnId: string; sessionId: string }) => void | Promise<void>;
  onStatusChange?: (status: VoiceUiStatus) => void;
  onError?: (message: string) => void;
  onOpenSettings?: () => void;
};

export type UseVoiceSessionResult = {
  state: VoiceSessionState;
  status: VoiceUiStatus;
  micActive: boolean;
  modelGenerating: boolean;
  audioPlaying: boolean;
  outputMuted: boolean;
  level: number;
  voiceReady: boolean | null;
  doctor: VoiceStatus | null;
  lastInterruptLatencyMs: number | null;
  turnMode: VoiceCaptureMode;
  interrupted: boolean;
  startSession: (opts?: { force?: boolean }) => Promise<void>;
  stopSession: () => Promise<void>;
  interrupt: () => Promise<void>;
  setMicMuted: (muted: boolean) => void;
  setOutputMuted: (muted: boolean) => void;
  holdPushToTalk: (down: boolean) => void;
  /** After assistant finishes generating — synthesize & play spoken response. */
  speakAssistantResponse: (text: string, responseId: string, opts?: { forceReplay?: boolean }) => Promise<void>;
  setModelGenerating: (generating: boolean) => void;
  refreshDoctor: () => Promise<VoiceStatus | null>;
  installVoice: (steps?: string[]) => Promise<Record<string, unknown>>;
  clearInterrupted: () => void;
};

function deriveStatus(flags: {
  micState: MicState;
  micActive: boolean;
  processing: boolean;
  modelGenerating: boolean;
  audioPlaying: boolean;
  interrupted: boolean;
  reconnecting: boolean;
  sessionActive: boolean;
}): VoiceUiStatus {
  if (flags.reconnecting) return "Verbinding herstellen";
  if (flags.interrupted) return "Onderbroken";
  if (!flags.sessionActive) return flags.micState === "idle" ? "idle" : "stopped";
  if (flags.micState === "requesting" || flags.micState === "denied" || flags.micState === "insecure") {
    return "Microfoon toestaan";
  }
  if (flags.audioPlaying) return "Spreekt";
  if (flags.modelGenerating) return "HADES antwoordt";
  if (flags.processing) return "Verwerkt spraak";
  if (flags.micActive) return "Luistert";
  return "Luistert";
}

/**
 * Conversation voice session state machine.
 * Separate flags: micActive, modelGenerating, audioPlaying.
 * Tab id stored in sessionStorage for exclusive session ownership.
 */
export function useVoiceSession(options: UseVoiceSessionOptions = {}): UseVoiceSessionResult {
  const clientTabId = useMemo(() => ensureClientTabId(VOICE_TAB_STORAGE_KEY), []);
  const [state, setState] = useState<VoiceSessionState>(() => createInitialVoiceSessionState(clientTabId));
  const [doctor, setDoctor] = useState<VoiceStatus | null>(null);
  const [voiceReady, setVoiceReady] = useState<boolean | null>(null);
  const [lastInterruptLatencyMs, setLastInterruptLatencyMs] = useState<number | null>(null);
  const [outputMuted, setOutputMutedState] = useState(false);

  const captureRef = useRef<AudioCapture | null>(null);
  const queueRef = useRef<PlaybackQueue | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const generationRef = useRef(1);
  const processingRef = useRef(false);
  const interruptedRef = useRef(false);
  const reconnectingRef = useRef(false);
  const mutedForPlaybackRef = useRef(false);
  const wakeArmedRef = useRef(true);
  const lastActivityRef = useRef(Date.now());
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const markActivity = useCallback(() => {
    lastActivityRef.current = Date.now();
  }, []);

  const turnMode: VoiceCaptureMode = options.mode === "push_to_talk" ? "push_to_talk" : "continuous";

  const patch = useCallback((partial: Partial<VoiceSessionState>) => {
    setState((prev) => ({ ...prev, ...partial }));
  }, []);

  const publishStatus = useCallback(
    (
      overrides: Partial<{
        micState: MicState;
        micActive: boolean;
        processing: boolean;
        modelGenerating: boolean;
        audioPlaying: boolean;
        interrupted: boolean;
        reconnecting: boolean;
        sessionActive: boolean;
        status: VoiceUiStatus;
      }> = {},
    ) => {
      if (overrides.processing != null) {
        processingRef.current = overrides.processing;
      }
      if (overrides.interrupted != null) {
        interruptedRef.current = overrides.interrupted;
      }
      if (overrides.reconnecting != null) {
        reconnectingRef.current = overrides.reconnecting;
      }
      setState((prev) => {
        const sessionActive = overrides.sessionActive ?? Boolean(prev.sessionId);
        const flags = {
          micState: overrides.micState ?? prev.micState,
          micActive: overrides.micActive ?? prev.micActive,
          processing: overrides.processing ?? processingRef.current,
          modelGenerating: overrides.modelGenerating ?? prev.modelGenerating,
          audioPlaying: overrides.audioPlaying ?? prev.audioPlaying,
          interrupted: overrides.interrupted ?? interruptedRef.current,
          reconnecting: overrides.reconnecting ?? reconnectingRef.current,
          sessionActive,
        };
        const status = overrides.status ?? deriveStatus(flags);
        optionsRef.current.onStatusChange?.(status);
        const next: VoiceSessionState = { ...prev, status };
        if (overrides.micState != null) next.micState = overrides.micState;
        if (overrides.micActive != null) next.micActive = overrides.micActive;
        if (overrides.modelGenerating != null) next.modelGenerating = overrides.modelGenerating;
        if (overrides.audioPlaying != null) next.audioPlaying = overrides.audioPlaying;
        return next;
      });
    },
    [],
  );

  useEffect(() => {
    queueRef.current = new PlaybackQueue({
      volume: options.volume ?? 1,
      outputDeviceId: options.outputDeviceId,
      onPlayingChange: (playing) => {
        patch({ audioPlaying: playing });
        publishStatus({ audioPlaying: playing, interrupted: false });
        // Avoid re-hearing own TTS through speakers: mute mic while playing when barge-in is off,
        // or temporarily ignore low-energy while still allowing strong barge-in.
        const capture = captureRef.current;
        if (!capture) return;
        if (playing) {
          if (optionsRef.current.bargeIn === false) {
            mutedForPlaybackRef.current = true;
            capture.setMuted(true);
          }
        } else if (mutedForPlaybackRef.current) {
          mutedForPlaybackRef.current = false;
          capture.setMuted(false);
        }
      },
      onInterrupt: (ms) => setLastInterruptLatencyMs(ms),
      onError: (message) => {
        patch({ lastError: message });
        optionsRef.current.onError?.(message);
      },
    });
    return () => {
      queueRef.current?.dispose();
      queueRef.current = null;
      void captureRef.current?.stop();
      captureRef.current = null;
    };
     
  }, []);

  useEffect(() => {
    if (options.volume != null) queueRef.current?.setVolume(options.volume);
  }, [options.volume]);

  useEffect(() => {
    void queueRef.current?.setOutputDevice(options.outputDeviceId ?? null);
  }, [options.outputDeviceId]);

  const refreshDoctor = useCallback(async () => {
    try {
      const report = await voiceApi.voiceDoctor();
      setDoctor(report);
      setVoiceReady(Boolean(report.ready));
      return report;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Voice-diagnose mislukt.";
      patch({ lastError: msg });
      setVoiceReady(false);
      return null;
    }
  }, [patch]);

  const installVoice = useCallback(
    async (steps?: string[]) => {
      const result = await voiceApi.voiceInstall(steps);
      await refreshDoctor();
      return result;
    },
    [refreshDoctor],
  );

  const handleUtterance = useCallback(
    async (blob: Blob, mimeType: string) => {
      const sessionId = sessionIdRef.current;
      if (!sessionId) return;
      publishStatus({ processing: true, interrupted: false });
      markActivity();
      try {
        const audio_base64 = await blobToBase64(blob);
        // Wake-word gate: when enabled and not armed, only accept "Hades" to arm.
        if (optionsRef.current.wakeWordEnabled && !wakeArmedRef.current) {
          const wake = await voiceApi.voiceWakeProbe({
            audio_base64,
            mime_type: mimeType || blob.type || "audio/webm",
            language: optionsRef.current.language || "nl",
          });
          if (!wake.detected) {
            return;
          }
          wakeArmedRef.current = true;
          const remainder = String(wake.remainder || "").trim();
          const wakeText = String(wake.text || "Hades");
          patch({ lastTranscript: remainder || wakeText, status: "Luistert" });
          publishStatus({ status: "Luistert" });
          if (!remainder) {
            return;
          }
          // Same utterance already contains a command after the wake word.
          await optionsRef.current.onUserUtterance?.(remainder, {
            turnId: `wake-${Date.now()}`,
            sessionId,
          });
          wakeArmedRef.current = false;
          return;
        }

        const result = await voiceApi.voiceTranscribe({
          audio_base64,
          mime_type: mimeType || blob.type || "audio/webm",
          language: optionsRef.current.language || "nl",
          session_id: sessionId,
          is_final: true,
        });
        const text = (result.text || "").trim();
        patch({ lastTranscript: text });
        if (result.silence || !text || result.should_send === false) {
          return;
        }
        // After a completed turn with wake-word on, return to wake listening.
        if (optionsRef.current.wakeWordEnabled) {
          wakeArmedRef.current = false;
        }
        await optionsRef.current.onUserUtterance?.(text, {
          turnId: result.turn_id,
          sessionId,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Spraakherkenning mislukt.";
        patch({ lastError: msg });
        optionsRef.current.onError?.(msg);
        if (msg.toLowerCase().includes("niet bereikbaar")) {
          publishStatus({ reconnecting: true });
        }
      } finally {
        publishStatus({ processing: false });
      }
    },
    [patch, publishStatus, markActivity],
  );

  const startMic = useCallback(async () => {
    const support = voiceMediaSupported();
    if (!support.ok) {
      const msg = support.reason || "Microfoon niet beschikbaar.";
      patch({ lastError: msg, micState: support.reason?.includes("beveiligde") ? "insecure" : "unsupported" });
      optionsRef.current.onError?.(msg);
      publishStatus({ micState: support.reason?.includes("beveiligde") ? "insecure" : "unsupported" });
      throw new Error(msg);
    }

    await captureRef.current?.stop();
    const mode: VoiceCaptureMode = optionsRef.current.mode === "push_to_talk" ? "push_to_talk" : "continuous";
    const capture = new AudioCapture({
      mode,
      deviceId: optionsRef.current.inputDeviceId,
      endSilenceMs: optionsRef.current.endSilenceMs,
      speechThreshold: optionsRef.current.speechThreshold,
      onLevel: (level) => patch({ level }),
      onStateChange: (micState) => {
        patch({ micState, micActive: micState === "active" || micState === "muted" });
        publishStatus({ micState, micActive: micState === "active" || micState === "muted" });
      },
      onError: (message) => {
        patch({ lastError: message });
        optionsRef.current.onError?.(message);
      },
      onSpeechStart: () => {
        const bargeIn = optionsRef.current.bargeIn !== false;
        if (!bargeIn) return;
        if (queueRef.current?.isPlaying() && sessionIdRef.current) {
          const ms = queueRef.current.stop("barge-in");
          setLastInterruptLatencyMs(ms);
          void voiceApi.voiceSessionInterrupt(sessionIdRef.current, "barge-in").catch(() => undefined);
          publishStatus({ audioPlaying: false, interrupted: true });
        }
      },
      onSpeechEnd: (blob, mime) => {
        void handleUtterance(blob, mime);
      },
    });
    captureRef.current = capture;
    patch({ status: "Microfoon toestaan", micState: "requesting" });
    await capture.requestPermissionAndStart(optionsRef.current.inputDeviceId);
    patch({ micActive: true });
    publishStatus({ micActive: true, micState: "active", sessionActive: true });
  }, [handleUtterance, patch, publishStatus]);

  const startSession = useCallback(
    async (opts?: { force?: boolean }) => {
      publishStatus({ interrupted: false, reconnecting: false });
      patch({ lastError: null, status: "Microfoon toestaan" });
      try {
        const started = await voiceApi.voiceSessionStart({
          conversation_id: optionsRef.current.conversationId || null,
          client_tab_id: clientTabId,
          keep_audio: optionsRef.current.keepAudio ?? false,
          force: Boolean(opts?.force),
          idle_timeout_seconds: optionsRef.current.idleTimeoutSeconds ?? 120,
        });
        sessionIdRef.current = started.session_id;
        generationRef.current = started.generation || 1;
        queueRef.current?.alignGeneration(generationRef.current);
        patch({
          sessionId: started.session_id,
          conversationId: started.conversation_id ?? optionsRef.current.conversationId ?? null,
          generation: generationRef.current,
          keepAudio: optionsRef.current.keepAudio ?? false,
        });
        // Never silently re-enable mic after reconnect — require this explicit startSession gesture.
        if (started.mic_must_reenable !== false) {
          await startMic();
        }
        wakeArmedRef.current = !optionsRef.current.wakeWordEnabled;
        patch({ status: optionsRef.current.wakeWordEnabled ? "Luistert" : "Luistert" });
        publishStatus({ sessionActive: true, micActive: true });
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Spraaksessie starten mislukt.";
        patch({ lastError: msg, status: "stopped", sessionId: null });
        optionsRef.current.onError?.(msg);
        sessionIdRef.current = null;
        await captureRef.current?.stop();
        captureRef.current = null;
      }
    },
    [clientTabId, patch, publishStatus, startMic],
  );

  const stopSession = useCallback(async () => {
    const sessionId = sessionIdRef.current;
    queueRef.current?.stop("stop");
    await captureRef.current?.stop();
    captureRef.current = null;
    if (sessionId) {
      try {
        await voiceApi.voiceSessionStop(sessionId, "user");
      } catch {
        // session may already be gone
      }
    }
    sessionIdRef.current = null;
    mutedForPlaybackRef.current = false;
    wakeArmedRef.current = true;
    publishStatus({
      processing: false,
      interrupted: false,
      reconnecting: false,
      micActive: false,
      modelGenerating: false,
      audioPlaying: false,
      sessionActive: false,
      status: "stopped",
    });
    patch({
      sessionId: null,
      micActive: false,
      modelGenerating: false,
      audioPlaying: false,
      level: 0,
      micState: "idle",
      status: "stopped",
    });
  }, [patch, publishStatus]);

  const interrupt = useCallback(async () => {
    const sessionId = sessionIdRef.current;
    const ms = queueRef.current?.stop("user") ?? null;
    setLastInterruptLatencyMs(ms);
    interruptedRef.current = true;
    markActivity();
    patch({ audioPlaying: false, modelGenerating: false, status: "Onderbroken" });
    if (sessionId) {
      try {
        await voiceApi.voiceSessionInterrupt(sessionId, "user");
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Onderbreken mislukt.";
        patch({ lastError: msg });
      }
    }
    publishStatus({ audioPlaying: false, modelGenerating: false, interrupted: true });
  }, [patch, publishStatus, markActivity]);

  const clearInterrupted = useCallback(() => {
    interruptedRef.current = false;
    publishStatus({ interrupted: false });
  }, [publishStatus]);

  const speakAssistantResponse = useCallback(
    async (text: string, responseId: string, opts?: { forceReplay?: boolean }) => {
      const sessionId = sessionIdRef.current;
      if (!sessionId || !text.trim()) return;
      // Do not speak a response that was interrupted while the model was still generating,
      // unless this is an explicit replay.
      if (interruptedRef.current && !opts?.forceReplay) {
        return;
      }
      interruptedRef.current = false;
      markActivity();
      publishStatus({ interrupted: false });
      patch({ modelGenerating: false, status: "Spreekt" });
      try {
        const result = await voiceApi.voiceSessionSpeakResponse({
          session_id: sessionId,
          response_id: responseId,
          text,
          force_replay: Boolean(opts?.forceReplay),
        });
        // If the user interrupted while TTS was being synthesized, drop playback.
        if (interruptedRef.current && !opts?.forceReplay) {
          queueRef.current?.stop("user");
          return;
        }
        const events = result.events || [];
        for (const raw of events) {
          if (interruptedRef.current && !opts?.forceReplay) {
            queueRef.current?.stop("user");
            break;
          }
          const event = raw as VoiceEvent;
          const payload = event.payload || {};
          const generation = Number(event.generation ?? payload.generation ?? generationRef.current);
          generationRef.current = Math.max(generationRef.current, generation);
          const queue = queueRef.current;
          if (!queue) continue;
          queue.alignGeneration(generation);
          const audio_base64 = String(payload.audio_base64 || "");
          if (!audio_base64) continue;
          queue.enqueueBase64({
            sessionId,
            turnId: String(event.turn_id || ""),
            responseId,
            order: Number(payload.order ?? 0),
            generation: queue.getGeneration(),
            mimeType: String(payload.mime_type || "audio/wav"),
            sampleRate: typeof payload.sample_rate === "number" ? payload.sample_rate : undefined,
            audioBase64: audio_base64,
            text: typeof payload.text === "string" ? payload.text : undefined,
          });
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Gesproken antwoord mislukt.";
        patch({ lastError: msg });
        optionsRef.current.onError?.(msg);
      }
    },
    [patch, publishStatus, markActivity],
  );

  const setModelGenerating = useCallback(
    (generating: boolean) => {
      patch({ modelGenerating: generating });
      if (generating) {
        publishStatus({ modelGenerating: true, interrupted: false });
      } else {
        publishStatus({ modelGenerating: false });
      }
    },
    [patch, publishStatus],
  );

  const setMicMuted = useCallback(
    (muted: boolean) => {
      captureRef.current?.setMuted(muted);
      patch({ micState: muted ? "muted" : captureRef.current ? "active" : "idle" });
    },
    [patch],
  );

  const setOutputMuted = useCallback((muted: boolean) => {
    setOutputMutedState(muted);
    queueRef.current?.setVolume(muted ? 0 : (optionsRef.current.volume ?? 1));
  }, []);

  const holdPushToTalk = useCallback((down: boolean) => {
    captureRef.current?.holdPushToTalk(down);
  }, []);

  useEffect(() => {
    void refreshDoctor();
  }, [refreshDoctor]);

  // Client-side idle watchdog (server also reaps); stops mic tracks after inactivity.
  useEffect(() => {
    const idleMs = Math.max(0, Number(options.idleTimeoutSeconds ?? 120) * 1000);
    if (!state.sessionId || idleMs <= 0) return undefined;
    markActivity();
    const timer = window.setInterval(() => {
      if (processingRef.current || queueRef.current?.isPlaying()) {
        markActivity();
        return;
      }
      if (Date.now() - lastActivityRef.current < idleMs) return;
      void stopSession();
      patch({ lastError: "Spraaksessie gestopt door inactiviteit." });
    }, Math.min(Math.max(5_000, Math.floor(idleMs / 4)), 30_000));
    return () => window.clearInterval(timer);
  }, [options.idleTimeoutSeconds, state.sessionId, stopSession, patch, markActivity]);

  // Re-sync conversation id into state when parent changes
  useEffect(() => {
    patch({ conversationId: options.conversationId ?? null });
  }, [options.conversationId, patch]);

  return {
    state,
    status: state.status,
    micActive: state.micActive,
    modelGenerating: state.modelGenerating,
    audioPlaying: state.audioPlaying,
    outputMuted,
    level: state.level,
    voiceReady,
    doctor,
    lastInterruptLatencyMs,
    turnMode,
    interrupted: interruptedRef.current,
    startSession,
    stopSession,
    interrupt,
    setMicMuted,
    setOutputMuted,
    holdPushToTalk,
    speakAssistantResponse,
    setModelGenerating,
    refreshDoctor,
    installVoice,
    clearInterrupted,
  };
}
