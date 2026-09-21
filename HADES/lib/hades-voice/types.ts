/** Shared types for HADES local voice mode (frontend). */

export type VoiceUiStatus =
  | "idle"
  | "stopped"
  | "Microfoon toestaan"
  | "Luistert"
  | "Verwerkt spraak"
  | "HADES antwoordt"
  | "Spreekt"
  | "Onderbroken"
  | "Verbinding herstellen";

export type MicState =
  | "idle"
  | "requesting"
  | "active"
  | "muted"
  | "denied"
  | "unsupported"
  | "insecure"
  | "error";

export type VoiceTurnMode = "push_to_talk" | "continuous" | "manual";

export type VoiceCaptureMode = "push_to_talk" | "continuous";

export type VoiceEventType =
  | "session_started"
  | "speech_started"
  | "transcript_partial"
  | "transcript_final"
  | "response_started"
  | "speech_segment_ready"
  | "playback_started"
  | "interrupted"
  | "session_stopped"
  | "status"
  | "error"
  | "metrics"
  | "wake_detected";

export type VoiceSessionState = {
  sessionId: string | null;
  conversationId: string | null;
  clientTabId: string;
  status: VoiceUiStatus;
  generation: number;
  micActive: boolean;
  modelGenerating: boolean;
  audioPlaying: boolean;
  micState: MicState;
  level: number;
  lastTranscript: string;
  lastError: string | null;
  keepAudio: boolean;
};

export type VoiceEvent = {
  event_id?: string;
  type: VoiceEventType | string;
  session_id?: string;
  sequence?: number;
  turn_id?: string | null;
  response_id?: string | null;
  generation?: number;
  timestamp?: number;
  payload?: Record<string, unknown>;
};

export type VoiceDoctorCheck = {
  id: string;
  ok: boolean;
  detail?: string;
  recovery?: string;
};

export type VoiceStatus = {
  ready: boolean;
  checks: VoiceDoctorCheck[];
  providers?: Record<string, unknown>;
  audio_formats?: Record<string, unknown>;
  data_dir?: string;
  requirements_file?: string;
  installable_voices?: string[];
  settings?: {
    voice_enabled?: boolean;
    voice_asr_provider?: string;
    voice_tts_provider?: string;
    voice_language?: string;
    voice_spoken_answers_default?: boolean;
    voice_wake_word_enabled?: boolean;
    voice_turn_mode?: string;
  };
};

export type VoiceTranscribeResult = {
  turn_id: string;
  text: string;
  is_partial?: boolean;
  is_final?: boolean;
  silence?: boolean;
  language?: string | null;
  confidence?: number | null;
  provider?: string;
  model?: string;
  duration_seconds?: number;
  elapsed_ms?: number;
  metadata?: Record<string, unknown>;
  should_send?: boolean;
  accepted?: boolean;
  deduped?: boolean;
};

export type VoiceSpeakableResult = {
  speakable_text: string;
  segments: string[];
  style: "compact" | "full";
  language: string;
  speakable_contract?: Record<string, unknown>;
};

export type VoiceVoiceInfo = {
  id: string;
  name?: string;
  language?: string;
  gender?: string;
  local?: boolean;
  [key: string]: unknown;
};

export type VoiceSessionStartResult = {
  session_id: string;
  conversation_id?: string | null;
  client_tab_id: string;
  status: string;
  generation: number;
  mic_must_reenable?: boolean;
};

export type VoiceAudioSegment = {
  sessionId: string;
  turnId: string;
  responseId: string;
  order: number;
  generation: number;
  mimeType: string;
  sampleRate?: number;
  blob: Blob;
  text?: string;
};

export type AudioDeviceInfo = {
  deviceId: string;
  label: string;
  kind: MediaDeviceKind;
};

export type AudioCaptureOptions = {
  deviceId?: string | null;
  mode?: VoiceCaptureMode;
  /** Pre-roll buffer before speech start (ms). Default ~180. */
  preRollMs?: number;
  /** End-of-utterance silence before finalizing (ms). */
  endSilenceMs?: number;
  /** RMS threshold (0–1) to count as speech. */
  speechThreshold?: number;
  /** MediaRecorder timeslice (ms). */
  timesliceMs?: number;
  echoCancellation?: boolean;
  noiseSuppression?: boolean;
  autoGainControl?: boolean;
  mimeType?: string;
  onLevel?: (rms: number) => void;
  onSpeechStart?: () => void;
  onSpeechEnd?: (blob: Blob, mimeType: string) => void;
  onChunk?: (blob: Blob, mimeType: string, isFinal: boolean) => void;
  onError?: (message: string) => void;
  onDeviceChange?: (devices: AudioDeviceInfo[]) => void;
  onStateChange?: (state: MicState) => void;
  /** Test/injection hook — defaults to navigator.mediaDevices.getUserMedia. */
  getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
};

export type PlaybackQueueOptions = {
  volume?: number;
  outputDeviceId?: string | null;
  onPlayingChange?: (playing: boolean) => void;
  onSegmentStart?: (segment: VoiceAudioSegment) => void;
  onSegmentEnd?: (segment: VoiceAudioSegment) => void;
  onInterrupt?: (latencyMs: number | null) => void;
  onError?: (message: string) => void;
};

export type BrowserTtsOptions = {
  lang?: string;
  rate?: number;
  pitch?: number;
  volume?: number;
  voiceURI?: string | null;
};

export type BrowserTtsVoice = {
  voiceURI: string;
  name: string;
  lang: string;
  localService: boolean;
  default: boolean;
};

export const VOICE_TAB_STORAGE_KEY = "hades.voice.client_tab_id";
export const VOICE_SETUP_DONE_KEY = "hades.voice.setup_done";
export const VOICE_SPOKEN_ANSWERS_KEY = "hades.voice.spoken_answers";

export function createInitialVoiceSessionState(clientTabId: string): VoiceSessionState {
  return {
    sessionId: null,
    conversationId: null,
    clientTabId,
    status: "idle",
    generation: 1,
    micActive: false,
    modelGenerating: false,
    audioPlaying: false,
    micState: "idle",
    level: 0,
    lastTranscript: "",
    lastError: null,
    keepAudio: false,
  };
}
