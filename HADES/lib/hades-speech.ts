/** Client-side VoiceStudio/HADES speech playback with barge-in + echo guard. */

import { hadesApi, type SpeechChunkAudio, type SpeechEchoGuard } from "@/lib/hades-api";

function decodeBase64Audio(chunk: SpeechChunkAudio): string {
  const binary = atob(chunk.audio_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const blob = new Blob([bytes], { type: chunk.mime_type || "audio/wav" });
  return URL.createObjectURL(blob);
}

export type SpeechPlayerState = {
  speaking: boolean;
  generationId: string | null;
  messageId: string | null;
  error: string | null;
};

type Listener = (state: SpeechPlayerState) => void;

class HadesSpeechPlayer {
  private audio: HTMLAudioElement | null = null;
  private objectUrl: string | null = null;
  private generationId: string | null = null;
  private messageId: string | null = null;
  private speaking = false;
  private error: string | null = null;
  private listeners = new Set<Listener>();
  private queueToken = 0;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => {
      this.listeners.delete(listener);
    };
  }

  snapshot(): SpeechPlayerState {
    return {
      speaking: this.speaking,
      generationId: this.generationId,
      messageId: this.messageId,
      error: this.error,
    };
  }

  private emit() {
    const snap = this.snapshot();
    this.listeners.forEach((listener) => listener(snap));
  }

  private clearAudio() {
    if (this.audio) {
      this.audio.onended = null;
      this.audio.onerror = null;
      this.audio.pause();
      this.audio.src = "";
      this.audio = null;
    }
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
  }

  async stop(): Promise<void> {
    this.queueToken += 1;
    const generationId = this.generationId;
    this.clearAudio();
    this.speaking = false;
    this.messageId = null;
    this.generationId = null;
    this.emit();
    try {
      await hadesApi.speechStop({ generation_id: generationId });
      await hadesApi.speechPlayback({ active: false });
    } catch {
      // Stop must be best-effort; chat continues without speech.
    }
  }

  private async playChunk(chunk: SpeechChunkAudio, messageId: string | null, token: number): Promise<void> {
    if (token !== this.queueToken) return;
    if (!chunk.audio_base64) return;
    this.clearAudio();
    this.objectUrl = decodeBase64Audio(chunk);
    this.audio = new Audio(this.objectUrl);
    this.speaking = true;
    this.messageId = messageId;
    this.generationId = chunk.generation_id;
    this.error = null;
    this.emit();
    await hadesApi.speechPlayback({ active: true }).catch(() => undefined);

    await new Promise<void>((resolve, reject) => {
      if (!this.audio) {
        resolve();
        return;
      }
      this.audio.onended = () => resolve();
      this.audio.onerror = () => reject(new Error("Audio-afspelen mislukt."));
      void this.audio.play().catch(reject);
    });
  }

  async speakText(text: string, messageId?: string | null): Promise<void> {
    await this.stop();
    const token = this.queueToken;
    this.error = null;
    this.messageId = messageId ?? null;
    this.emit();
    try {
      const plan = await hadesApi.speechSpeak({ text, message_id: messageId || undefined });
      if (token !== this.queueToken) return;
      this.generationId = plan.generation_id;
      this.speaking = true;
      this.emit();
      for (const item of plan.chunks) {
        if (token !== this.queueToken) return;
        const chunk = await hadesApi.speechChunk({
          text: item.text,
          generation_id: plan.generation_id,
          chunk_index: item.index,
        });
        if (token !== this.queueToken) return;
        await this.playChunk(chunk, messageId ?? null, token);
      }
    } catch (reason) {
      if (token !== this.queueToken) return;
      this.error = reason instanceof Error ? reason.message : "Voorlezen mislukt.";
      throw reason;
    } finally {
      if (token === this.queueToken) {
        this.speaking = false;
        this.messageId = null;
        this.emit();
        await hadesApi.speechPlayback({ active: false }).catch(() => undefined);
      }
    }
  }

  async preview(): Promise<void> {
    await this.stop();
    const token = this.queueToken;
    try {
      const chunk = await hadesApi.speechPreview();
      if (token !== this.queueToken) return;
      this.generationId = chunk.generation_id;
      await this.playChunk(chunk, null, token);
    } finally {
      if (token === this.queueToken) {
        const finishedId = this.generationId;
        this.speaking = false;
        this.emit();
        await hadesApi.speechPlayback({ active: false }).catch(() => undefined);
        await hadesApi.speechStop({ generation_id: finishedId }).catch(() => undefined);
      }
    }
  }

  async ensureMicAllowed(): Promise<SpeechEchoGuard> {
    const guard = await hadesApi.speechEchoGuard();
    if (guard.blocked) {
      throw new Error(guard.note || "Microfoon geblokkeerd tijdens TTS-afspelen (echo-guard).");
    }
    return guard;
  }
}

export const hadesSpeechPlayer = new HadesSpeechPlayer();
