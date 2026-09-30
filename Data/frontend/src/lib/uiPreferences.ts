/** UI preference helpers for Settings Control Plane → browser surface. */

const PREFS_CACHE_KEY = "lv.ui.preferences.v1";

export type UiPrefsCache = {
  app_display_name: string;
  timezone: string;
  locale: string;
  theme: string;
  auto_refresh_seconds: number;
  sound_notifications: boolean;
  desktop_notifications: boolean;
  prefer_local_data: boolean;
  optional_diagnostics_share: boolean;
  crash_reports_enabled: boolean;
};

const DEFAULTS: UiPrefsCache = {
  app_display_name: "Leviathan AI Control Center",
  timezone: "Europe/Amsterdam",
  locale: "nl",
  theme: "dark_leviathan",
  auto_refresh_seconds: 30,
  sound_notifications: true,
  desktop_notifications: true,
  prefer_local_data: true,
  optional_diagnostics_share: false,
  crash_reports_enabled: true,
};

export function readUiPrefsCache(): UiPrefsCache {
  if (typeof window === "undefined") return { ...DEFAULTS };
  try {
    const raw = window.localStorage.getItem(PREFS_CACHE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw) as Partial<UiPrefsCache>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

export function writeUiPrefsCache(next: Partial<UiPrefsCache>): UiPrefsCache {
  const merged = { ...readUiPrefsCache(), ...next };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(PREFS_CACHE_KEY, JSON.stringify(merged));
  }
  applyUiPreferences(merged);
  return merged;
}

export function applyUiPreferences(prefs: UiPrefsCache): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = prefs.theme || "dark_leviathan";
  root.dataset.locale = prefs.locale || "nl";
  root.lang = prefs.locale === "en" ? "en" : "nl";
  if (prefs.app_display_name) {
    document.title = prefs.app_display_name;
  }
}

export function formatTimezoneLabel(tz: string, now = new Date()): string {
  try {
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      timeZoneName: "shortOffset",
    });
    const parts = fmt.formatToParts(now);
    const offset = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    return offset ? `${tz} (${offset})` : tz;
  } catch {
    return tz;
  }
}

export function formatClockInTimezone(
  date: Date,
  timezone: string,
  locale: string,
): { dateLine: string; timeLine: string } {
  const loc = locale === "en" ? "en-GB" : "nl-NL";
  try {
    const dateFmt = new Intl.DateTimeFormat(loc, {
      timeZone: timezone,
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    });
    const timeFmt = new Intl.DateTimeFormat(loc, {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    return { dateLine: dateFmt.format(date), timeLine: timeFmt.format(date) };
  } catch {
    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    const ss = String(date.getSeconds()).padStart(2, "0");
    return { dateLine: date.toDateString(), timeLine: `${hh}:${mm}:${ss}` };
  }
}

export type DesktopNotificationCapability = {
  supported: boolean;
  permission: NotificationPermission | "unsupported";
  configuredEnabled: boolean;
};

export function desktopNotificationCapability(configuredEnabled: boolean): DesktopNotificationCapability {
  if (typeof window === "undefined" || typeof Notification === "undefined") {
    return { supported: false, permission: "unsupported", configuredEnabled };
  }
  return {
    supported: true,
    permission: Notification.permission,
    configuredEnabled,
  };
}

export async function ensureDesktopNotificationPermission(): Promise<NotificationPermission | "unsupported"> {
  if (typeof window === "undefined" || typeof Notification === "undefined") return "unsupported";
  if (Notification.permission === "granted" || Notification.permission === "denied") {
    return Notification.permission;
  }
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

/** Short, non-overlapping toast cue respecting sound preference. */
let lastSoundAt = 0;
export function playToastSoundIfEnabled(): void {
  const prefs = readUiPrefsCache();
  if (!prefs.sound_notifications) return;
  if (typeof window === "undefined") return;
  const now = Date.now();
  if (now - lastSoundAt < 400) return;
  lastSoundAt = now;
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.value = 0.04;
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.12);
    osc.stop(ctx.currentTime + 0.13);
    window.setTimeout(() => void ctx.close(), 200);
  } catch {
    /* audio blocked — silent */
  }
}

export const COMMON_TIMEZONES = [
  "Europe/Amsterdam",
  "Europe/Brussels",
  "Europe/London",
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Tokyo",
] as const;

export const UI_SETTING_KEYS = [
  "ui.app_display_name",
  "ui.timezone",
  "ui.locale",
  "ui.theme",
  "ui.auto_refresh_seconds",
  "ui.sound_notifications",
  "ui.desktop_notifications",
  "ui.start_with_system",
  "ui.prefer_local_data",
  "ui.optional_diagnostics_share",
  "ui.crash_reports_enabled",
] as const;

/** Curated system panel keys (canonical catalog owners — not duplicated). */
export const SYSTEM_PANEL_KEYS = [
  "managed_serving.gpu_memory_limit_pct",
  "context.token_budget",
  "resources.max_model_concurrency",
  "model.timeout_seconds",
] as const;
