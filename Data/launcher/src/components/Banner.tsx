import { useEffect, useState } from "react";
import crest from "../assets/crest.svg";
import geometry from "../assets/geometry.svg";
import skyline from "../assets/skyline.svg";
import { formatClock } from "../lib/format";

export function Banner({ frozen }: { frozen?: Date }) {
  const [now, setNow] = useState(() => frozen ?? new Date());
  useEffect(() => {
    if (frozen) return;
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, [frozen]);
  const clock = formatClock(now);
  return (
    <section className="banner" aria-label="LEVIATHAN Backend Host">
      <div className="brand">
        <img src={crest} alt="" />
        <div>
          <h1>LEVIATHAN</h1>
          <p>BACKEND HOST</p>
          <small>TARTARIAN INTELLIGENCE INFRASTRUCTURE</small>
        </div>
      </div>
      <div className="seal-wrap">
        <img className="skyline" src={skyline} alt="" />
        <img className="seal" src={geometry} alt="" />
      </div>
      <div className="clock">
        <div className="motto">SCIENTIA<br />INFRASTRUCTURA<br />SAPIENTIA<br />IN AETERNUM</div>
        <div className="label">SYSTEM TIME</div>
        <strong>{clock.date}</strong>
        <strong>{clock.time}</strong>
        <em>{clock.zone}</em>
      </div>
    </section>
  );
}
