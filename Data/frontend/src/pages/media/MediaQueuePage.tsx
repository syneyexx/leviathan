import { useMemo, useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { PageHero, Panel, Pill, PlatformGlyph, Spark } from "./mr-shared";

type Status = "queue" | "live" | "wait" | "approved" | "failed";
type Priority = "Hoog" | "Normaal" | "Laag";
type Platform = "youtube" | "tiktok" | "instagram" | "facebook";

type QueueItem = {
  id: string;
  title: string;
  tags: string;
  platforms: Platform[];
  when: string;
  status: Status;
  priority: Priority;
  assets: string;
  duration: string;
  thumb: string;
  retries?: string;
};

const STATUS_TONE: Record<Status, "cyan" | "green" | "gold" | "red" | "blue"> = {
  queue: "cyan",
  live: "green",
  wait: "gold",
  approved: "green",
  failed: "red",
};

const STATUS_LABEL: Record<Status, string> = {
  queue: "In wachtrij",
  live: "Publiceren",
  wait: "Wachten",
  approved: "Goedgekeurd",
  failed: "Mislukt",
};

const TABS = [
  { id: "all", label: "Alle", count: 54 },
  { id: "queue", label: "In wachtrij", count: 42 },
  { id: "live", label: "Nu publiceren", count: 3 },
  { id: "wait", label: "Goedkeuring", count: 7 },
  { id: "done", label: "Gepubliceerd", count: 186 },
  { id: "failed", label: "Mislukt", count: 2 },
] as const;

const ITEMS: QueueItem[] = [
  {
    id: "q1",
    title: "Discipline Changes Everything",
    tags: "#mindset #discipline #leviathan",
    platforms: ["youtube", "tiktok", "instagram"],
    when: "Vandaag 15:00 UTC",
    status: "queue",
    priority: "Hoog",
    assets: "3/3",
    duration: "01:24",
    thumb: mediaPageArt.queueThumbs[0],
  },
  {
    id: "q2",
    title: "The Compounding Mind",
    tags: "#growth #systems #focus",
    platforms: ["youtube", "facebook"],
    when: "Vandaag 17:30 UTC",
    status: "wait",
    priority: "Normaal",
    assets: "2/3",
    duration: "00:48",
    thumb: mediaPageArt.queueThumbs[1],
  },
  {
    id: "q3",
    title: "Markets After Midnight",
    tags: "#markets #liquidity #macro",
    platforms: ["tiktok", "instagram"],
    when: "Morgen 09:00 UTC",
    status: "approved",
    priority: "Normaal",
    assets: "3/3",
    duration: "00:32",
    thumb: mediaPageArt.queueThumbs[2],
  },
  {
    id: "q4",
    title: "Build in Silence",
    tags: "#builders #ambition",
    platforms: ["instagram", "facebook"],
    when: "Morgen 12:00 UTC",
    status: "queue",
    priority: "Laag",
    assets: "1/3",
    duration: "00:56",
    thumb: mediaPageArt.queueThumbs[3],
  },
  {
    id: "q5",
    title: "Neural Edge Briefing",
    tags: "#ai #research #edge",
    platforms: ["youtube"],
    when: "Wo 11:00 UTC",
    status: "live",
    priority: "Hoog",
    assets: "3/3",
    duration: "02:10",
    thumb: mediaPageArt.queueThumbs[4],
  },
  {
    id: "q6",
    title: "Audience Gravity",
    tags: "#content #reach",
    platforms: ["tiktok", "youtube", "instagram"],
    when: "Wo 18:00 UTC",
    status: "failed",
    priority: "Hoog",
    assets: "2/3",
    duration: "00:41",
    thumb: mediaPageArt.queueThumbs[5],
    retries: "3x",
  },
  {
    id: "q7",
    title: "A Brighter Tomorrow",
    tags: "#brand #vision",
    platforms: ["facebook", "instagram"],
    when: "Do 10:00 UTC",
    status: "queue",
    priority: "Normaal",
    assets: "3/3",
    duration: "01:05",
    thumb: mediaPageArt.queueThumbs[6],
  },
  {
    id: "q8",
    title: "Signal Over Noise",
    tags: "#signal #clarity",
    platforms: ["youtube", "tiktok"],
    when: "Do 16:00 UTC",
    status: "wait",
    priority: "Laag",
    assets: "3/3",
    duration: "00:38",
    thumb: mediaPageArt.queueThumbs[7],
  },
];

export function MediaQueuePage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("all");
  const [selectedId, setSelectedId] = useState("q1");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    return ITEMS.filter((item) => {
      if (tab === "queue" && item.status !== "queue") return false;
      if (tab === "live" && item.status !== "live") return false;
      if (tab === "wait" && item.status !== "wait") return false;
      if (tab === "failed" && item.status !== "failed") return false;
      if (tab === "done") return false;
      if (!query.trim()) return true;
      const hay = `${item.title} ${item.tags}`.toLowerCase();
      return hay.includes(query.trim().toLowerCase());
    });
  }, [tab, query]);

  const selected = ITEMS.find((i) => i.id === selectedId) ?? ITEMS[0];

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Publish Mode"
      searchPlaceholder="Search media, content, campaigns, or ask Leviathan..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.queue} title="ALGEMENE PUBLICATIE WACHTRIJ" imageOnly />

        <section className="lv-mr-kpi-row">
          <article className="lv-mr-kpi is-cyan">
            <div className="lbl">In de wachtrij (vandaag)</div>
            <div className="val">42</div>
            <div className="sub">
              <span className="delta">↑ +12%</span>
              <Spark points={[12, 16, 14, 20, 24, 22, 30, 34]} />
            </div>
          </article>
          <article className="lv-mr-kpi is-green">
            <div className="lbl">Nu aan het publiceren</div>
            <div className="val">3</div>
            <div className="sub">
              <Pill tone="cyan">● LIVE</Pill>
              <Spark points={[8, 18, 10, 22, 14, 26, 16, 28]} color="#4ade80" />
            </div>
          </article>
          <article className="lv-mr-kpi is-gold">
            <div className="lbl">Wachten op goedkeuring</div>
            <div className="val">7</div>
            <div className="sub">
              <span className="delta">↑ +2</span>
              <Spark points={[10, 12, 11, 14, 16, 15, 18, 20]} color="#f0c875" />
            </div>
          </article>
          <article className="lv-mr-kpi is-red">
            <div className="lbl">Mislukt</div>
            <div className="val">2</div>
            <div className="sub">
              <span className="lv-mr-bad">↑ +1</span>
              <Spark points={[4, 6, 5, 8, 7, 10, 9, 12]} color="#f87171" />
            </div>
          </article>
          <aside className="lv-mr-quote-card">
            “Great content finds its audience. We just make it inevitable.” — LEVIATHAN
          </aside>
        </section>

        <Panel>
          <div className="lv-mr-tabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                className={`lv-mr-tab${tab === t.id ? " is-active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label} ({t.count})
              </button>
            ))}
          </div>

          <div className="lv-mr-toolbar">
            <select className="lv-mr-select" defaultValue="all" aria-label="Platform">
              <option value="all">Alle platforms</option>
              <option>YouTube</option>
              <option>TikTok</option>
              <option>Instagram</option>
              <option>Facebook</option>
            </select>
            <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("YouTube filter")}>
              YT 14
            </button>
            <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("TikTok filter")}>
              TT 12
            </button>
            <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("Instagram filter")}>
              IG 16
            </button>
            <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("Facebook filter")}>
              FB 12
            </button>
            <input
              className="lv-mr-input"
              style={{ minWidth: 220, flex: 1 }}
              placeholder="Zoek in publicatie wachtrij..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button type="button" className="lv-mr-btn" onClick={() => toast("Goedkeuren")}>
              Goedkeuren
            </button>
            <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Publiceren nu")}>
              Publiceren nu
            </button>
            <button type="button" className="lv-mr-btn" onClick={() => toast("Uitstellen")}>
              Uitstellen
            </button>
            <select className="lv-mr-select" defaultValue="time" aria-label="Sorteren">
              <option value="time">Sorteer op: Publicatietijd (asc)</option>
              <option value="prio">Prioriteit</option>
              <option value="status">Status</option>
            </select>
          </div>
        </Panel>

        <section className="lv-mr-split">
          <Panel title={`Wachtrij · ${filtered.length} items`}>
            <div className="lv-mq-table-wrap">
              <table className="lv-mq-table">
                <thead>
                  <tr>
                    <th />
                    <th>Preview</th>
                    <th>Titel / Beschrijving</th>
                    <th>Platforms</th>
                    <th>Planning</th>
                    <th>Status</th>
                    <th>Prioriteit</th>
                    <th>Assets</th>
                    <th>Retry</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((item) => (
                    <tr
                      key={item.id}
                      className={item.id === selected.id ? "is-active" : undefined}
                      onClick={() => setSelectedId(item.id)}
                      style={{ cursor: "pointer" }}
                    >
                      <td>
                        <input type="checkbox" aria-label={`Selecteer ${item.title}`} onClick={(e) => e.stopPropagation()} />
                      </td>
                      <td>
                        <div className="lv-mq-thumb">
                          <img src={item.thumb} alt="" />
                          <span className="dur">{item.duration}</span>
                        </div>
                      </td>
                      <td>
                        <div className="lv-mq-title">{item.title}</div>
                        <div className="lv-mq-tags">{item.tags}</div>
                      </td>
                      <td>
                        <div className="lv-mr-plat-row">
                          {item.platforms.map((p) => (
                            <PlatformGlyph key={p} platform={p} />
                          ))}
                        </div>
                      </td>
                      <td>{item.when}</td>
                      <td>
                        <Pill tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status]}</Pill>
                      </td>
                      <td>
                        <Pill tone={item.priority === "Hoog" ? "red" : item.priority === "Laag" ? "blue" : "cyan"}>
                          {item.priority}
                        </Pill>
                      </td>
                      <td>{item.assets}</td>
                      <td>{item.retries ? <span className="lv-mr-bad">{item.retries}</span> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel
            title="DETAILS"
            action={
              <div className="lv-mr-tabs" style={{ border: 0 }}>
                <button type="button" className="lv-mr-tab is-active">
                  DETAILS
                </button>
                <button type="button" className="lv-mr-tab" onClick={() => toast("Assets")}>
                  ASSETS (3)
                </button>
                <button type="button" className="lv-mr-tab" onClick={() => toast("Geschiedenis")}>
                  GESCHIEDENIS
                </button>
              </div>
            }
          >
            <div className="lv-mq-detail-media">
              <img src={mediaPageArt.queueDetail} alt="" />
              <div className="overlay">DISCIPLINE CHANGES EVERYTHING</div>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
              <strong style={{ color: "#f0ebe3" }}>{selected.title}</strong>
              <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("Bewerken")}>
                Bewerken
              </button>
            </div>
            <p className="lv-mr-muted" style={{ margin: "6px 0 0", fontSize: 12, lineHeight: 1.45 }}>
              Discipline is de brug tussen waar je nu bent en waar je wilt zijn. Geen excuses. Alleen actie.{" "}
              <span style={{ color: "#5b9fd4" }}>{selected.tags}</span>
            </p>
            <div className="lv-mq-meta">
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Platforms</span>
                <div className="lv-mr-plat-row">
                  {selected.platforms.map((p) => (
                    <PlatformGlyph key={p} platform={p} />
                  ))}
                </div>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Geplande publicatie</span>
                <strong>{selected.when}</strong>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Status</span>
                <Pill tone={STATUS_TONE[selected.status]}>{STATUS_LABEL[selected.status]}</Pill>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Goedkeuring</span>
                <span>Goedgekeurd door Alex · 14:12</span>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Prioriteit</span>
                <Pill tone={selected.priority === "Hoog" ? "red" : "cyan"}>{selected.priority}</Pill>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Assets</span>
                <span className="lv-mr-good">{selected.assets} verwerkt</span>
              </div>
              <div className="lv-mq-meta-row">
                <span className="lv-mr-muted">Auto-retry</span>
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="checkbox" defaultChecked /> Max. 3 pogingen
                </label>
              </div>
            </div>
            <div className="lv-mq-actions">
              <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Publiceren nu")}>
                ▶ Publiceren nu
              </button>
              <div className="lv-mq-actions-row">
                <button type="button" className="lv-mr-btn" style={{ flex: 1 }} onClick={() => toast("Uitstellen")}>
                  Uitstellen
                </button>
                <button type="button" className="lv-mr-btn" style={{ flex: 1 }} onClick={() => toast("Dupliceren")}>
                  Dupliceren
                </button>
              </div>
            </div>
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
