import type { Measured } from "../../../../types/researchCommand";

export const UNMEASURED = "UNMEASURED";

export function asRec(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

export function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function measuredNumber(m: Measured | null | undefined): number | null {
  if (!m || m.measurement === "UNMEASURED" || m.measurement === "EMPTY") return null;
  return asNumber(m.value);
}

export function fmtInt(n: number | null): string {
  return n == null ? UNMEASURED : String(Math.round(n));
}

export function fmtUsd(n: number, digits = 0): string {
  return `$ ${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function fmtPct(n: number | null, digits = 1): string {
  if (n == null) return UNMEASURED;
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function shortId(v: unknown, len = 18): string {
  const s = v == null ? "" : String(v);
  if (!s) return "—";
  return s.length > len ? `${s.slice(0, len)}…` : s;
}

const DAYS = ["Zo", "Ma", "Di", "Wo", "Do", "Vr", "Za"];
const MONTHS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"];

export function fmtHubDate(d: Date): string {
  return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function fmtHubTime(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
