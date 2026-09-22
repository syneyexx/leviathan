import { useMemo, useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { PageHero, Panel, Pill, PlatformGlyph } from "./mr-shared";

type CalPlatform = "youtube" | "tiktok" | "instagram" | "linkedin";
type ViewMode = "month" | "week" | "list";
type EventTone = "yt" | "tt" | "ig" | "li";

type CalEvent = {
  id: string;
  title: string;
  tone: EventTone;
  platform: CalPlatform;
  time: string;
};

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const TODAY = 22;
/** April 2025 starts on Tuesday → two leading blanks for Sun-start grid. */
const LEAD_BLANKS = 2;
const DAYS_IN_MONTH = 30;

const EVENTS: Record<number, CalEvent[]> = {
  1: [{ id: "e1", title: "Kickoff Q2", tone: "li", platform: "linkedin", time: "10:00" }],
  3: [
    { id: "e2", title: "YT Short", tone: "yt", platform: "youtube", time: "09:00" },
    { id: "e3", title: "IG Reel", tone: "ig", platform: "instagram", time: "16:00" },
  ],
  7: [{ id: "e4", title: "TikTok batch", tone: "tt", platform: "tiktok", time: "11:00" }],
  10: [
    { id: "e5", title: "Product Demo", tone: "yt", platform: "youtube", time: "14:00" },
    { id: "e6", title: "LI essay", tone: "li", platform: "linkedin", time: "09:30" },
  ],
  14: [{ id: "e7", title: "Stories drop", tone: "ig", platform: "instagram", time: "12:00" }],
  16: [{ id: "e8", title: "Trend cut", tone: "tt", platform: "tiktok", time: "18:00" }],
  18: [
    { id: "e9", title: "Campagne sync", tone: "li", platform: "linkedin", time: "10:00" },
    { id: "e10", title: "YT longform", tone: "yt", platform: "youtube", time: "15:00" },
  ],
  21: [{ id: "e11", title: "IG carousel", tone: "ig", platform: "instagram", time: "13:00" }],
  22: [
    { id: "e12", title: "AI Pet Hook", tone: "tt", platform: "tiktok", time: "09:00" },
    { id: "e13", title: "Discipline Cut", tone: "yt", platform: "youtube", time: "15:00" },
    { id: "e14", title: "Team Sync", tone: "li", platform: "linkedin", time: "16:30" },
  ],
  24: [{ id: "e15", title: "Weekend teaser", tone: "ig", platform: "instagram", time: "11:00" }],
  28: [
    { id: "e16", title: "Launch window", tone: "yt", platform: "youtube", time: "10:00" },
    { id: "e17", title: "TT challenge", tone: "tt", platform: "tiktok", time: "19:00" },
  ],
  30: [{ id: "e18", title: "Month wrap", tone: "li", platform: "linkedin", time: "14:00" }],
};

const CHECKLIST = [
  { id: "c1", label: "Script goedgekeurd", done: true },
  { id: "c2", label: "Visual assets klaar", done: true },
  { id: "c3", label: "Captions + hashtags", done: true },
  { id: "c4", label: "Thumbnail A/B", done: true },
  { id: "c5", label: "Platform crop check", done: true },
  { id: "c6", label: "CTA link verified", done: true },
  { id: "c7", label: "Final legal review", done: false },
];

const TIMELINE = [
  { name: "HADES Launch Q2", start: 8, width: 42, color: "#22c9d6" },
  { name: "Creator Growth Push", start: 22, width: 48, color: "#f0c875" },
  { name: "Short-form Lab", start: 35, width: 36, color: "#fe2c55" },
  { name: "Podcast Autumn Arc", start: 55, width: 30, color: "#a78bfa" },
];

const DEADLINES = [
  { day: "23", month: "APR", title: "Deadline assets · YT", hint: "09:00 · Hoog" },
  { day: "24", month: "APR", title: "Captions review", hint: "14:00 · Normaal" },
  { day: "26", month: "APR", title: "Legal sign-off", hint: "11:00 · Hoog" },
  { day: "28", month: "APR", title: "Launch pack freeze", hint: "17:00 · Kritiek" },
  { day: "30", month: "APR", title: "Month wrap report", hint: "16:00 · Normaal" },
];

const SHOOTS = [
  { title: "Studio: AI Pet duo", when: "23 Apr · 10:00–13:00", status: "Bevestigd" },
  { title: "Outdoor: Nature POV", when: "25 Apr · 07:30–11:00", status: "Planning" },
  { title: "Desk: Cozy productivity", when: "27 Apr · 14:00–16:00", status: "Crew TBD" },
];

const LAUNCH_WINDOWS = [
  { platform: "youtube" as const, label: "YouTube", window: "10:00 – 12:00", level: "Hoog", pct: 92 },
  { platform: "tiktok" as const, label: "TikTok", window: "18:00 – 21:00", level: "Hoog", pct: 88 },
  { platform: "instagram" as const, label: "Instagram", window: "12:00 – 14:00", level: "Mid", pct: 64 },
  { platform: "linkedin" as const, label: "LinkedIn", window: "08:00 – 09:30", level: "Mid", pct: 58 },
];

const SELECTED_META = {
  title: "AI Pet Hook — Discipline Drop",
  campaign: "Creator Growth Push",
  persona: "Gen-Z Builder",
  status: "Scheduled",
  platforms: ["tiktok", "youtube", "instagram"] as CalPlatform[],
  when: "Vandaag 15:00 UTC",
  owner: "Alex · Media Ops",
};

export function MediaCalendarPage() {
  const toast = useAppToast();
  const [view, setView] = useState<ViewMode>("month");
  const [selectedDay, setSelectedDay] = useState(TODAY);
  const [checks, setChecks] = useState(CHECKLIST);
  const [selectedEventId, setSelectedEventId] = useState("e12");

  const cells = useMemo(() => {
    const out: Array<number | null> = [];
    for (let i = 0; i < LEAD_BLANKS; i += 1) out.push(null);
    for (let d = 1; d <= DAYS_IN_MONTH; d += 1) out.push(d);
    while (out.length % 7 !== 0) out.push(null);
    return out;
  }, []);

  const dayEvents = EVENTS[selectedDay] ?? [];
  const selectedEvent = dayEvents.find((e) => e.id === selectedEventId) ?? dayEvents[0] ?? null;
  const doneCount = checks.filter((c) => c.done).length;

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Calendar Mode"
      searchPlaceholder="Search media, content, campaigns, platforms, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.calendar} title="CALENDAR — Plan. Produce. Publish. Grow." imageOnly />

        <section className="lv-mc-kpi-row">
          <article className="lv-mr-kpi is-cyan">
            <div className="lbl">Total Scheduled</div>
            <div className="val">42</div>
            <div className="sub">
              <span className="delta">↑ +8</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-green">
            <div className="lbl">Published</div>
            <div className="val">28</div>
            <div className="sub">
              <span className="delta">↑ +12%</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-gold">
            <div className="lbl">Engagement</div>
            <div className="val">1.4M</div>
            <div className="sub">
              <span className="delta">↑ +19%</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-cyan">
            <div className="lbl">Active Campaigns</div>
            <div className="val">6</div>
            <div className="sub">
              <Pill tone="cyan">Live</Pill>
            </div>
          </article>
          <article className="lv-mr-kpi is-red">
            <div className="lbl">Upcoming Deadlines</div>
            <div className="val">5</div>
            <div className="sub">
              <span className="lv-mr-bad">2 kritiek</span>
            </div>
          </article>
          <aside className="lv-mr-quote-card">
            “Plan. Produce. Publish. Grow.” — LEVIATHAN
          </aside>
        </section>

        <Panel>
          <div className="lv-mr-toolbar">
            <select className="lv-mr-select" defaultValue="all" aria-label="Platform">
              <option value="all">Alle platforms</option>
              <option>YouTube</option>
              <option>TikTok</option>
              <option>Instagram</option>
              <option>LinkedIn</option>
            </select>
            <select className="lv-mr-select" defaultValue="all" aria-label="Campaign">
              <option value="all">Alle campagnes</option>
              <option>Creator Growth Push</option>
              <option>HADES Launch Q2</option>
              <option>Short-form Lab</option>
            </select>
            <select className="lv-mr-select" defaultValue="all" aria-label="Persona">
              <option value="all">Alle persona’s</option>
              <option>Gen-Z Builder</option>
              <option>Operator</option>
              <option>Founder</option>
            </select>
            <select className="lv-mr-select" defaultValue="all" aria-label="Status">
              <option value="all">Alle statussen</option>
              <option>Scheduled</option>
              <option>Draft</option>
              <option>In review</option>
              <option>Published</option>
            </select>
            <button type="button" className="lv-mr-btn" onClick={() => { setSelectedDay(TODAY); toast("Vandaag"); }}>
              Today
            </button>
            <strong style={{ color: "#f0c875", letterSpacing: "0.08em", fontSize: 13 }}>April 2025</strong>
            <div className="lv-mr-tabs" style={{ border: 0 }} role="tablist">
              {(
                [
                  ["month", "Month"],
                  ["week", "Week"],
                  ["list", "List"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  className={`lv-mr-tab${view === id ? " is-active" : ""}`}
                  onClick={() => setView(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Create Content")}>
              + Create Content
            </button>
            <div className="lv-mc-visuals">
              <div className="lv-mc-visual">
                <img src={mediaPageArt.calendarVisual1} alt="" />
              </div>
              <div className="lv-mc-visual">
                <img src={mediaPageArt.calendarVisual2} alt="" />
              </div>
              <div className="lv-mc-visual">
                <img src={mediaPageArt.calendarVisual3} alt="" />
              </div>
            </div>
          </div>
        </Panel>

        <section className="lv-mr-split">
          <Panel title={view === "list" ? "Content List · April 2025" : "April 2025"}>
            {view === "list" ? (
              <div style={{ display: "grid", gap: 6 }}>
                {Object.entries(EVENTS)
                  .flatMap(([day, list]) => list.map((e) => ({ ...e, day: Number(day) })))
                  .map((e) => (
                    <button
                      key={e.id}
                      type="button"
                      className={`lv-mc-event is-${e.tone}`}
                      style={{ width: "100%", textAlign: "left", cursor: "pointer", background: "rgba(255,255,255,0.04)", border: 0, color: "inherit" }}
                      onClick={() => {
                        setSelectedDay(e.day);
                        setSelectedEventId(e.id);
                      }}
                    >
                      <span className="lv-mr-muted">{e.day} Apr</span>
                      <PlatformGlyph platform={e.platform} />
                      <strong style={{ color: "#f0ebe3" }}>{e.title}</strong>
                      <span className="lv-mr-muted">{e.time}</span>
                    </button>
                  ))}
              </div>
            ) : (
              <div className="lv-mc-cal">
                {DOW.map((d) => (
                  <div key={d} className="lv-mc-dow">
                    {d}
                  </div>
                ))}
                {cells.map((day, idx) => {
                  if (day == null) {
                    return <div key={`empty-${idx}`} className="lv-mc-cell" style={{ opacity: 0.35 }} />;
                  }
                  const events = EVENTS[day] ?? [];
                  const visible = view === "week" && (day < 20 || day > 26) ? [] : events;
                  const isToday = day === TODAY;
                  return (
                    <button
                      key={day}
                      type="button"
                      className={`lv-mc-cell${isToday ? " is-today" : ""}`}
                      style={{
                        cursor: "pointer",
                        textAlign: "left",
                        color: "inherit",
                        outline: selectedDay === day ? "1px solid rgba(34, 201, 214, 0.45)" : undefined,
                      }}
                      onClick={() => {
                        setSelectedDay(day);
                        if (events[0]) setSelectedEventId(events[0].id);
                      }}
                    >
                      <div className="day">{day}</div>
                      {(view === "week" ? visible : events).slice(0, 3).map((e) => (
                        <div
                          key={e.id}
                          className={`lv-mc-event is-${e.tone}`}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            setSelectedDay(day);
                            setSelectedEventId(e.id);
                          }}
                        >
                          {e.title}
                        </div>
                      ))}
                      {events.length > 3 ? (
                        <div className="lv-mr-muted" style={{ fontSize: 10 }}>
                          +{events.length - 3} meer
                        </div>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            )}
          </Panel>

          <Panel
            title="Selected Content"
            action={<Pill tone="gold">{doneCount}/7 checklist</Pill>}
          >
            <div className="lv-mc-selected-media">
              <img src={mediaPageArt.calendarSelected} alt="" />
            </div>
            <div style={{ marginTop: 10 }}>
              <strong style={{ color: "#f0ebe3", fontSize: 15 }}>
                {selectedEvent?.title ?? SELECTED_META.title}
              </strong>
              <p className="lv-mr-muted" style={{ margin: "4px 0 0", fontSize: 12 }}>
                {SELECTED_META.campaign} · {SELECTED_META.persona}
              </p>
            </div>
            <div className="lv-mq-meta">
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Datum</span>
                <strong>
                  {selectedDay} April 2025{selectedEvent ? ` · ${selectedEvent.time}` : ""}
                </strong>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Platforms</span>
                <div className="lv-mr-plat-row">
                  {(selectedEvent ? [selectedEvent.platform] : SELECTED_META.platforms).map((p) => (
                    <PlatformGlyph key={p} platform={p} />
                  ))}
                </div>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Status</span>
                <Pill tone="cyan">{SELECTED_META.status}</Pill>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Owner</span>
                <span>{SELECTED_META.owner}</span>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Publish</span>
                <span>{SELECTED_META.when}</span>
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 6 }}>
                Publish Checklist
              </div>
              {checks.map((c) => (
                <label key={c.id} className="lv-mc-check">
                  <input
                    type="checkbox"
                    checked={c.done}
                    onChange={() =>
                      setChecks((prev) => prev.map((x) => (x.id === c.id ? { ...x, done: !x.done } : x)))
                    }
                  />
                  <span style={{ color: c.done ? "#c8d4dc" : "#f0ebe3" }}>{c.label}</span>
                </label>
              ))}
            </div>

            <div className="lv-mq-actions">
              <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Publiceren")}>
                ▶ Publiceren
              </button>
              <div className="lv-mq-actions-row">
                <button type="button" className="lv-mr-btn" style={{ flex: 1 }} onClick={() => toast("Bewerken")}>
                  Bewerken
                </button>
                <button type="button" className="lv-mr-btn" style={{ flex: 1 }} onClick={() => toast("Verplaatsen")}>
                  Verplaatsen
                </button>
              </div>
            </div>
          </Panel>
        </section>

        <section className="lv-mc-bottom">
          <Panel title="Content Timeline">
            <div style={{ display: "grid", gap: 10, paddingTop: 4 }}>
              {TIMELINE.map((row) => (
                <div key={row.name}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
                    <span style={{ color: "#f0ebe3" }}>{row.name}</span>
                    <span className="lv-mr-muted">Apr</span>
                  </div>
                  <div
                    style={{
                      position: "relative",
                      height: 14,
                      borderRadius: 4,
                      background: "rgba(255,255,255,0.04)",
                      border: "1px solid rgba(40,60,80,0.4)",
                      overflow: "hidden",
                    }}
                  >
                    <span
                      style={{
                        position: "absolute",
                        left: `${row.start}%`,
                        width: `${row.width}%`,
                        top: 2,
                        bottom: 2,
                        borderRadius: 3,
                        background: row.color,
                        opacity: 0.85,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Upcoming Deadlines">
            {DEADLINES.map((d) => (
              <button
                key={d.title}
                type="button"
                onClick={() => toast(d.title)}
                style={{
                  display: "grid",
                  gridTemplateColumns: "44px 1fr",
                  gap: 10,
                  alignItems: "center",
                  width: "100%",
                  textAlign: "left",
                  background: "transparent",
                  border: 0,
                  borderBottom: "1px solid rgba(40,60,80,0.35)",
                  padding: "8px 0",
                  color: "inherit",
                  cursor: "pointer",
                }}
              >
                <span
                  style={{
                    display: "grid",
                    placeItems: "center",
                    borderRadius: 6,
                    border: "1px solid rgba(240,200,117,0.35)",
                    padding: "4px 0",
                    fontSize: 10,
                    color: "#f0c875",
                  }}
                >
                  <strong style={{ fontSize: 14, lineHeight: 1 }}>{d.day}</strong>
                  {d.month}
                </span>
                <span>
                  <div style={{ color: "#f0ebe3", fontSize: 12 }}>{d.title}</div>
                  <div className="lv-mr-muted" style={{ fontSize: 11 }}>
                    {d.hint}
                  </div>
                </span>
              </button>
            ))}
          </Panel>

          <Panel title="Planned Shoots">
            {SHOOTS.map((s) => (
              <div
                key={s.title}
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid rgba(40,60,80,0.35)",
                  fontSize: 12,
                }}
              >
                <div style={{ color: "#f0ebe3" }}>{s.title}</div>
                <div className="lv-mr-muted" style={{ marginTop: 2 }}>
                  {s.when}
                </div>
                <div style={{ marginTop: 4 }}>
                  <Pill tone={s.status === "Bevestigd" ? "green" : s.status === "Planning" ? "gold" : "muted"}>
                    {s.status}
                  </Pill>
                </div>
              </div>
            ))}
          </Panel>

          <Panel title="Launch Windows">
            {LAUNCH_WINDOWS.map((w) => (
              <div key={w.platform} className="lv-mv-heat-row">
                <PlatformGlyph platform={w.platform} />
                <div>
                  <div style={{ color: "#f0ebe3" }}>{w.label}</div>
                  <div className="lv-mr-muted" style={{ fontSize: 11 }}>
                    {w.window}
                  </div>
                </div>
                <Pill tone={w.level === "Hoog" ? "green" : "gold"}>{w.level}</Pill>
                <strong style={{ color: "#22c9d6" }}>{w.pct}%</strong>
              </div>
            ))}
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
