import { useMemo, useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../assets/mediaPagesAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { BarRow, Donut, PageHero, Panel, Pill } from "./media/mr-shared";

type EvType = "Web" | "Files" | "Images" | "Code" | "Reports" | "Logs" | "Conversations";
type EvStatus = "Verified" | "Pending" | "Flagged" | "Review";

type EvidenceItem = {
  id: string;
  source: string;
  type: EvType;
  status: EvStatus;
  timestamp: string;
  confidence: number;
  title: string;
  hashes: { sha256: string; sha1: string; md5: string };
  tags: string[];
};

const TYPE_CHIPS = ["All", "Web", "Files", "Images", "Code", "Reports", "Logs", "Conversations"] as const;

const GROWTH = [28, 36, 32, 44, 52, 48, 61, 70, 66, 78, 84, 92];

const ITEMS: EvidenceItem[] = [
  {
    id: "EV-2841",
    source: "reuters.com",
    type: "Web",
    status: "Verified",
    timestamp: "2026-09-22 14:12",
    confidence: 96,
    title: "Macro wire — funding compression",
    hashes: {
      sha256: "a3f1…9c2e8b71",
      sha1: "7b91…c04d",
      md5: "e2a1…19f0",
    },
    tags: ["markets", "liquidity"],
  },
  {
    id: "EV-2838",
    source: "vault/reports/q3.pdf",
    type: "Reports",
    status: "Verified",
    timestamp: "2026-09-22 13:48",
    confidence: 91,
    title: "Q3 retention cohort brief",
    hashes: {
      sha256: "91cd…44aa012f",
      sha1: "c881…2fe1",
      md5: "0bb4…77ac",
    },
    tags: ["media", "retention"],
  },
  {
    id: "EV-2834",
    source: "sat-orbit/tile-12",
    type: "Images",
    status: "Pending",
    timestamp: "2026-09-22 12:05",
    confidence: 74,
    title: "Satellite overlay — coastal grid",
    hashes: {
      sha256: "55e0…ab19d3c2",
      sha1: "119a…88ef",
      md5: "9f3c…0012",
    },
    tags: ["geo", "imagery"],
  },
  {
    id: "EV-2829",
    source: "github.com/lev/hades",
    type: "Code",
    status: "Verified",
    timestamp: "2026-09-22 11:22",
    confidence: 88,
    title: "Chunker provenance patch",
    hashes: {
      sha256: "d014…6e91bb40",
      sha1: "aa12…9c01",
      md5: "71fe…cc09",
    },
    tags: ["code", "ingestion"],
  },
  {
    id: "EV-2822",
    source: "agent/chat-4921",
    type: "Conversations",
    status: "Review",
    timestamp: "2026-09-21 22:40",
    confidence: 69,
    title: "Research session transcript",
    hashes: {
      sha256: "bb70…1188afe3",
      sha1: "33cd…a190",
      md5: "c4d2…55e8",
    },
    tags: ["chat", "research"],
  },
  {
    id: "EV-2817",
    source: "runtime/access.log",
    type: "Logs",
    status: "Flagged",
    timestamp: "2026-09-21 19:03",
    confidence: 58,
    title: "Anomalous vault read burst",
    hashes: {
      sha256: "0fe2…9911ccaa",
      sha1: "ee09…4412",
      md5: "a190…77bd",
    },
    tags: ["security", "logs"],
  },
  {
    id: "EV-2811",
    source: "datasets/creator_vel.parquet",
    type: "Files",
    status: "Verified",
    timestamp: "2026-09-21 16:18",
    confidence: 93,
    title: "Creator velocity dataset slice",
    hashes: {
      sha256: "88a1…c0ff2199",
      sha1: "5d10…abce",
      md5: "12ff…90aa",
    },
    tags: ["datasets", "creators"],
  },
];

const STATUS_TONE: Record<EvStatus, "green" | "gold" | "red" | "cyan"> = {
  Verified: "green",
  Pending: "gold",
  Flagged: "red",
  Review: "cyan",
};

const CATEGORIES = [
  { label: "Web", value: 34, color: "#22c9d6" },
  { label: "Files", value: 22, color: "#60a5fa" },
  { label: "Images", value: 14, color: "#f0c875" },
  { label: "Code", value: 11, color: "#4ade80" },
  { label: "Reports", value: 9, color: "#c084fc" },
  { label: "Logs", value: 6, color: "#f87171" },
  { label: "Conversations", value: 4, color: "#94a3b8" },
];

const REVIEW_QUEUE = [
  { id: "EV-2834", reason: "Imagery OCR incomplete", due: "Today" },
  { id: "EV-2822", reason: "Needs human provenance check", due: "Today" },
  { id: "EV-2817", reason: "Flagged access pattern", due: "Overdue" },
  { id: "EV-2804", reason: "Hash mismatch vs mirror", due: "Tomorrow" },
];

const EVENTS = [
  { t: "14:12", text: "EV-2841 verified · SHA-256 matched" },
  { t: "13:48", text: "Report ingested · 12 chunks" },
  { t: "12:05", text: "Image tile queued for review" },
  { t: "11:22", text: "Code evidence linked to PR #412" },
  { t: "09:40", text: "Vault integrity sweep complete" },
];

export function EvidenceVaultPage() {
  const toast = useAppToast();
  const [chip, setChip] = useState<(typeof TYPE_CHIPS)[number]>("All");
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState("7d");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(ITEMS[0].id);

  const filtered = useMemo(() => {
    return ITEMS.filter((item) => {
      if (chip !== "All" && item.type !== chip) return false;
      if (statusFilter !== "all" && item.status.toLowerCase() !== statusFilter) return false;
      if (!query.trim()) return true;
      const hay = `${item.id} ${item.source} ${item.title} ${item.tags.join(" ")}`.toLowerCase();
      return hay.includes(query.trim().toLowerCase());
    });
  }, [chip, statusFilter, query]);

  const selected = ITEMS.find((i) => i.id === selectedId) ?? ITEMS[0];

  const copyHash = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      /* clipboard may be unavailable in some environments */
    }
    toast(`${label} copied`);
  };

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Evidence Mode"
      searchPlaceholder="Search evidence, sources, content, hash, or tags..."
      systemItems={["SYSTEMS OPERATIONAL", "LLM", "NEURAL", "MEMORY", "TOOLS"]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.evidence} title="EVIDENCE VAULT" imageOnly />

        <Panel>
          <div className="lv-mr-toolbar">
            <input
              className="lv-mr-input"
              style={{ flex: 1, minWidth: 220 }}
              placeholder="Search evidence, sources, hash, or tags…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search evidence"
            />
            <select
              className="lv-mr-select"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              aria-label="Date range"
            >
              <option value="24h">Last 24h</option>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="all">All time</option>
            </select>
            <select
              className="lv-mr-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label="Status filter"
            >
              <option value="all">All statuses</option>
              <option value="verified">Verified</option>
              <option value="pending">Pending</option>
              <option value="flagged">Flagged</option>
              <option value="review">Review</option>
            </select>
          </div>
          <div className="lv-mr-tabs" role="tablist" aria-label="Evidence type">
            {TYPE_CHIPS.map((c) => (
              <button
                key={c}
                type="button"
                role="tab"
                className={`lv-mr-tab${chip === c ? " is-active" : ""}`}
                onClick={() => setChip(c)}
              >
                {c}
              </button>
            ))}
          </div>
        </Panel>

        <section className="lv-ev-kpis" aria-label="Evidence KPIs">
          <article className="lv-mr-kpi is-cyan">
            <div className="lbl">Evidence Items</div>
            <div className="val">2,847</div>
            <div className="sub">
              <span className="delta">↑ +128</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-green">
            <div className="lbl">Verification</div>
            <div className="val">92.4%</div>
            <div className="sub">
              <Pill tone="green">Healthy</Pill>
            </div>
          </article>
          <article className="lv-mr-kpi is-gold">
            <div className="lbl">Pending</div>
            <div className="val">7</div>
            <div className="sub">
              <span className="lv-mr-muted">in review</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-red">
            <div className="lbl">Flagged</div>
            <div className="val">3</div>
            <div className="sub">
              <span className="lv-mr-bad">needs attention</span>
            </div>
          </article>
          <article className="lv-mr-kpi is-gold">
            <div className="lbl">Evidence Growth</div>
            <div className="lv-ev-growth" aria-hidden="true">
              {GROWTH.map((h, i) => (
                <span key={i} style={{ height: `${h}%` }} />
              ))}
            </div>
          </article>
        </section>

        <section className="lv-mr-split">
          <Panel title={`Evidence Items · ${filtered.length}`}>
            <div style={{ overflow: "auto" }}>
              <table className="lv-ev-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Source</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Timestamp</th>
                    <th>Confidence</th>
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
                        <strong>{item.id}</strong>
                      </td>
                      <td>{item.source}</td>
                      <td>
                        <Pill tone="muted">{item.type}</Pill>
                      </td>
                      <td>
                        <Pill tone={STATUS_TONE[item.status]}>{item.status}</Pill>
                      </td>
                      <td className="lv-mr-muted">{item.timestamp}</td>
                      <td>
                        <div className="lv-ev-conf">
                          <div className="lv-mr-bar">
                            <span
                              style={{
                                width: `${item.confidence}%`,
                                background:
                                  item.confidence >= 90
                                    ? "#4ade80"
                                    : item.confidence >= 70
                                      ? "#22c9d6"
                                      : "#f0c875",
                              }}
                            />
                          </div>
                          <span>{item.confidence}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel
            title="Evidence Details"
            action={<Pill tone={STATUS_TONE[selected.status]}>{selected.status}</Pill>}
          >
            <div className="lv-ev-preview">
              <img src={mediaPageArt.evidenceSat} alt="" />
            </div>
            <strong style={{ color: "#f0ebe3", marginTop: 8 }}>{selected.title}</strong>
            <div className="lv-mr-muted" style={{ fontSize: 12, marginTop: 4 }}>
              {selected.id} · {selected.source} · {selected.type}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              {selected.tags.map((tag) => (
                <Pill key={tag} tone="cyan">
                  #{tag}
                </Pill>
              ))}
            </div>

            <div className="lv-mr-panel-title" style={{ marginTop: 12 }}>
              Metadata
            </div>
            <div style={{ fontSize: 12, display: "grid", gap: 6 }}>
              <div className="lv-rs-active-item">
                <span className="lv-mr-muted">Captured</span>
                <span>{selected.timestamp}</span>
              </div>
              <div className="lv-rs-active-item">
                <span className="lv-mr-muted">Confidence</span>
                <span>{selected.confidence}%</span>
              </div>
              <div className="lv-rs-active-item">
                <span className="lv-mr-muted">Date filter</span>
                <span>{dateFilter}</span>
              </div>
            </div>

            <div className="lv-mr-panel-title" style={{ marginTop: 12 }}>
              Hashes
            </div>
            {(
              [
                ["SHA-256", selected.hashes.sha256],
                ["SHA-1", selected.hashes.sha1],
                ["MD5", selected.hashes.md5],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="lv-ev-hash">
                <span>
                  <span className="lv-mr-muted">{label}</span> {value}
                </span>
                <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => copyHash(label, value)}>
                  Copy
                </button>
              </div>
            ))}

            <div className="lv-mr-toolbar" style={{ marginTop: 10 }}>
              <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Marked verified")}>
                Verify
              </button>
              <button type="button" className="lv-mr-btn" onClick={() => toast("Opened in vault")}>
                Open
              </button>
              <button type="button" className="lv-mr-btn" onClick={() => toast("Exported evidence pack")}>
                Export
              </button>
              <button type="button" className="lv-mr-btn" onClick={() => toast("Flagged for review")}>
                Flag
              </button>
            </div>
          </Panel>
        </section>

        <section className="lv-ev-bottom">
          <Panel title="Categories">
            {CATEGORIES.map((cat) => (
              <div key={cat.label} className="lv-ev-cat-row">
                <span>{cat.label}</span>
                <div className="lv-mr-bar">
                  <span style={{ width: `${cat.value * 2.5}%`, background: cat.color }} />
                </div>
                <strong>{cat.value}%</strong>
              </div>
            ))}
          </Panel>

          <Panel title="Credibility">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <Donut
                slices={[
                  { value: 72, color: "#4ade80" },
                  { value: 18, color: "#f0c875" },
                  { value: 7, color: "#22c9d6" },
                  { value: 3, color: "#f87171" },
                ]}
                center="92%"
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11 }}>
                <BarRow label="Verified" value={72} color="#4ade80" />
                <BarRow label="Pending" value={18} color="#f0c875" />
                <BarRow label="Review" value={7} color="#22c9d6" />
                <BarRow label="Flagged" value={3} color="#f87171" />
              </div>
            </div>
          </Panel>

          <Panel title="Review Queue">
            {REVIEW_QUEUE.map((row) => (
              <div key={row.id} className="lv-rs-active-item">
                <span>
                  <strong>{row.id}</strong>
                  <span className="lv-mr-muted"> · {row.reason}</span>
                </span>
                <Pill tone={row.due === "Overdue" ? "red" : "gold"}>{row.due}</Pill>
              </div>
            ))}
          </Panel>

          <Panel title="Recent Events">
            <ol className="lv-ev-timeline">
              {EVENTS.map((ev) => (
                <li key={ev.t + ev.text}>
                  <time>{ev.t}</time>
                  <span>{ev.text}</span>
                </li>
              ))}
            </ol>
          </Panel>
        </section>

        <blockquote className="lv-rs-quote">
          <img src={mediaPageArt.evidenceBust} alt="" />
          <span>“Provenance is the product. If we cannot verify it, we do not claim it.”</span>
        </blockquote>
      </main>
    </AppShell>
  );
}
