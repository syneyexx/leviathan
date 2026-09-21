/** Shared FINALBETA media/stats page chrome (welcome + clock). */
"use client";

import { useEffect, useState, type ReactNode } from "react";
import { FbIcon } from "../icons";

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

function pad(n: number) {
  return String(n).padStart(2, "0");
}

export function useMediaClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 15_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

export function MediaWelcome({
  title,
  subtitle,
  quote,
  right,
  brand,
}: {
  title: ReactNode;
  subtitle: string;
  quote: string;
  right?: ReactNode;
  brand?: ReactNode;
}) {
  const now = useMediaClock();
  return (
    <div className="mc-welcome">
      <div className="mc-welcome-copy">
        {brand}
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="mc-welcome-mid">“{quote}”</div>
      {right ?? (
        <div className="mc-clock">
          <div className="mc-clock-copy">
            <div className="date">
              {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
            </div>
            <div className="time">
              {pad(now.getHours())}:{pad(now.getMinutes())}
            </div>
          </div>
          <FbIcon name="bolt" size={22} className="mc-sun" />
        </div>
      )}
    </div>
  );
}

export function McTrend({ value, tone = "up" }: { value: string; tone?: "up" | "down" | "flat" }) {
  return <span className={`mc-trend ${tone}`}>{value}</span>;
}

export function McFooter() {
  return (
    <footer className="fb-page-footer">
      <span>HADES FINALBETA v0.9.0 | Local AI Platform</span>
      <span className="fb-page-footer-right">Build a smarter tomorrow.</span>
    </footer>
  );
}
