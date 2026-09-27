import { useEffect, useState } from "react";
import { formatClock } from "../lib/format";

export function Banner({ frozen, utc = false }: { frozen?: Date; utc?: boolean }) {
  const [now, setNow] = useState(() => frozen ?? new Date());
  useEffect(() => {
    if (frozen) return;
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, [frozen]);
  const clock = formatClock(now, utc || Boolean(frozen));
  return (
    <section className="banner" aria-label="LEVIATHAN Backend Host">
      <h1>LEVIATHAN Backend Host</h1>
      <div className="art-hit" />
      <div className="clock">
        <div className="label">SYSTEM TIME</div>
        <strong>{clock.date}</strong>
        <strong>{clock.time}</strong>
        <em>{clock.zone}</em>
      </div>
    </section>
  );
}
