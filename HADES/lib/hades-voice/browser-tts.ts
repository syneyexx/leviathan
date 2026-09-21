/**
 * Optional browser speechSynthesis fallback.
 * Reports "offline" only when available voices are local/native (localService).
 */

import type { BrowserTtsOptions, BrowserTtsVoice } from "./types";

function synth(): SpeechSynthesis | null {
  if (typeof window === "undefined") return null;
  return window.speechSynthesis ?? null;
}

export function browserTtsSupported(): boolean {
  return Boolean(synth());
}

export function listBrowserVoices(): BrowserTtsVoice[] {
  const s = synth();
  if (!s) return [];
  return s.getVoices().map((v) => ({
    voiceURI: v.voiceURI,
    name: v.name,
    lang: v.lang,
    localService: Boolean(v.localService),
    default: Boolean(v.default),
  }));
}

/** Wait briefly for voiceschanged (Chromium often loads voices async). */
export function loadBrowserVoices(timeoutMs = 1500): Promise<BrowserTtsVoice[]> {
  const s = synth();
  if (!s) return Promise.resolve([]);
  const existing = listBrowserVoices();
  if (existing.length) return Promise.resolve(existing);

  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      s.removeEventListener("voiceschanged", onChange);
      resolve(listBrowserVoices());
    };
    const onChange = () => finish();
    s.addEventListener("voiceschanged", onChange);
    window.setTimeout(finish, timeoutMs);
  });
}

/**
 * Offline capability: true only when at least one voice is marked localService
 * (native/OS voice). Network-backed cloud voices do not count as offline.
 */
export function browserTtsOfflineCapable(voices?: BrowserTtsVoice[]): boolean {
  const list = voices ?? listBrowserVoices();
  return list.some((v) => v.localService);
}

export function pickBrowserVoice(
  voices: BrowserTtsVoice[],
  opts: { lang?: string; preferLocal?: boolean; voiceURI?: string | null } = {},
): BrowserTtsVoice | null {
  if (!voices.length) return null;
  if (opts.voiceURI) {
    const exact = voices.find((v) => v.voiceURI === opts.voiceURI);
    if (exact) return exact;
  }
  const lang = (opts.lang || "nl").toLowerCase();
  const preferLocal = opts.preferLocal !== false;
  const scored = [...voices].sort((a, b) => {
    const score = (v: BrowserTtsVoice) => {
      let s = 0;
      if (preferLocal && v.localService) s += 8;
      const vl = v.lang.toLowerCase();
      if (vl === lang || vl.startsWith(lang)) s += 4;
      if (lang.startsWith("nl") && (vl.startsWith("nl") || vl.includes("neder"))) s += 2;
      if (v.default) s += 1;
      return s;
    };
    return score(b) - score(a);
  });
  return scored[0] || null;
}

export type BrowserTtsHandle = {
  stop: () => void;
  done: Promise<void>;
};

export class BrowserTts {
  private utterance: SpeechSynthesisUtterance | null = null;

  async speak(text: string, options: BrowserTtsOptions = {}): Promise<BrowserTtsHandle> {
    const s = synth();
    if (!s) {
      return {
        stop: () => undefined,
        done: Promise.reject(new Error("Browser-spraak (speechSynthesis) is niet beschikbaar.")),
      };
    }

    const trimmed = text.trim();
    if (!trimmed) {
      return { stop: () => undefined, done: Promise.resolve() };
    }

    this.stop();
    const voices = await loadBrowserVoices();
    const offline = browserTtsOfflineCapable(voices);
    const preferLocal = offline;
    const picked = pickBrowserVoice(voices, {
      lang: options.lang || "nl-NL",
      preferLocal,
      voiceURI: options.voiceURI,
    });

    // If we only have remote voices, still speak but callers can check offlineCapable.
    const utter = new SpeechSynthesisUtterance(trimmed);
    utter.lang = options.lang || picked?.lang || "nl-NL";
    utter.rate = options.rate ?? 1;
    utter.pitch = options.pitch ?? 1;
    utter.volume = options.volume ?? 1;
    if (picked) {
      const match = s.getVoices().find((v) => v.voiceURI === picked.voiceURI);
      if (match) utter.voice = match;
    }

    this.utterance = utter;

    const done = new Promise<void>((resolve, reject) => {
      utter.onend = () => {
        if (this.utterance === utter) this.utterance = null;
        resolve();
      };
      utter.onerror = (event) => {
        if (this.utterance === utter) this.utterance = null;
        if (event.error === "canceled" || event.error === "interrupted") resolve();
        else reject(new Error(`Browser-spraakfout: ${event.error || "onbekend"}`));
      };
      try {
        s.cancel();
        s.speak(utter);
      } catch (err) {
        reject(err instanceof Error ? err : new Error("speechSynthesis.speak mislukt."));
      }
    });

    return {
      stop: () => this.stop(),
      done,
    };
  }

  stop(): void {
    const s = synth();
    try {
      s?.cancel();
    } catch {
      // ignore
    }
    this.utterance = null;
  }

  /** Status helper for UI / doctor. */
  async status(): Promise<{
    supported: boolean;
    offline: boolean;
    voices: BrowserTtsVoice[];
    message: string;
  }> {
    const supported = browserTtsSupported();
    if (!supported) {
      return {
        supported: false,
        offline: false,
        voices: [],
        message: "Browser-spraak niet beschikbaar.",
      };
    }
    const voices = await loadBrowserVoices();
    const offline = browserTtsOfflineCapable(voices);
    return {
      supported: true,
      offline,
      voices,
      message: offline
        ? "Lokale/native browserstemmen beschikbaar (offline)."
        : voices.length
          ? "Alleen netwerk-/cloudstemmen — niet als offline beschouwen."
          : "Geen browserstemmen geladen.",
    };
  }
}

export const browserTts = new BrowserTts();
