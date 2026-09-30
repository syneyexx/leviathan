/**
 * Media Control helpers — classify jobs/capabilities into overview media kinds.
 * No fabricated inventory; missing fields stay explicit.
 */

export type MediaKind = "image" | "video" | "audio" | "document";

export const MEDIA_KIND_LABEL: Record<MediaKind, string> = {
  image: "Afbeelding",
  video: "Video",
  audio: "Audio",
  document: "Document",
};

const IMAGE_CAPS = new Set([
  "media.image_generate",
  "media.image_edit",
  "media.image.batch",
]);

const VIDEO_CAPS = new Set([
  "media.video_ingest",
  "media.video.process",
  "media.transcode",
  "media.thumbnail",
]);

const AUDIO_CAPS = new Set(["media.audio.process"]);

const DOC_CAPS = new Set([
  "media.probe",
  "media.convert",
  "media.vision_inspect",
  "media.cross_modal_search",
]);

export function isMediaCapability(capabilityId: string | null | undefined): boolean {
  if (!capabilityId) return false;
  const id = capabilityId.toLowerCase();
  return id.startsWith("media.") || id.startsWith("media/");
}

export function classifyMediaCapability(capabilityId: string | null | undefined): MediaKind | null {
  if (!capabilityId) return null;
  const id = capabilityId.toLowerCase();
  if (IMAGE_CAPS.has(id) || id.includes("image")) return "image";
  if (VIDEO_CAPS.has(id) || id.includes("video")) return "video";
  if (AUDIO_CAPS.has(id) || id.includes("audio")) return "audio";
  if (DOC_CAPS.has(id) || id.includes("document") || id.includes("probe") || id.includes("convert")) {
    return "document";
  }
  if (isMediaCapability(id)) return "document";
  return null;
}

export function classifyByFilename(name: string | null | undefined): MediaKind | null {
  if (!name) return null;
  const lower = name.toLowerCase();
  if (/\.(png|jpe?g|gif|webp|bmp|svg|avif)$/.test(lower)) return "image";
  if (/\.(mp4|mov|mkv|webm|avi|m4v)$/.test(lower)) return "video";
  if (/\.(mp3|wav|flac|aac|ogg|m4a)$/.test(lower)) return "audio";
  if (/\.(pdf|docx?|txt|md|csv|json)$/.test(lower)) return "document";
  return null;
}

export function mediaKindFromJob(job: {
  capabilityId?: string | null;
  capability_id?: string | null;
  path?: string | null;
  human_title?: string | null;
  title?: string | null;
}): MediaKind | null {
  const cap = job.capabilityId ?? job.capability_id ?? null;
  const byCap = classifyMediaCapability(typeof cap === "string" ? cap : null);
  if (byCap) return byCap;
  const name =
    (typeof job.path === "string" && job.path) ||
    (typeof job.human_title === "string" && job.human_title) ||
    (typeof job.title === "string" && job.title) ||
    null;
  return classifyByFilename(name);
}

export function formatRelativeNl(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const deltaMs = Math.max(0, now - t);
  const mins = Math.floor(deltaMs / 60_000);
  if (mins < 1) return "zojuist";
  if (mins < 60) return `${mins} min geleden`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} uur geleden`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "1 dag geleden";
  return `${days} dagen geleden`;
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export type TypesRange = "24h" | "7d" | "30d" | "90d";

export function rangeToMs(range: TypesRange): number {
  switch (range) {
    case "24h":
      return 24 * 60 * 60 * 1000;
    case "7d":
      return 7 * 24 * 60 * 60 * 1000;
    case "30d":
      return 30 * 24 * 60 * 60 * 1000;
    case "90d":
      return 90 * 24 * 60 * 60 * 1000;
    default:
      return 7 * 24 * 60 * 60 * 1000;
  }
}

export function dutchDayLabel(date: Date): string {
  const months = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"] as const;
  return `${date.getDate()} ${months[date.getMonth()] ?? ""}`;
}
