import type { ReactNode } from "react";
import { media } from "../../assets/media";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";

export function TradingShell({
  children,
  title = "Trading Center",
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <AppShell
      activeMode="explore"
      modeLabel="Trading Mode"
      searchPlaceholder="Search markets, strategies, or ask Leviathan..."
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tr-main">
        <section className="lv-tr-hero" aria-label={title}>
          <img src={media.tradingHero} alt="" width={1400} height={220} />
        </section>
        <SubMenu />
        {children}
        <p className="lv-footer-quote">
          “The best trades are not found in the noise, but in the alignment of data, discipline and time.” —
          LEVIATHAN
        </p>
      </main>
    </AppShell>
  );
}

export function fmtMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "UNMEASURED";
  return `${(n * 100).toFixed(2)}%`;
}

export function metricValue(metrics: Record<string, unknown> | undefined, key: string): string {
  const raw = metrics?.[key];
  if (!raw || typeof raw !== "object") return "UNMEASURED";
  const m = raw as { status?: string; value?: number | null; reason?: string };
  if (m.status === "UNMEASURED" || m.value == null) return m.reason ? `UNMEASURED` : "UNMEASURED";
  if (key.includes("drawdown") || key.includes("return") || key.includes("rate")) {
    return fmtPct(Number(m.value));
  }
  if (typeof m.value === "number") return m.value.toFixed(4);
  return String(m.value);
}

export function hashShort(hash: string | null | undefined): string {
  if (!hash) return "—";
  return `${hash.slice(0, 8)}…${hash.slice(-4)}`;
}
