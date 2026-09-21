/** Shared TradingCenter chrome — reuses Media Control welcome classes. */
"use client";

import type { ReactNode } from "react";
import { chartPolyline } from "../hooks/dashboard-live-utils";
import { MediaWelcome, McFooter, McTrend } from "../media/media-chrome";

export { MediaWelcome as TradingWelcome, McFooter as TcFooter, McTrend as TcTrend };

export function TcSpark({
  values,
  tone = "up",
  width = 72,
  height = 24,
}: {
  values: number[];
  tone?: "up" | "down" | "flat" | "warn";
  width?: number;
  height?: number;
}) {
  const stroke =
    tone === "down" ? "#f87171" : tone === "flat" ? "#6f8490" : tone === "warn" ? "#f0b429" : "#22c55e";
  return (
    <svg className="tc-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <path
        d={chartPolyline(values, width, height)}
        fill="none"
        stroke={stroke}
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function TcPill({
  children,
  tone = "green",
}: {
  children: ReactNode;
  tone?: "green" | "blue" | "gold" | "orange" | "red" | "gray" | "cyan";
}) {
  return <span className={`tc-pill ${tone}`}>{children}</span>;
}

export function TcFooterBanner({ left, right }: { left: string; right: string }) {
  return (
    <footer className="fb-page-footer tc-page-footer">
      <span>{left}</span>
      <span className="fb-page-footer-right">{right}</span>
    </footer>
  );
}
