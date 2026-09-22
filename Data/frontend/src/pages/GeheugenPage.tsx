import { useState } from "react";
import { onderzoekHeroes } from "../assets/onderzoekKennisAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { OkBars, OkGauge, OkHero, OkPanel, OkProgress, OkSpark } from "./onderzoek/ok-shared";

const TABS = [
  "Overview",
  "Ingestion",
  "Memory Graph",
  "Recall",
  "Organization",
  "Retention",
  "Settings",
] as const;

const TRACE = [
  { text: "Project scope besproken voor Atlas platform", when: "12m ago", tags: ["Episodisch", "Projecten", "Atlas"] },
  { text: "Voorkeur: korte antwoorden met bronnen", when: "34m ago", tags: ["Semantisch", "Voorkeuren"] },
  { text: "RAG evaluatie thresholds vastgelegd", when: "1u ago", tags: ["Procedureel", "RAG"] },
  { text: "Meeting notes: training data governance", when: "2u ago", tags: ["Episodisch", "Governance"] },
  { text: "Architectuur principe: EXTERNAL-FIRST workers", when: "5u ago", tags: ["Semantisch", "Architectuur"] },
] as const;

const INGEST = [
  { name: "research_notes_atlas.md", size: "184 KB", status: "Processing", tone: "gold" as const },
  { name: "session_export_0917.json", size: "2.1 MB", status: "Queued", tone: "cyan" as const },
  { name: "policy_brief_eu.pdf", size: "6.4 MB", status: "Queued", tone: "cyan" as const },
] as const;

const PINS = [
  { key: "Alt+1", title: "LEVIATHAN missie", meta: "Kernidentiteit" },
  { key: "Alt+2", title: "Architectuur principes", meta: "Platform" },
  { key: "Alt+3", title: "Atlas project scope", meta: "Actief" },
  { key: "Alt+4", title: "RAG quality bar", meta: "Evaluatie" },
] as const;

const TOPICS = [
  { name: "AI/LLM", pct: 28 },
  { name: "RAG", pct: 17 },
  { name: "Projecten", pct: 14 },
  { name: "Architectuur", pct: 11 },
] as const;

const GROWTH = [40, 42, 45, 48, 52, 55, 58, 61, 64, 68, 72, 78];
const SEARCHES = [18, 24, 22, 30, 28, 36, 40];

export function GeheugenPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [mode, setMode] = useState<"semantisch" | "hybride" | "exact">("hybride");
  const [query, setQuery] = useState("");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Search memories, knowledge, research, agents..."
      systemItems={["SYSTEMS ONLINE", "LLM", "NEURAL", "MEMORY", "TOOLS"]}
      layout="wide"
      pageClass="lv-app--onderzoek"
    >
      <main className="lv-main lv-ok-main">
        <OkHero
          title="GEHEUGEN"
          kicker="VASTLEGGEN. BEGRIJPEN. TOEPASSEN. EVOLUEREN."
          quote="Kennis is wat we onthouden. Wijsheid is wat we ermee doen."
          image={onderzoekHeroes.geheugen}
        />

        <section className="lv-ok-actions" aria-label="Geheugen tabs">
          {TABS.map((item) => (
            <button
              key={item}
              type="button"
              className={`lv-ok-action${tab === item ? " is-active" : ""}`}
              onClick={() => {
                setTab(item);
                toast(item);
              }}
            >
              <strong>{item}</strong>
              <small>{item === "Overview" ? "Memory health & traces" : "Module"}</small>
            </button>
          ))}
        </section>

        <OkPanel>
          <div className="lv-gh-health">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <OkGauge value={92} label="Health" size={110} />
              <div>
                <strong style={{ color: "var(--lv-gold-pale)" }}>Memory Systems Optimal</strong>
                <p className="lv-ok-muted" style={{ margin: "4px 0 0" }}>
                  All systems operational.
                </p>
              </div>
            </div>
            <div className="lv-gh-stats">
              <div className="lv-gh-stat">
                <strong>1.2M</strong>
                <small>Total Memories</small>
              </div>
              <div className="lv-gh-stat">
                <strong>98%</strong>
                <small>Integrity Score</small>
              </div>
              <div className="lv-gh-stat">
                <strong>12ms</strong>
                <small>Avg. Recall Time</small>
              </div>
              <div className="lv-gh-stat">
                <strong>99.7%</strong>
                <small>Availability</small>
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <OkSpark points={GROWTH} width={140} height={40} />
              <div className="lv-ok-kpi-meta">+12% Growth (30d)</div>
            </div>
          </div>
        </OkPanel>

        <section className="lv-gh-mid">
          <div className="lv-gh-types">
            <article className="lv-gh-type">
              <strong>Episodisch Geheugen</strong>
              <em>482K</em>
              <small>Events & sessies</small>
            </article>
            <article className="lv-gh-type">
              <strong>Semantisch Geheugen</strong>
              <em>612K</em>
              <small>Feiten & kennis</small>
            </article>
            <article className="lv-gh-type">
              <strong>Procedureel Geheugen</strong>
              <em>128K</em>
              <small>Skills & patronen</small>
            </article>
          </div>

          <OkPanel title="Recente Memory Traces">
            <ul className="lv-ok-list">
              {TRACE.map((item) => (
                <li key={item.text}>
                  <button type="button" onClick={() => toast(item.text)}>
                    <span className="lv-ok-list-copy">
                      <strong>{item.text}</strong>
                      <small>{item.when}</small>
                      <span className="lv-ok-chip-row" style={{ marginTop: 4 }}>
                        {item.tags.map((tag) => (
                          <span key={tag} className="lv-ok-tag">
                            {tag}
                          </span>
                        ))}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </OkPanel>

          <OkPanel title="Actieve Context">
            <ul className="lv-ok-check">
              <li>
                <span>Huidige sessie</span>
                <span>live</span>
              </li>
              <li>
                <span>Actief project</span>
                <span>LEVIATHAN Platform</span>
              </li>
              <li>
                <span>Gebruiker intentie</span>
                <span>Research synthesis</span>
              </li>
              <li>
                <span>Relevante thema's</span>
                <span>RAG · Atlas · Policy</span>
              </li>
            </ul>
            <p className="lv-ok-muted" style={{ marginBottom: 4 }}>
              Context venster · 12/32
            </p>
            <OkProgress value={(12 / 32) * 100} />
          </OkPanel>
        </section>

        <section className="lv-gh-lower">
          <OkPanel title="Memory Ingestion Queue">
            <ul className="lv-ok-list">
              {INGEST.map((item) => (
                <li key={item.name} className="lv-ok-list-row">
                  <span className="lv-ok-list-copy">
                    <strong>{item.name}</strong>
                    <small>{item.size}</small>
                  </span>
                  <span className={`lv-ok-pill is-${item.tone}`}>{item.status}</span>
                </li>
              ))}
            </ul>
          </OkPanel>

          <OkPanel title="Context Recall">
            <input
              className="lv-ok-input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Zoek in je geheugen..."
            />
            <div className="lv-ok-chip-row" style={{ margin: "8px 0" }}>
              {(["semantisch", "hybride", "exact"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`lv-ok-chip${mode === item ? " is-active" : ""}`}
                  onClick={() => setMode(item)}
                >
                  {item[0].toUpperCase() + item.slice(1)}
                </button>
              ))}
            </div>
            <div className="lv-ds-filters">
              <select className="lv-ok-select" defaultValue="relevant">
                <option value="relevant">Relevante</option>
                <option value="recent">Recent</option>
                <option value="pinned">Vastgezet</option>
              </select>
              <button className="lv-ok-btn is-gold" type="button" onClick={() => toast(`Recall: ${query || "…"}`)}>
                Recall
              </button>
            </div>
          </OkPanel>

          <OkPanel title="Memory Tiers">
            <div className="lv-gh-tier">
              <span>Hot (Active)</span>
              <OkProgress value={18} tone="red" />
              <span className="lv-ok-count">124K</span>
            </div>
            <div className="lv-gh-tier">
              <span>Warm (Recent)</span>
              <OkProgress value={42} />
              <span className="lv-ok-count">412K</span>
            </div>
            <div className="lv-gh-tier">
              <span>Cold (Archive)</span>
              <OkProgress value={70} tone="muted" />
              <span className="lv-ok-count">664K</span>
            </div>
          </OkPanel>

          <OkPanel title="Memory Integrity">
            <ul className="lv-ok-check">
              <li>
                <span>Data consistency</span>
                <span>99.8%</span>
              </li>
              <li>
                <span>Embedding integrity</span>
                <span>Healthy</span>
              </li>
              <li>
                <span>Index freshness</span>
                <span>Healthy</span>
              </li>
              <li>
                <span>Replica sync</span>
                <span>Healthy</span>
              </li>
              <li>
                <span>Retention policy</span>
                <span>Healthy</span>
              </li>
            </ul>
            <button className="lv-ok-btn" type="button" style={{ width: "100%", marginTop: 8 }} onClick={() => toast("Integrity check")}>
              Run Integrity Check
            </button>
          </OkPanel>
        </section>

        <section className="lv-gh-bottom">
          <OkPanel title="Vastgezette Herinneringen">
            <div className="lv-gh-pins">
              {PINS.map((pin) => (
                <button key={pin.key} type="button" className="lv-gh-pin" onClick={() => toast(pin.title)}>
                  <kbd>{pin.key}</kbd>
                  <strong>{pin.title}</strong>
                  <small>{pin.meta}</small>
                </button>
              ))}
            </div>
          </OkPanel>

          <OkPanel title="Recall Analytics (7D)">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div className="lv-ok-muted">Searches</div>
                <strong style={{ fontFamily: "var(--lv-font-display)", fontSize: 22 }}>1,842</strong>
                <OkBars values={SEARCHES} height={48} />
              </div>
              <div>
                <div className="lv-ok-muted">Hit Rate</div>
                <strong style={{ fontFamily: "var(--lv-font-display)", fontSize: 22 }}>94%</strong>
                <div className="lv-ok-muted" style={{ marginTop: 8 }}>
                  Avg. Latency 12ms
                </div>
              </div>
            </div>
          </OkPanel>

          <OkPanel title="Top Topics">
            <ol style={{ margin: 0, paddingLeft: 18 }}>
              {TOPICS.map((topic, index) => (
                <li key={topic.name} style={{ marginBottom: 6, fontSize: 11, color: "var(--lv-text-secondary)" }}>
                  <strong style={{ color: "var(--lv-text)" }}>
                    {index + 1}. {topic.name}
                  </strong>{" "}
                  <span className="lv-ok-count">{topic.pct}%</span>
                </li>
              ))}
            </ol>
          </OkPanel>
        </section>
      </main>
    </AppShell>
  );
}
