import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { SidebarStatusRow } from "../components/layout/AppSidebarV2";
import {
  clampPct,
  formatBytes,
  formatDuration,
  formatPct,
  type BadgeTone,
} from "../lib/dashboardNormalize";
import { MEDIA_CONNECTED, MEDIA_STATUS_LABEL } from "../lib/mediaConnection";
import {
  classifyMediaCapability,
  dutchDayLabel,
  formatClock,
  formatRelativeNl,
  isMediaCapability,
  mediaKindFromJob,
  MEDIA_KIND_LABEL,
  rangeToMs,
  type MediaKind,
  type TypesRange,
} from "../lib/mediaClassify";
import type {
  CapabilityListItem,
  JobRecord,
  ModelHardwareInventory,
  SystemTelemetryResponse,
  TaskEvent,
  WorkerFabricDashboard,
  WorkerFabricJobSummary,
} from "../types/api";
import { useSystemTelemetry } from "./useSystemTelemetry";

const POLL_MS = 8_000;

export type MediaOverview = ReturnType<typeof useMediaOverview>;

export type MediaKpi = {
  id: string;
  label: string;
  value: string;
  sublabel: string;
  kind: MediaKind | "total";
  available: boolean;
  barHeights: number[];
};

export type MediaStorageSlice = {
  kind: MediaKind;
  label: string;
  bytes: number | null;
  pct: number | null;
  available: boolean;
};

export type MediaRecentItem = {
  id: string;
  name: string;
  kind: MediaKind;
  relative: string;
  durationLabel?: string;
  thumb?: string | null;
  to: string;
};

export type MediaGenerationJob = {
  id: string;
  title: string;
  kind: MediaKind;
  progress: number | null;
  progressLabel: string;
  timeLabel: string;
  tone: "running" | "done" | "queued" | "failed";
};

export type MediaTypesDay = {
  key: string;
  label: string;
  counts: Record<MediaKind, number>;
};

export type MediaToolCard = {
  id: string;
  title: string;
  subtitle: string;
  to: string;
  available: boolean;
};

export type MediaPlatformRow = {
  id: string;
  name: string;
  to: string;
  connected: boolean;
  statusLabel: string;
  countLabel: string;
  spark: number[];
};

export type MediaActivityRow = {
  id: string;
  time: string;
  description: string;
  kind: MediaKind | "system";
  tone: BadgeTone;
};

function reasonMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function jobCap(job: JobRecord | WorkerFabricJobSummary): string | null {
  if ("capability_id" in job && typeof job.capability_id === "string") return job.capability_id;
  if ("capabilityId" in job && typeof job.capabilityId === "string") return job.capabilityId;
  return null;
}

function jobIdOf(job: JobRecord | WorkerFabricJobSummary): string {
  if ("job_id" in job && typeof job.job_id === "string") return job.job_id;
  if ("jobId" in job && typeof job.jobId === "string") return job.jobId;
  if ("id" in job && typeof job.id === "string") return job.id;
  return cryptoRandomId();
}

function cryptoRandomId(): string {
  return `media-${Math.random().toString(36).slice(2, 10)}`;
}

function jobTitle(job: JobRecord | WorkerFabricJobSummary): string {
  if ("human_title" in job && typeof job.human_title === "string" && job.human_title) {
    return job.human_title;
  }
  const path = typeof (job as JobRecord).path === "string" ? String((job as JobRecord).path) : null;
  if (path) {
    const base = path.split(/[/\\]/).pop();
    if (base) return base;
  }
  const cap = jobCap(job);
  if (cap) return cap.replace(/^media\./, "").replace(/[._]/g, " ");
  return "Media job";
}

function jobState(job: JobRecord | WorkerFabricJobSummary): string {
  if ("state" in job && typeof job.state === "string") return job.state.toUpperCase();
  if ("status" in job && typeof job.status === "string") return String(job.status).toUpperCase();
  return "";
}

function jobProgress(job: JobRecord | WorkerFabricJobSummary): number | null {
  if ("progress_percent" in job) return clampPct(job.progress_percent as number | null);
  if ("progress" in job && typeof job.progress === "number") return clampPct(job.progress);
  return null;
}

function isActiveState(state: string): boolean {
  return /RUNNING|QUEUED|ACCEPTED|PENDING|STARTED|BUSY|PROCESSING/.test(state);
}

function isDoneState(state: string): boolean {
  return /COMPLETED|SUCCEEDED|SUCCESS|DONE/.test(state);
}

function isFailedState(state: string): boolean {
  return /FAILED|REJECTED|CANCELLED|ERROR|UNSUPPORTED/.test(state);
}

function emptyCounts(): Record<MediaKind, number> {
  return { image: 0, video: 0, audio: 0, document: 0 };
}

function decorativeBars(seed: number, active: boolean): number[] {
  if (!active) return [18, 18, 20, 18, 18, 20, 18, 18];
  const base = [30, 48, 38, 62, 45, 70, 52, 68];
  return base.map((h, i) => Math.max(16, Math.min(95, h + ((seed + i * 7) % 17) - 8)));
}

function tempFromHardware(
  hardware: ModelHardwareInventory | null,
  index: number,
  name: string,
): number | null {
  const devices = hardware?.devices ?? null;
  if (!Array.isArray(devices)) return null;
  const match =
    devices.find((d) => Number(d.ordinal) === index) ||
    devices.find((d) => String(d.name || "").includes(name));
  const temp = match?.temperatureC;
  return typeof temp === "number" && Number.isFinite(temp) ? temp : null;
}

function capabilitySubtitle(cap: CapabilityListItem | undefined, fallback: string): string {
  if (!cap) return fallback;
  const provider =
    (typeof cap.provider_ref === "string" && cap.provider_ref) ||
    (typeof cap.provider_kind === "string" && cap.provider_kind) ||
    null;
  if (provider) return provider;
  if (cap.available === false) {
    return cap.availability_reason || cap.unavailable_reason || "Niet geconfigureerd";
  }
  return fallback;
}

/**
 * Media Control → Overzicht data projection.
 * Live sources only: /api/media/status, workers, jobs, telemetry, capabilities, tasks.
 */
export function useMediaOverview(opts?: { enabled?: boolean }) {
  const enabled = opts?.enabled ?? true;
  const telemetryHook = useSystemTelemetry({ enabled, intervalMs: 4000 });
  const telemetry = telemetryHook.sample;

  const [mediaStatus, setMediaStatus] = useState<Record<string, unknown> | null>(null);
  const [workersDash, setWorkersDash] = useState<WorkerFabricDashboard | null>(null);
  const [jobs, setJobs] = useState<JobRecord[] | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityListItem[] | null>(null);
  const [activity, setActivity] = useState<TaskEvent[] | null>(null);
  const [hardware, setHardware] = useState<ModelHardwareInventory | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [selectedGpuIndex, setSelectedGpuIndex] = useState(0);
  const [typesRange, setTypesRange] = useState<TypesRange>("7d");
  const [perfRange, setPerfRange] = useState<"24h" | "7d" | "30d">("24h");

  const mounted = useRef(true);
  const inFlight = useRef(false);
  const generation = useRef(0);

  const mergeErrors = useCallback((patch: Partial<Record<string, string | undefined>>) => {
    setErrors((prev) => {
      const next = { ...prev };
      for (const [key, value] of Object.entries(patch)) {
        if (value == null) delete next[key];
        else next[key] = value;
      }
      return next;
    });
  }, []);

  const pull = useCallback(async (opts?: { silent?: boolean }) => {
    if (inFlight.current && opts?.silent) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden" && opts?.silent) {
      return;
    }
    inFlight.current = true;
    const gen = ++generation.current;
    if (!opts?.silent) {
      if (jobs == null) setLoading(true);
      else setRefreshing(true);
    }
    try {
      const settled = await Promise.allSettled([
        api.mediaStatus(),
        api.getWorkersDashboard(),
        api.listJobs(),
        api.listCapabilities({ q: "media", limit: 80 }),
        api.taskActivity({ limit: 24 }),
        api.modelsHardware(),
      ]);
      if (!mounted.current || gen !== generation.current) return;

      const [statusRes, workersRes, jobsRes, capsRes, actRes, hwRes] = settled;
      const errPatch: Partial<Record<string, string | undefined>> = {};

      if (statusRes.status === "fulfilled") {
        setMediaStatus(statusRes.value);
        errPatch.mediaStatus = undefined;
      } else {
        errPatch.mediaStatus = reasonMessage(statusRes.reason, "Media status unavailable");
      }

      if (workersRes.status === "fulfilled") {
        setWorkersDash(workersRes.value);
        errPatch.workers = undefined;
      } else {
        errPatch.workers = reasonMessage(workersRes.reason, "Workers unavailable");
      }

      if (jobsRes.status === "fulfilled") {
        setJobs(jobsRes.value.jobs ?? []);
        errPatch.jobs = undefined;
      } else {
        errPatch.jobs = reasonMessage(jobsRes.reason, "Jobs unavailable");
      }

      if (capsRes.status === "fulfilled") {
        setCapabilities(capsRes.value.capabilities ?? []);
        errPatch.capabilities = undefined;
      } else {
        errPatch.capabilities = reasonMessage(capsRes.reason, "Capabilities unavailable");
      }

      if (actRes.status === "fulfilled") {
        setActivity(actRes.value.activity ?? []);
        errPatch.activity = undefined;
      } else {
        errPatch.activity = reasonMessage(actRes.reason, "Activity unavailable");
      }

      if (hwRes.status === "fulfilled") {
        setHardware(hwRes.value.hardware);
        errPatch.hardware = undefined;
      } else {
        errPatch.hardware = reasonMessage(hwRes.reason, "Hardware unavailable");
      }

      mergeErrors(errPatch);
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [jobs, mergeErrors]);

  const refresh = useCallback(async () => {
    await Promise.all([telemetryHook.refresh(), pull()]);
  }, [pull, telemetryHook]);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) return;
    void pull();
    const id = window.setInterval(() => {
      void pull({ silent: true });
    }, POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") void pull({ silent: true });
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      mounted.current = false;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [enabled, pull]);

  useEffect(() => {
    if (telemetryHook.error) mergeErrors({ telemetry: telemetryHook.error });
    else mergeErrors({ telemetry: undefined });
  }, [telemetryHook.error, mergeErrors]);

  const mediaJobs = useMemo(() => {
    const fromList = (jobs ?? []).filter((j) => isMediaCapability(jobCap(j)));
    const fromWorkers: WorkerFabricJobSummary[] = [];
    if (workersDash) {
      for (const w of workersDash.workers ?? []) {
        if (w.current_job && isMediaCapability(w.current_job.capability_id)) {
          fromWorkers.push(w.current_job);
        }
      }
      for (const j of workersDash.queued_jobs ?? []) {
        if (j && isMediaCapability(j.capability_id)) fromWorkers.push(j);
      }
    }
    const byId = new Map<string, JobRecord | WorkerFabricJobSummary>();
    for (const j of [...fromList, ...fromWorkers]) {
      byId.set(jobIdOf(j), j);
    }
    return [...byId.values()];
  }, [jobs, workersDash]);

  const counts = useMemo(() => {
    const c = emptyCounts();
    let measured = false;
    for (const j of mediaJobs) {
      const kind = mediaKindFromJob({
        capabilityId: jobCap(j),
        path: typeof (j as JobRecord).path === "string" ? String((j as JobRecord).path) : null,
        human_title: "human_title" in j ? (j.human_title as string | null) : null,
      });
      if (!kind) continue;
      measured = true;
      c[kind] += 1;
    }
    const total = c.image + c.video + c.audio + c.document;
    return { ...c, total, measured };
  }, [mediaJobs]);

  const kpis: MediaKpi[] = useMemo(() => {
    const total = counts.total;
    const pct = (n: number) => (total > 0 ? `${Math.round((n / total) * 100)}% van totaal` : "geen media jobs");
    return [
      {
        id: "total",
        label: "Totale Media",
        value: counts.measured ? total.toLocaleString("nl-NL") : "—",
        sublabel: counts.measured ? "uit media jobs" : "UNAVAILABLE",
        kind: "total",
        available: counts.measured,
        barHeights: decorativeBars(1, counts.measured),
      },
      {
        id: "image",
        label: "Afbeeldingen",
        value: counts.measured ? String(counts.image) : "—",
        sublabel: counts.measured ? pct(counts.image) : "UNAVAILABLE",
        kind: "image",
        available: counts.measured,
        barHeights: decorativeBars(2, counts.measured && counts.image > 0),
      },
      {
        id: "video",
        label: "Video's",
        value: counts.measured ? String(counts.video) : "—",
        sublabel: counts.measured ? pct(counts.video) : "UNAVAILABLE",
        kind: "video",
        available: counts.measured,
        barHeights: decorativeBars(3, counts.measured && counts.video > 0),
      },
      {
        id: "audio",
        label: "Audio",
        value: counts.measured ? String(counts.audio) : "—",
        sublabel: counts.measured ? pct(counts.audio) : "UNAVAILABLE",
        kind: "audio",
        available: counts.measured,
        barHeights: decorativeBars(4, counts.measured && counts.audio > 0),
      },
      {
        id: "document",
        label: "Documenten",
        value: counts.measured ? String(counts.document) : "—",
        sublabel: counts.measured ? pct(counts.document) : "UNAVAILABLE",
        kind: "document",
        available: counts.measured,
        barHeights: decorativeBars(5, counts.measured && counts.document > 0),
      },
    ];
  }, [counts]);

  const storage = useMemo(() => {
    const disk = telemetry?.disk;
    const used = disk?.usedBytes ?? null;
    const total = disk?.totalBytes ?? null;
    const pct =
      disk?.utilizationPct != null
        ? clampPct(disk.utilizationPct)
        : used != null && total != null && total > 0
          ? clampPct((used / total) * 100)
          : null;
    const available = disk?.available === true && (used != null || pct != null);

    // Host telemetry has aggregate disk only — no honest per-type media breakdown.
    const slices: MediaStorageSlice[] = (["image", "video", "audio", "document"] as MediaKind[]).map(
      (kind) => ({
        kind,
        label: MEDIA_KIND_LABEL[kind],
        bytes: null,
        pct: null,
        available: false,
      }),
    );

    return {
      available,
      usedBytes: used,
      totalBytes: total,
      usedPct: pct,
      usedLabel: available && used != null ? formatBytes(used) : "—",
      totalLabel: available && total != null ? formatBytes(total) : "—",
      pctLabel: available && pct != null ? formatPct(pct, true) : "N/A",
      slices,
      note: available
        ? "Host disk capacity — media-type split unavailable"
        : "Disk telemetry unavailable",
    };
  }, [telemetry]);

  const recentMedia: MediaRecentItem[] = useMemo(() => {
    const done = mediaJobs
      .filter((j) => isDoneState(jobState(j)))
      .slice()
      .sort((a, b) => {
        const ta = Date.parse(String(("finished_at" in a && a.finished_at) || ("updatedAt" in a && a.updatedAt) || ("createdAt" in a && a.createdAt) || "")) || 0;
        const tb = Date.parse(String(("finished_at" in b && b.finished_at) || ("updatedAt" in b && b.updatedAt) || ("createdAt" in b && b.createdAt) || "")) || 0;
        return tb - ta;
      })
      .slice(0, 4);

    return done.map((j) => {
      const kind =
        mediaKindFromJob({
          capabilityId: jobCap(j),
          path: typeof (j as JobRecord).path === "string" ? String((j as JobRecord).path) : null,
          human_title: "human_title" in j ? (j.human_title as string | null) : null,
        }) ?? "document";
      const iso =
        ("finished_at" in j && typeof j.finished_at === "string" && j.finished_at) ||
        ("updatedAt" in j && typeof j.updatedAt === "string" && j.updatedAt) ||
        ("createdAt" in j && typeof j.createdAt === "string" && j.createdAt) ||
        null;
      const elapsed =
        "elapsed_seconds" in j && typeof j.elapsed_seconds === "number" ? j.elapsed_seconds : null;
      return {
        id: jobIdOf(j),
        name: jobTitle(j),
        kind,
        relative: formatRelativeNl(iso),
        durationLabel: elapsed != null ? formatDuration(elapsed) : undefined,
        thumb: null,
        to: "/media/library",
      };
    });
  }, [mediaJobs]);

  const generationJobs: MediaGenerationJob[] = useMemo(() => {
    const active = mediaJobs.filter((j) => {
      const s = jobState(j);
      return isActiveState(s) || isDoneState(s);
    });
    const sorted = active.slice().sort((a, b) => {
      const pa = jobProgress(a) ?? (isDoneState(jobState(a)) ? 100 : 0);
      const pb = jobProgress(b) ?? (isDoneState(jobState(b)) ? 100 : 0);
      return pb - pa;
    });
    return sorted.slice(0, 5).map((j) => {
      const state = jobState(j);
      const kind =
        mediaKindFromJob({
          capabilityId: jobCap(j),
          path: typeof (j as JobRecord).path === "string" ? String((j as JobRecord).path) : null,
          human_title: "human_title" in j ? (j.human_title as string | null) : null,
        }) ?? "document";
      const progress = isDoneState(state) ? 100 : jobProgress(j);
      const elapsed =
        "elapsed_display" in j && typeof j.elapsed_display === "string"
          ? j.elapsed_display
          : "elapsed_seconds" in j
            ? formatDuration(j.elapsed_seconds as number | null)
            : "—";
      let tone: MediaGenerationJob["tone"] = "queued";
      if (isFailedState(state)) tone = "failed";
      else if (isDoneState(state)) tone = "done";
      else if (isActiveState(state)) tone = "running";
      return {
        id: jobIdOf(j),
        title: jobTitle(j),
        kind,
        progress,
        progressLabel: progress != null ? `${Math.round(progress)}%` : "—",
        timeLabel: elapsed,
        tone,
      };
    });
  }, [mediaJobs]);

  const typesSeries: MediaTypesDay[] = useMemo(() => {
    const now = Date.now();
    const windowMs = rangeToMs(typesRange);
    const dayCount = typesRange === "24h" ? 1 : typesRange === "7d" ? 7 : typesRange === "30d" ? 30 : 14;
    const days: MediaTypesDay[] = [];
    for (let i = dayCount - 1; i >= 0; i -= 1) {
      const d = new Date(now - i * 24 * 60 * 60 * 1000);
      d.setHours(0, 0, 0, 0);
      days.push({
        key: d.toISOString().slice(0, 10),
        label: dutchDayLabel(d),
        counts: emptyCounts(),
      });
    }
    const byKey = new Map(days.map((d) => [d.key, d]));
    for (const j of mediaJobs) {
      const iso =
        ("createdAt" in j && typeof j.createdAt === "string" && j.createdAt) ||
        ("started_at" in j && typeof j.started_at === "string" && j.started_at) ||
        ("updatedAt" in j && typeof j.updatedAt === "string" && j.updatedAt) ||
        null;
      if (!iso) continue;
      const t = Date.parse(iso);
      if (!Number.isFinite(t) || now - t > windowMs) continue;
      const key = new Date(t);
      key.setHours(0, 0, 0, 0);
      const bucket = byKey.get(key.toISOString().slice(0, 10));
      if (!bucket) continue;
      const kind =
        mediaKindFromJob({
          capabilityId: jobCap(j),
          path: typeof (j as JobRecord).path === "string" ? String((j as JobRecord).path) : null,
          human_title: "human_title" in j ? (j.human_title as string | null) : null,
        }) ?? "document";
      bucket.counts[kind] += 1;
    }
    return days;
  }, [mediaJobs, typesRange]);

  const tools: MediaToolCard[] = useMemo(() => {
    const byId = new Map((capabilities ?? []).map((c) => [c.id, c]));
    const image = byId.get("media.image_generate");
    const video = byId.get("media.video.process") ?? byId.get("media.video_ingest");
    const audio = byId.get("media.audio.process");
    const edit = byId.get("media.image_edit");
    return [
      {
        id: "image",
        title: "Afbeelding Generatie",
        subtitle: capabilitySubtitle(image, "media.image_generate"),
        to: "/media/genereren?tool=image",
        available: image?.available !== false && image != null,
      },
      {
        id: "video",
        title: "Video Generatie",
        subtitle: capabilitySubtitle(video, "media.video.process"),
        to: "/media/genereren?tool=video",
        available: video?.available !== false && video != null,
      },
      {
        id: "audio",
        title: "Audio Generatie",
        subtitle: capabilitySubtitle(audio, "media.audio.process"),
        to: "/media/genereren?tool=audio",
        available: audio?.available !== false && audio != null,
      },
      {
        id: "edit",
        title: "Video Bewerking",
        subtitle: capabilitySubtitle(edit, "media.image_edit"),
        to: "/media/bewerken",
        available: edit?.available !== false && edit != null,
      },
    ];
  }, [capabilities]);

  const platforms: MediaPlatformRow[] = useMemo(() => {
    const rows = [
      { id: "youtube", name: "YouTube", to: "/media/youtube" },
      { id: "x", name: "Twitter / X", to: "/media/distributie" },
      { id: "linkedin", name: "LinkedIn", to: "/media/distributie" },
      { id: "tiktok", name: "TikTok", to: "/media/tiktok" },
      { id: "instagram", name: "Instagram", to: "/media/instagram" },
    ] as const;
    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      to: r.to,
      connected: MEDIA_CONNECTED,
      statusLabel: MEDIA_CONNECTED ? "Actief" : MEDIA_STATUS_LABEL,
      countLabel: MEDIA_CONNECTED ? "—" : "—",
      spark: [],
    }));
  }, []);

  const activities: MediaActivityRow[] = useMemo(() => {
    const fromJobs = mediaJobs
      .slice()
      .sort((a, b) => {
        const ta =
          Date.parse(
            String(
              ("updatedAt" in a && a.updatedAt) ||
                ("started_at" in a && a.started_at) ||
                ("createdAt" in a && a.createdAt) ||
                "",
            ),
          ) || 0;
        const tb =
          Date.parse(
            String(
              ("updatedAt" in b && b.updatedAt) ||
                ("started_at" in b && b.started_at) ||
                ("createdAt" in b && b.createdAt) ||
                "",
            ),
          ) || 0;
        return tb - ta;
      })
      .slice(0, 6)
      .map((j) => {
        const state = jobState(j);
        const kind =
          mediaKindFromJob({
            capabilityId: jobCap(j),
            human_title: "human_title" in j ? (j.human_title as string | null) : null,
          }) ?? "document";
        const verb = isDoneState(state)
          ? "voltooid"
          : isFailedState(state)
            ? "mislukt"
            : isActiveState(state)
              ? "gestart"
              : "bijgewerkt";
        const iso =
          ("updatedAt" in j && typeof j.updatedAt === "string" && j.updatedAt) ||
          ("started_at" in j && typeof j.started_at === "string" && j.started_at) ||
          ("createdAt" in j && typeof j.createdAt === "string" && j.createdAt) ||
          null;
        return {
          id: jobIdOf(j),
          time: formatClock(iso),
          description: `${MEDIA_KIND_LABEL[kind]} ${verb} (${jobTitle(j)})`,
          kind,
          tone: (kind === "video"
            ? "research"
            : kind === "image"
              ? "info"
              : kind === "audio"
                ? "warning"
                : "data") as BadgeTone,
        };
      });

    if (fromJobs.length > 0) return fromJobs;

    return (activity ?? []).slice(0, 6).map((ev) => ({
      id: ev.eventId,
      time: formatClock(ev.createdAt),
      description: ev.taskTitle || ev.eventType || "Activiteit",
      kind: "system" as const,
      tone: "system" as BadgeTone,
    }));
  }, [mediaJobs, activity]);

  const gpuDevices = useMemo(() => {
    const devices = telemetry?.gpu.devices ?? [];
    return devices.map((d) => {
      const temp =
        d.temperatureC != null && Number.isFinite(d.temperatureC)
          ? d.temperatureC
          : tempFromHardware(hardware, d.index, d.name);
      return {
        index: d.index,
        name: d.name || `GPU ${d.index}`,
        util: clampPct(d.utilizationPct),
        vramUsedBytes: d.vramUsedBytes ?? null,
        vramTotalBytes: d.vramTotalBytes ?? null,
        tempC: temp,
      };
    });
  }, [telemetry, hardware]);

  useEffect(() => {
    if (!gpuDevices.length) {
      if (selectedGpuIndex !== 0) setSelectedGpuIndex(0);
      return;
    }
    if (selectedGpuIndex < 0 || selectedGpuIndex >= gpuDevices.length) setSelectedGpuIndex(0);
  }, [gpuDevices, selectedGpuIndex]);

  const renderingQueue = useMemo(() => {
    const active = generationJobs.filter((j) => j.tone === "running" || j.tone === "queued").length;
    return { active, label: `${active} actief` };
  }, [generationJobs]);

  const performance = useMemo(() => {
    const windowMs = rangeToMs(perfRange === "24h" ? "24h" : perfRange === "7d" ? "7d" : "30d");
    const now = Date.now();
    let generated = 0;
    let success = 0;
    let failed = 0;
    let elapsedSum = 0;
    let elapsedN = 0;
    for (const j of mediaJobs) {
      const iso =
        ("finished_at" in j && typeof j.finished_at === "string" && j.finished_at) ||
        ("updatedAt" in j && typeof j.updatedAt === "string" && j.updatedAt) ||
        ("createdAt" in j && typeof j.createdAt === "string" && j.createdAt) ||
        null;
      if (!iso) continue;
      const t = Date.parse(iso);
      if (!Number.isFinite(t) || now - t > windowMs) continue;
      const state = jobState(j);
      if (isDoneState(state) || isFailedState(state) || isActiveState(state)) {
        generated += 1;
      }
      if (isDoneState(state)) success += 1;
      if (isFailedState(state)) failed += 1;
      if ("elapsed_seconds" in j && typeof j.elapsed_seconds === "number") {
        elapsedSum += j.elapsed_seconds;
        elapsedN += 1;
      }
    }
    const decided = success + failed;
    const successPct = decided > 0 ? (success / decided) * 100 : null;
    const avgMin = elapsedN > 0 ? elapsedSum / elapsedN / 60 : null;
    const available = mediaJobs.length > 0 || jobs != null;
    return {
      available,
      generated: available ? generated : null,
      avgRenderMin: avgMin,
      successPct,
      generatedDelta: null as string | null,
      avgDelta: null as string | null,
      successDelta: null as string | null,
    };
  }, [mediaJobs, jobs, perfRange]);

  const engineLabel = useMemo(() => {
    if (!mediaStatus) return errors.mediaStatus ? "Offline" : "UNMEASURED";
    const worker = String(mediaStatus.worker ?? "").toUpperCase();
    const ffmpeg = String(mediaStatus.ffmpeg ?? "").toUpperCase();
    if (worker === "READY" || worker === "RUNNING" || ffmpeg === "AVAILABLE") return "Running";
    if (worker === "UNKNOWN" && ffmpeg === "UNKNOWN") return "UNKNOWN";
    if (worker.includes("FAIL") || worker === "DOWN") return "Offline";
    return worker || "UNKNOWN";
  }, [mediaStatus, errors.mediaStatus]);

  const sidebarStatus: SidebarStatusRow[] = useMemo(() => {
    const rows: SidebarStatusRow[] = [
      {
        id: "media-engine",
        label: "Media Engine",
        value: engineLabel,
        tone:
          engineLabel === "Running"
            ? "success"
            : engineLabel === "Offline"
              ? "danger"
              : "muted",
      },
    ];

    const devices = gpuDevices.slice(0, 2);
    if (devices.length === 0) {
      rows.push({
        id: "gpu-none",
        label: "GPU",
        value: telemetry?.gpu.available === false ? "Unavailable" : "UNMEASURED",
        tone: "muted",
      });
    } else {
      for (const d of devices) {
        const shortName = d.name.replace(/^NVIDIA\s+/i, "");
        rows.push({
          id: `gpu-${d.index}`,
          label: `GPU ${d.index} - ${shortName}`,
          value: d.util != null ? "Ready" : "UNMEASURED",
          tone: d.util == null ? "muted" : "success",
        });
      }
    }

    rows.push({
      id: "storage",
      label: "Storage",
      value:
        storage.available && storage.usedBytes != null && storage.totalBytes != null
          ? `${formatBytes(storage.usedBytes)} / ${formatBytes(storage.totalBytes)}`
          : "UNMEASURED",
      tone: storage.available ? "info" : "muted",
    });

    const queueActive = renderingQueue.active;
    const queueCap =
      workersDash?.summary.queue_depth != null
        ? Math.max(queueActive, workersDash.summary.queue_depth)
        : null;
    rows.push({
      id: "media-queue",
      label: "Media Queue",
      value:
        jobs != null || workersDash != null
          ? queueCap != null
            ? `${queueActive} / ${queueCap} actief`
            : `${queueActive} actief`
          : "UNMEASURED",
      tone: queueActive > 0 ? "success" : "muted",
    });

    return rows;
  }, [
    engineLabel,
    gpuDevices,
    telemetry,
    storage,
    renderingQueue.active,
    workersDash,
    jobs,
  ]);

  const online: boolean | null = useMemo(() => {
    if (engineLabel === "Running") return true;
    if (engineLabel === "Offline") return false;
    return null;
  }, [engineLabel]);

  return {
    loading,
    refreshing,
    refresh,
    online,
    errors,
    kpis,
    storage,
    recentMedia,
    generationJobs,
    typesRange,
    setTypesRange,
    typesSeries,
    tools,
    platforms,
    activities,
    gpuPanel: {
      devices: gpuDevices,
      selectedIndex: selectedGpuIndex,
      setSelectedIndex: setSelectedGpuIndex,
      renderingQueue,
    },
    perfRange,
    setPerfRange,
    performance,
    sidebarStatus,
    mediaStatus,
    telemetry: telemetry as SystemTelemetryResponse | null,
    classifyMediaCapability,
  };
}
