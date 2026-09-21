/**
 * Generate ALL FinalBeta pages for the v2 mockup.
 * Source of truth for page IDs: components/hades/finalbeta/routes.ts FINALBETA_PAGES
 * Run: node docs/mockups/finalbeta-v2/_generate-all-pages.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pagesDir = path.join(__dirname, "pages");
fs.mkdirSync(pagesDir, { recursive: true });

const HOOFD = [
  { id: "ai", label: "Hades AI", desc: "Jouw persoonlijke assistent", href: "dashboard.html", icon: "cube" },
  { id: "llm", label: "LLM", desc: "Train. Tune. Own.", href: "models.html", icon: "chip" },
  { id: "media", label: "Media Control", desc: "Audio, video & live", href: "media.html", icon: "play" },
  { id: "trading", label: "TradingCenter", desc: "Marktdata & strategieën", href: "trading.html", icon: "chart" },
  { id: "onderzoek", label: "Onderzoek & kennis", desc: "Analyseer. Ontdek. Bouw.", href: "research.html", icon: "search" },
  { id: "plugin", label: "Plugin & Runtime", desc: "Breid uit. Integreer. Automatiseer.", href: "performance.html", icon: "wrench" },
];

const SECTIONS = {
  ai: {
    title: "Hades AI",
    sub: "Persoonlijke assistent",
    items: [
      { id: "dashboard", label: "Dashboard", desc: "Omniroute & status" },
      { id: "chat", label: "Chatten", desc: "Gesprekken en taken" },
      { id: "coding", label: "Coding", desc: "Patches & sandbox" },
      { id: "mission-control", label: "Mission Control", desc: "Missies & goedkeuring" },
      { id: "tasks", label: "Taken", desc: "Work Runtime" },
    ],
  },
  llm: {
    title: "LLM Studio",
    sub: "Modellen & training",
    items: [
      { id: "models", label: "Modellen", desc: "Runtime & providers" },
      { id: "model-training", label: "Model training", desc: "Fine-tune & ATME" },
      { id: "agents", label: "Agents", desc: "Specialisten" },
    ],
  },
  media: {
    title: "Media Studio",
    sub: "Audio, video & live",
    items: [
      { id: "media", label: "Overzicht", desc: "Projecten & productie" },
      { id: "youtube", label: "Youtube", desc: "Kanaal & shorts" },
      { id: "tiktok", label: "Tiktok", desc: "Short-form" },
      { id: "instagram", label: "Instagram", desc: "Reels & posts" },
      { id: "facebook", label: "Facebook", desc: "Posts & live" },
    ],
  },
  trading: {
    title: "TradingCenter",
    sub: "Marktdata & strategieën",
    items: [{ id: "trading", label: "Markets", desc: "Charts & signals" }],
  },
  onderzoek: {
    title: "Onderzoek",
    sub: "Analyseer. Ontdek. Bouw.",
    items: [
      { id: "research", label: "Research", desc: "Vragen & bronnen" },
      { id: "brain", label: "Brain", desc: "Dataset Brain" },
      { id: "memory", label: "Geheugen", desc: "Context & feiten" },
      { id: "knowledge", label: "Knowledge Library", desc: "Documenten" },
      { id: "evidence", label: "Evidence Vault", desc: "Bewijsstukken" },
      { id: "files", label: "Bestanden", desc: "Lokale files" },
    ],
  },
  plugin: {
    title: "Plugin & Runtime",
    sub: "Breid uit. Integreer.",
    items: [
      { id: "performance", label: "Performance", desc: "Health & metrics" },
      { id: "settings", label: "Instellingen", desc: "Voorkeuren" },
      { id: "tools", label: "Plugins", desc: ".HadesPlugin packages" },
      { id: "mcp", label: "MCP", desc: "Model Context Protocol" },
      { id: "workflows", label: "Workflows", desc: "Automations" },
      { id: "system", label: "Systeem", desc: "Diagnostics" },
    ],
  },
};

const PAGE_META = {
  dashboard: { title: "Dashboard", top: "ai", section: "ai" },
  chat: { title: "Chatten", top: "ai", section: "ai" },
  coding: { title: "Coding", top: "ai", section: "ai" },
  "mission-control": { title: "Mission Control", top: "ai", section: "ai" },
  tasks: { title: "Taken", top: "ai", section: "ai" },
  models: { title: "Modellen", top: "llm", section: "llm" },
  "model-training": { title: "Model training", top: "llm", section: "llm" },
  agents: { title: "Agents", top: "llm", section: "llm" },
  media: { title: "Media dashboard", top: "media", section: "media" },
  youtube: { title: "Youtube", top: "media", section: "media" },
  tiktok: { title: "Tiktok", top: "media", section: "media" },
  instagram: { title: "Instagram", top: "media", section: "media" },
  facebook: { title: "Facebook", top: "media", section: "media" },
  trading: { title: "TradingCenter", top: "trading", section: "trading" },
  research: { title: "Research", top: "onderzoek", section: "onderzoek" },
  brain: { title: "Brain", top: "onderzoek", section: "onderzoek" },
  memory: { title: "Geheugen", top: "onderzoek", section: "onderzoek" },
  knowledge: { title: "Knowledge Library", top: "onderzoek", section: "onderzoek" },
  evidence: { title: "Evidence Vault", top: "onderzoek", section: "onderzoek" },
  files: { title: "Bestanden", top: "onderzoek", section: "onderzoek" },
  performance: { title: "Performance", top: "plugin", section: "plugin" },
  settings: { title: "Instellingen", top: "plugin", section: "plugin" },
  tools: { title: "Plugins", top: "plugin", section: "plugin" },
  mcp: { title: "MCP", top: "plugin", section: "plugin" },
  workflows: { title: "Workflows", top: "plugin", section: "plugin" },
  system: { title: "Systeem", top: "plugin", section: "plugin" },
};

const ICONS = {
  cube: `<svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>`,
  chip: `<svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/></svg>`,
  play: `<svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M10 9l5 3-5 3V9z"/></svg>`,
  chart: `<svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 17l5-5 4 4 8-9"/><path d="M14 7h6v6"/></svg>`,
  search: `<svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>`,
  wrench: `<svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`,
  side: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 8v8"/></svg>`,
};

function topnav(active) {
  return `<nav class="topnav" aria-label="Hoofdmenu">${HOOFD.map(
    (h) => `
        <a class="topnav-item${h.id === active ? " active" : ""}" href="${h.href}">
          ${ICONS[h.icon]}
          <span class="topnav-copy"><span class="topnav-label">${h.label}</span><span class="topnav-desc">${h.desc}</span></span>
        </a>`
  ).join("")}
      </nav>`;
}

function sidebar(sectionKey, activeId) {
  const s = SECTIONS[sectionKey];
  return `
          <div class="studio-card">
            <div class="studio-icon"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.2-2.5 5.5L15 17H9l-1.5-2.5C6.3 13.2 5 11.5 5 9a7 7 0 0 1 7-7z"/></svg></div>
            <div>
              <div class="studio-title">${s.title}</div>
              <div class="studio-sub">${s.sub}</div>
            </div>
          </div>
          <nav class="side-nav">${s.items
            .map(
              (i) => `
            <a class="side-item${i.id === activeId ? " active" : ""}" href="${i.id}.html">
              ${ICONS.side}
              <span class="side-copy"><span class="side-label">${i.label}</span><span class="side-desc">${i.desc}</span></span>
            </a>`
            )
            .join("")}
          </nav>
          <div class="sidebar-motto">Higher Intelligence<br />A Brighter Tomorrow</div>`;
}

function defaultInsp(title = "Context") {
  return `
      <aside class="inspector">
        <p class="quote">“Sovereign AI. Local power.<br />Infinite possibilities.”</p>
        <div style="margin-bottom:10px"><span class="badge-outline">ONTWERPVOORBEELD</span></div>
        <section class="insp-section">
          <h3 class="insp-title">${title}</h3>
          <div class="insp-card">
            <div class="detail-row"><span class="k">Status</span><span class="v green">● Online</span></div>
            <div class="detail-row"><span class="k">Host</span><span class="v">DESKTOP-HADES</span></div>
            <div class="detail-row"><span class="k">Modus</span><span class="v">Lokaal / Offline-first</span></div>
            <div class="detail-row"><span class="k">UI</span><span class="v">FINALBETA v2 mockup</span></div>
          </div>
        </section>
        <section class="insp-section">
          <h3 class="insp-title">Snelacties</h3>
          <div class="insp-card" style="display:flex;flex-direction:column;gap:8px">
            <button class="btn btn-sm btn-outline btn-block" type="button" data-toast="Demo">Refresh</button>
            <button class="btn btn-sm btn-gold btn-block" type="button" data-toast="Demo">Open Work Runtime</button>
          </div>
        </section>
      </aside>`;
}

function head(title, actions = "") {
  return `
        <div class="page-head">
          <div>
            <h1 class="page-title">${title}</h1>
            <p class="page-sub">${PAGE_SUB[title] || "HADES FINALBETA — lokale soevereine AI-werkruimte."}</p>
          </div>
          <div class="page-actions">${actions}</div>
        </div>`;
}

const PAGE_SUB = {
  Dashboard: "Omniroute-overzicht: status, actieve processen en snelle start.",
  Chatten: "Chat-first werkruimte met context, tools en lokale modellen.",
  Coding: "Patches voorstellen, reviewen en sandbox-verifiëren.",
  "Mission Control": "Bewaak lopende missies, goedkeuringen en uitvoeringsstatus.",
  Taken: "Work Runtime — taken plannen, uitvoeren en volgen.",
  Modellen: "Beheer lokale modellen en runtime-instellingen.",
  "Model training": "Train, evalueer en beheer lokale modelruns met ATME.",
  Agents: "Specialisten voor research, coding, planning en meer.",
  "Media dashboard": "Produceer audio, video en live content lokaal.",
  Youtube: "YouTube-kanaalproductie: scripts, shots en exports.",
  Tiktok: "Short-form content pipeline voor TikTok.",
  Instagram: "Reels en posts vanuit dezelfde Media Studio.",
  Facebook: "Posts, live en community-content.",
  TradingCenter: "Lokale marktdata, strategieën en PAPER-simulaties.",
  Research: "Structureer vragen, verzamel evidence en synthetiseer.",
  Brain: "Dataset Brain — kennisindex en retrieval.",
  Geheugen: "Persistente feiten, voorkeuren en sessiecontext.",
  "Knowledge Library": "Documenten, notities en gestructureerde kennis.",
  "Evidence Vault": "Bewijsstukken met herkomst en claims.",
  Bestanden: "Lokale file tree, preview en ingestie.",
  Performance: "Health, resources en runtime-metrics.",
  Instellingen: "Voorkeuren, policies en lokale configuratie.",
  Plugins: "Beheer .HadesPlugin packages en tool runtime.",
  MCP: "Model Context Protocol servers en tools.",
  Workflows: "Automations en flow-graphs.",
  Systeem: "Diagnostics, logs en systeemstatus.",
};

const btn = (label, gold = false) =>
  `<button class="btn ${gold ? "btn-gold" : "btn-outline"}" type="button" data-toast="Demo">${label}</button>`;

const CONTENTS = {
  dashboard: () => `
        ${head("Dashboard", btn("Nieuwe chat", true) + btn("Mission starten"))}
        <div class="stat-grid-4" style="margin-bottom:12px">
          <div class="card card-pad"><div class="muted" style="font-size:11px">LM Studio</div><div style="font-weight:700;margin-top:4px">Verbonden</div><div class="muted" style="font-size:11px">127.0.0.1:1234</div></div>
          <div class="card card-pad"><div class="muted" style="font-size:11px">Actief model</div><div style="font-weight:700;margin-top:4px">qwen3-14b</div><div class="muted" style="font-size:11px">74.8 tok/s</div></div>
          <div class="card card-pad"><div class="muted" style="font-size:11px">GPU</div><div style="font-weight:700;margin-top:4px">RTX 4090</div><div class="bar-row" style="margin-top:6px"><div class="bar"><span style="width:62%"></span></div><span class="bar-pct">62%</span></div></div>
          <div class="card card-pad"><div class="muted" style="font-size:11px">Actieve processen</div><div style="font-weight:700;margin-top:4px">3</div><div class="muted" style="font-size:11px">1 training · 2 tasks</div></div>
        </div>
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Omniroute</h2>
            <p class="section-sub">Wat wil je doen? HADES routeert naar de juiste werkruimte.</p>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px">
              ${[
                ["Chat", "chat.html"],
                ["Coding", "coding.html"],
                ["Research", "research.html"],
                ["Training", "model-training.html"],
                ["Media", "media.html"],
                ["Trading", "trading.html"],
              ]
                .map(
                  ([l, h]) =>
                    `<a class="btn btn-outline" href="${h}" style="justify-content:flex-start">${l}</a>`
                )
                .join("")}
            </div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Actieve processen</h2>
            <div class="list-row"><div class="grow"><strong>HADES-Llama-8B</strong><div class="muted" style="font-size:11px">Training · 24%</div></div><span class="tag gold">Running</span></div>
            <div class="list-row"><div class="grow"><strong>Nav UI patch review</strong><div class="muted" style="font-size:11px">Coding · wacht op accept</div></div><span class="tag warn">Blocked</span></div>
            <div class="list-row"><div class="grow"><strong>ATME evidence sweep</strong><div class="muted" style="font-size:11px">Research · 2 bronnen</div></div><span class="tag green">Running</span></div>
          </section>
        </div>`,

  chat: () => `
        ${head("Chatten", btn("+ Nieuw gesprek", true))}
        <div class="chat-layout">
          <section class="card" style="padding:10px;overflow:auto">
            <div class="search-bar" style="margin-bottom:10px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg><input placeholder="Gesprekken zoeken..." /></div>
            <div class="list-row" style="border-radius:6px;background:rgba(240,180,41,.08);border:1px solid rgba(240,180,41,.25)"><div class="grow"><strong>HADES BETA uitwerken</strong><div class="muted" style="font-size:10px">10:24</div></div></div>
            <div class="list-row"><div class="grow"><strong>Research samenvatten</strong><div class="muted" style="font-size:10px">09:12</div></div></div>
            <div class="list-row"><div class="grow"><strong>Plugin instellen</strong><div class="muted" style="font-size:10px">14 apr</div></div></div>
          </section>
          <section class="card chat-thread">
            <div style="padding:12px 14px;border-bottom:1px solid var(--border-soft);display:flex;justify-content:space-between;align-items:center">
              <div><div style="font-weight:650;font-size:15px">HADES BETA uitwerken</div><div class="muted" style="font-size:11px">3 berichten · Lokaal model · Adaptive</div></div>
              <span class="tag green">Live</span>
            </div>
            <div class="messages">
              <div class="bubble user">Werk de navigatie van HADES verder uit.</div>
              <div class="bubble">Ik groepeer de werkruimtes in <strong>Hades AI</strong>, <strong>LLM</strong>, <strong>Media</strong>, <strong>Trading</strong>, <strong>Onderzoek</strong> en <strong>Plugin &amp; Runtime</strong>. Chat blijft primary; Advanced consoles blijven bereikbaar.</div>
            </div>
            <div class="composer"><input type="text" placeholder="Stuur een bericht..." /><button class="btn btn-gold" type="button" data-toast="Verzonden">Verstuur</button></div>
          </section>
        </div>`,

  coding: () => `
        ${head("Coding", btn("Nieuwe taak", true) + btn("Open sandbox"))}
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Runs</h2>
            <div class="list-row" style="background:rgba(240,180,41,.08)"><div class="grow"><strong>Nav UI patch</strong><div class="muted" style="font-size:11px">routes.ts · wacht op accept</div></div><span class="tag gold">Review</span></div>
            <div class="list-row"><div class="grow"><strong>Training API types</strong><div class="muted" style="font-size:11px">voltooid</div></div><span class="tag green">Done</span></div>
            <div class="list-row"><div class="grow"><strong>Plugin loader fix</strong><div class="muted" style="font-size:11px">queued</div></div><span class="tag">Queued</span></div>
          </section>
          <section class="card" style="padding:0;overflow:hidden">
            <div style="padding:12px 14px;border-bottom:1px solid var(--border-soft);display:flex;justify-content:space-between;align-items:center">
              <strong>Patch — routes.ts</strong>
              <div style="display:flex;gap:6px">${btn("Reject")}${btn("Accept", true)}</div>
            </div>
            <div class="code-diff">
              <div class="code-pane"><div class="code-head">− oud</div>
                <div class="code-line del"><span class="ln">42</span><code>  home: "models",</code></div>
                <div class="code-line"><span class="ln">43</span><code>  submenu: [</code></div>
              </div>
              <div class="code-pane"><div class="code-head">+ nieuw</div>
                <div class="code-line add"><span class="ln">42</span><code>  home: "model-training",</code></div>
                <div class="code-line"><span class="ln">43</span><code>  submenu: [</code></div>
              </div>
            </div>
          </section>
        </div>`,

  "mission-control": () => `
        ${head("Mission Control", btn("Nieuwe missie", true))}
        <div class="stat-grid-3" style="margin-bottom:12px">
          <div class="card card-pad"><div class="muted">Actief</div><div style="font-size:22px;font-weight:700">2</div></div>
          <div class="card card-pad"><div class="muted">Wacht op goedkeuring</div><div style="font-size:22px;font-weight:700;color:var(--gold)">1</div></div>
          <div class="card card-pad"><div class="muted">Voltooid (24u)</div><div style="font-size:22px;font-weight:700;color:var(--success)">5</div></div>
        </div>
        <section class="card list-card">
          <div class="list-row"><div class="grow"><strong>Ship Training Control UI</strong><div class="muted" style="font-size:11px">Criteria: pixel parity · tests groen</div></div><span class="tag gold">Active</span>${btn("Open")}</div>
          <div class="list-row"><div class="grow"><strong>ATME benchmark gate</strong><div class="muted" style="font-size:11px">Wacht op accept score ≥ 9.0</div></div><span class="tag warn">Approval</span>${btn("Review")}</div>
          <div class="list-row"><div class="grow"><strong>Evidence vault ingest</strong><div class="muted" style="font-size:11px">14 docs · voltooid</div></div><span class="tag green">Done</span>${btn("Log")}</div>
        </section>`,

  tasks: () => `
        ${head("Taken", btn("+ Nieuwe taak", true))}
        <div class="tabs" data-tabs="tasks"><button class="tab active" type="button">Actief</button><button class="tab" type="button">Wachtrij</button><button class="tab" type="button">Archief</button></div>
        <div class="page-grid-2">
          <section class="card list-card">
            <div class="list-row"><div class="grow"><strong>Dataset Brain sync</strong><div class="muted" style="font-size:11px">running · 68%</div></div><span class="tag gold">Running</span></div>
            <div class="list-row"><div class="grow"><strong>Export training report</strong><div class="muted" style="font-size:11px">queued</div></div><span class="tag">Queued</span></div>
            <div class="list-row"><div class="grow"><strong>Cleanup temp artifacts</strong><div class="muted" style="font-size:11px">done</div></div><span class="tag green">Done</span></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Uitvoering — Dataset Brain sync</h2>
            <div class="timeline">
              <div class="timeline-step done"><div class="timeline-dot"></div><strong>Queued</strong><div class="muted" style="font-size:11px">14:20</div></div>
              <div class="timeline-step done"><div class="timeline-dot"></div><strong>Index rebuild</strong><div class="muted" style="font-size:11px">14:21</div></div>
              <div class="timeline-step doing"><div class="timeline-dot"></div><strong>Embedding pass</strong><div class="muted" style="font-size:11px">nu · 68%</div></div>
              <div class="timeline-step"><div class="timeline-dot"></div><strong>Verify + commit</strong></div>
            </div>
          </section>
        </div>`,

  models: () => `
        ${head("Modellen", btn("Modellen zoeken", true) + btn("Provider toevoegen"))}
        <div class="stat-grid-3" style="margin-bottom:12px">
          <div class="card card-pad"><div class="muted">LM Studio</div><div style="font-weight:700">Verbonden</div><div class="muted" style="font-size:11px">http://127.0.0.1:1234/v1</div></div>
          <div class="card card-pad"><div class="muted">Actief model</div><div style="font-weight:700">qwen3-14b-instruct</div><div class="muted" style="font-size:11px">32K context</div></div>
          <div class="card card-pad"><div class="muted">Doorvoer</div><div style="font-weight:700">74.8 tok/s</div><div class="muted" style="font-size:11px">Laatste generatie</div></div>
        </div>
        <section class="card" style="padding:0;overflow:hidden">
          <div style="padding:10px 12px;display:flex;gap:8px;border-bottom:1px solid var(--border-soft)">
            <div class="search-bar grow"><input placeholder="Zoek geïnstalleerde modellen..." /></div>
            <select class="control" style="width:140px"><option>Alle providers</option></select>
            <select class="control" style="width:120px"><option>Alle types</option></select>
          </div>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Model</th><th>Provider</th><th>Type</th><th>Context</th><th>Status</th></tr></thead>
            <tbody>
              <tr class="selected"><td><strong>qwen3-14b-instruct</strong></td><td>LM Studio</td><td>Chat</td><td>32K</td><td><span class="tag green">Geladen</span></td></tr>
              <tr><td><strong>dolphin-3.0-llama-3.1-8b</strong></td><td>LM Studio</td><td>Chat</td><td>16K</td><td><span class="tag">Beschikbaar</span></td></tr>
              <tr><td><strong>qwen2.5-coder-14b</strong></td><td>LM Studio</td><td>Code</td><td>32K</td><td><span class="tag">Beschikbaar</span></td></tr>
              <tr><td><strong>bge-m3</strong></td><td>Local embeddings</td><td>Embedding</td><td>8K</td><td><span class="tag green">Gereed</span></td></tr>
              <tr><td><strong>whisper-small</strong></td><td>Local audio</td><td>Speech</td><td>—</td><td><span class="tag warn">Niet geladen</span></td></tr>
            </tbody>
          </table></div>
        </section>
        <div class="page-grid-2" style="margin-top:12px">
          <section class="card card-pad"><h2 class="section-title">Routering</h2>
            <div class="kv"><span>Chat</span><span>qwen3-14b-instruct</span></div>
            <div class="kv"><span>Coding</span><span>qwen2.5-coder-14b</span></div>
            <div class="kv"><span>Embeddings</span><span>bge-m3</span></div>
          </section>
          <section class="card card-pad"><h2 class="section-title">Runtime</h2>
            <div class="kv"><span>GPU offload</span><span>100%</span></div>
            <div class="kv"><span>Context cache</span><span>Aan</span></div>
            <div class="kv"><span>Parallel requests</span><span>2</span></div>
          </section>
        </div>`,

  "model-training": () => `
        ${head("Model training", btn("ATME benchmark") + btn("+ Nieuwe training", true))}
        <div class="tabs"><button class="tab active" type="button">Overzicht</button><button class="tab" type="button">Datasets</button><button class="tab" type="button">Model</button><button class="tab" type="button">Runs</button></div>
        <div class="stat-grid-4" style="margin-bottom:12px">
          <div class="card status-card"><div class="status-ico ok"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M20 6L9 17l-5-5"/></svg></div><div class="status-meta"><span class="status-value">Trainer gereed</span><span class="status-hint">Online</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-label">GPU / VRAM</span><span class="status-value">RTX 4090</span><span class="status-hint">18.4 / 24 GB · 77%</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-value">Dataset Brain</span><span class="status-hint">3 datasets · 142.6K</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-label">Actieve run</span><span class="status-value">HADES-Llama-8B</span><span class="status-hint">24% · stap 2480</span></div></div>
        </div>
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Nieuwe training configureren</h2>
            <div class="mode-grid" style="margin-top:10px">
              <button class="mode-card active" type="button" data-mode="model"><span class="mode-ico">◆</span><span><span class="mode-title">Model trainen</span><span class="mode-desc">Fine-tune met eigen datasets</span></span></button>
              <button class="mode-card" type="button" data-mode="fw"><span class="mode-ico">◎</span><span><span class="mode-title">Framework trainen</span><span class="mode-desc">HADES Neural</span></span></button>
            </div>
            <div class="form-grid" style="margin-top:8px">
              <label class="field"><span class="field-label">Dataset</span><select class="control"><option>HADES-Chat</option></select></label>
              <label class="field"><span class="field-label">Mode</span><select class="control"><option>QLoRA (4-bit)</option></select></label>
              <label class="field"><span class="field-label">Base model</span><select class="control"><option>Llama-3.1-8B-Instruct</option></select></label>
              <label class="field"><span class="field-label">Max steps</span><select class="control"><option>10000</option></select></label>
            </div>
            <div class="config-actions">${btn("Model inspecteren")}${btn("Training starten", true)}</div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Actieve training</h2>
            <div class="run-name" style="margin-top:8px">HADES-Llama-8B <span class="tag gold">QLoRA</span></div>
            <div class="bar" style="margin-top:8px"><span style="width:24%"></span></div>
            <div class="muted" style="font-size:11px;margin-top:4px">Stap 2.480 / 10.000 · resterend 1u 34m</div>
            <div class="metrics-row" style="margin-top:12px">
              <div class="metric"><div class="metric-label">Loss</div><div class="metric-value">0.842</div></div>
              <div class="metric"><div class="metric-label">VRAM</div><div class="metric-value">13.6 GB</div></div>
              <div class="metric"><div class="metric-label">RAM</div><div class="metric-value">28.4 GB</div></div>
              <div class="metric"><div class="metric-label">Bottleneck</div><div class="metric-value orange">VRAM</div></div>
            </div>
            <p class="section-sub" style="margin-top:10px">Volledige pixel-referentie: <a href="../index.html" style="color:var(--gold)">index.html (Training Control)</a></p>
          </section>
        </div>`,

  agents: () => `
        ${head("Agents", btn("Vernieuwen") + btn("Import / Export", true))}
        <div style="display:flex;gap:8px;margin-bottom:12px">
          <div class="search-bar grow"><input placeholder="Zoek agents..." /></div>
          <select class="control" style="width:110px"><option>Rol</option></select>
          <select class="control" style="width:110px"><option>Status</option></select>
        </div>
        <div class="agent-grid">
          ${[
            ["Research", "Bronnen en synthese", "Gereed", true],
            ["Coding", "Code en wijzigingen", "Gereed", false],
            ["Planner", "Taken structureren", "Inactief", false],
            ["Reviewer", "Werk beoordelen", "Gereed", false],
            ["Trading", "PAPER-simulaties", "Inactief", false],
            ["Media", "Content en productie", "Gepland", false],
          ]
            .map(
              ([n, d, s, sel]) => `
          <div class="card agent-card${sel ? " selected" : ""}">
            <div class="agent-ico">◇</div>
            <div><div class="agent-name">${n}</div><div class="agent-desc">${d}</div><div style="margin-top:6px;font-size:11px"><span class="tag ${s === "Gereed" ? "green" : s === "Gepland" ? "warn" : ""}">${s}</span></div></div>
            <div class="muted" style="font-size:11px;text-align:right">Lokaal model</div>
          </div>`
            )
            .join("")}
        </div>`,

  media: () => `
        ${head("Media dashboard", btn("Import media") + btn("+ Nieuw project", true))}
        <div class="stat-grid-4" style="margin-bottom:12px">
          <div class="card card-pad"><div class="muted">Projecten</div><div style="font-weight:700">3 actief</div></div>
          <div class="card card-pad"><div class="muted">Render queue</div><div style="font-weight:700">Idle</div></div>
          <div class="card card-pad"><div class="muted">Assets</div><div style="font-weight:700">248 · 18.4 GB</div></div>
          <div class="card card-pad"><div class="muted">Live</div><div style="font-weight:700">Geen stream</div></div>
        </div>
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Sovereign Pitch</h2>
            <p class="section-sub">Script → Voice → Visual → Export</p>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0">
              ${["Script", "Voice", "Visual", "Export"]
                .map(
                  (s, i) =>
                    `<div class="card card-pad" style="text-align:center;${i < 2 ? "border-color:rgba(240,180,41,.45)" : ""}"><div style="font-weight:700;color:${i < 2 ? "var(--gold)" : "var(--muted)"}">${i + 1}</div><div style="font-size:11px;margin-top:4px">${s}</div></div>`
                )
                .join("")}
            </div>
            <textarea class="control" style="height:120px;padding:12px;width:100%;resize:vertical">HADES is lokale soevereine AI. Train je eigen modellen. Beheer je eigen kennis.</textarea>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Preview</h2>
            <div class="phone-preview">SOVEREIGN<br/>PITCH<div class="play-circle"><svg width="14" height="14" viewBox="0 0 24 24" fill="#fff"><path d="M8 5v14l11-7z"/></svg></div></div>
          </section>
        </div>`,

  youtube: () => channelPage("Youtube", "Long-form + Shorts", "Subscribe-ready script", "#FF0000"),
  tiktok: () => channelPage("Tiktok", "Short-form clips", "Hook in 1.5s", "#69C9D0"),
  instagram: () => channelPage("Instagram", "Reels & carousels", "Visual-first caption", "#E1306C"),
  facebook: () => channelPage("Facebook", "Posts & live", "Community CTA", "#1877F2"),

  trading: () => `
        ${head("TradingCenter", btn("Sync feeds") + btn("+ Strategie", true))}
        <section class="card" style="overflow:hidden">
          <div style="height:44px;display:flex;align-items:center;gap:10px;padding:0 14px;border-bottom:1px solid var(--border-soft)">
            <span style="font-size:18px;font-weight:700">BTC/USDT</span>
            <span class="green" style="font-weight:700">68.420,50</span>
            <span class="tag green">+1.24%</span>
            <div style="margin-left:auto;display:flex;border:1px solid var(--border);border-radius:6px;overflow:hidden">
              ${["1H", "4H", "1D", "1W"]
                .map(
                  (t, i) =>
                    `<button type="button" class="btn" style="height:30px;border:0;border-radius:0;${i === 2 ? "background:linear-gradient(180deg,#ffd76a,#f0b429);color:#1a1408;font-weight:700" : "background:#0b151a"}">${t}</button>`
                )
                .join("")}
            </div>
          </div>
          <svg viewBox="0 0 900 200" style="width:100%;height:200px;display:block;background:#071018">
            <path d="M0,150 C100,140 160,160 220,120 C300,70 380,100 460,80 C540,60 620,90 700,55 C780,30 840,50 900,35 L900,200 L0,200 Z" fill="rgba(34,197,94,.15)"/>
            <path d="M0,150 C100,140 160,160 220,120 C300,70 380,100 460,80 C540,60 620,90 700,55 C780,30 840,50 900,35" fill="none" stroke="#22c55e" stroke-width="2.2"/>
          </svg>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--border-soft)">
            <div class="card-pad"><div class="muted" style="font-size:11px">Volume 24u</div><div style="font-size:18px;font-weight:700">24.8B</div></div>
            <div class="card-pad" style="border-left:1px solid var(--border-soft)"><div class="muted" style="font-size:11px">High</div><div style="font-size:18px;font-weight:700">69.120</div></div>
            <div class="card-pad" style="border-left:1px solid var(--border-soft)"><div class="muted" style="font-size:11px">Low</div><div style="font-size:18px;font-weight:700">66.840</div></div>
          </div>
        </section>
        <section class="card card-pad" style="margin-top:12px">
          <h2 class="section-title">Strategieën</h2>
          <div class="list-row"><div class="grow"><strong>Momentum Breakout</strong><div class="muted" style="font-size:11px">BTC · 4H · paper</div></div><span class="tag green">Actief</span></div>
          <div class="list-row"><div class="grow"><strong>Mean Reversion Soft</strong><div class="muted" style="font-size:11px">ETH · 1H · paper</div></div><span class="tag">Paused</span></div>
        </section>`,

  research: () => `
        ${head("Research", btn("Import bron") + btn("+ Nieuw onderzoek", true))}
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Hoe verbetert ATME VRAM-planning?</h2>
            <p class="section-sub">In uitvoering · 6 bronnen · 14 evidence items</p>
            <div class="control" style="height:auto;padding:10px;margin-top:10px;flex-direction:column;align-items:flex-start;gap:4px"><strong>Claim</strong><span class="muted">Adaptive batching reduceert piek-VRAM met 12–18%.</span></div>
            <div class="control" style="height:auto;padding:10px;margin-top:8px;flex-direction:column;align-items:flex-start;gap:4px"><strong>Open vraag</strong><span class="muted">Geldt dit bij sequence length ≥ 8192?</span></div>
            <div style="display:flex;gap:8px;margin-top:12px">${btn("Zoek evidence")}${btn("Synthetiseer", true)}</div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Evidence</h2>
            <div class="page-grid-2" style="margin-top:10px">
              <div class="card card-pad"><strong style="font-size:12px">Bench #482</strong><p class="muted" style="font-size:11px;margin:4px 0 0">13.6 → 11.9 GB</p></div>
              <div class="card card-pad"><strong style="font-size:12px">ATME notes</strong><p class="muted" style="font-size:11px;margin:4px 0 0">Planner v2.1</p></div>
              <div class="card card-pad"><strong style="font-size:12px">Paper excerpt</strong><p class="muted" style="font-size:11px;margin:4px 0 0">Activation ckpt</p></div>
              <div class="card card-pad"><strong style="font-size:12px">Log snippet</strong><p class="muted" style="font-size:11px;margin:4px 0 0">Bottleneck=VRAM</p></div>
            </div>
          </section>
        </div>`,

  brain: () => `
        ${head("Brain", btn("Reindex") + btn("Snapshot", true))}
        <div class="stat-grid-3" style="margin-bottom:12px">
          <div class="card card-pad"><div class="muted">Chunks</div><div style="font-size:22px;font-weight:700">142.6K</div></div>
          <div class="card card-pad"><div class="muted">Collections</div><div style="font-size:22px;font-weight:700">12</div></div>
          <div class="card card-pad"><div class="muted">Laatste sync</div><div style="font-size:16px;font-weight:700">14:22</div></div>
        </div>
        <section class="card list-card">
          <div class="list-row"><div class="grow"><strong>HADES Knowledge v1.2</strong><div class="muted" style="font-size:11px">122.1K · primary</div></div><span class="tag gold">Active</span></div>
          <div class="list-row"><div class="grow"><strong>Chat transcripts</strong><div class="muted" style="font-size:11px">18.4K</div></div><span class="tag green">Indexed</span></div>
          <div class="list-row"><div class="grow"><strong>Code notes</strong><div class="muted" style="font-size:11px">2.1K</div></div><span class="tag">Idle</span></div>
        </section>`,

  memory: () => `
        ${head("Geheugen", btn("Nieuwe herinnering", true))}
        <div class="page-grid-2">
          <section class="card" style="padding:8px">
            <div class="search-bar" style="margin-bottom:8px"><input placeholder="Zoek geheugen..." /></div>
            <div class="list-row" style="background:rgba(240,180,41,.08)"><div class="grow"><strong>UI voorkeur: Chat-primary</strong><div class="muted" style="font-size:11px">preference · pinned</div></div></div>
            <div class="list-row"><div class="grow"><strong>GPU: RTX 4090 24GB</strong><div class="muted" style="font-size:11px">hardware fact</div></div></div>
            <div class="list-row"><div class="grow"><strong>Taal: Nederlands</strong><div class="muted" style="font-size:11px">locale</div></div></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Bewerken</h2>
            <label class="field" style="grid-template-columns:80px 1fr;margin-top:10px"><span class="field-label">Titel</span><input class="control" value="UI voorkeur: Chat-primary" /></label>
            <label class="field" style="grid-template-columns:80px 1fr"><span class="field-label">Type</span><select class="control"><option>preference</option><option>fact</option></select></label>
            <label class="field" style="grid-template-columns:80px 1fr"><span class="field-label">Inhoud</span><textarea class="control" style="height:100px;padding:8px">Gebruiker wil Chat als primary surface; Advanced consoles blijven beschikbaar.</textarea></label>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">${btn("Verwijderen")}${btn("Opslaan", true)}</div>
          </section>
        </div>`,

  knowledge: () => `
        ${head("Knowledge Library", btn("Import") + btn("+ Document", true))}
        <section class="card list-card">
          ${[
            ["navigatie.md", "Vandaag 09:14", "Note"],
            ["ATME-planner.md", "12 nov", "Spec"],
            ["training-runbook.md", "10 nov", "Guide"],
            ["hades-vision-excerpt.md", "Archief", "Archive"],
          ]
            .map(
              ([n, d, t]) =>
                `<div class="list-row"><div class="grow"><strong>${n}</strong><div class="muted" style="font-size:11px">${d}</div></div><span class="tag">${t}</span>${btn("Open")}</div>`
            )
            .join("")}
        </section>`,

  evidence: () => `
        ${head("Evidence Vault", btn("Nieuwe claim", true))}
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Claims</h2>
            <div class="list-row"><div class="grow"><strong>ATME reduceert VRAM-piek</strong><div class="muted" style="font-size:11px">4 bronnen · confidence hoog</div></div><span class="tag green">Supported</span></div>
            <div class="list-row"><div class="grow"><strong>QLoRA 4-bit voldoende voor 8B</strong><div class="muted" style="font-size:11px">2 bronnen</div></div><span class="tag gold">Likely</span></div>
            <div class="list-row"><div class="grow"><strong>GGUF merge in-scope</strong><div class="muted" style="font-size:11px">0 bronnen</div></div><span class="tag warn">Rejected</span></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Bronnen bij selectie</h2>
            <div class="kv"><span>Bench #482</span><span>local log</span></div>
            <div class="kv"><span>ATME notes</span><span>knowledge</span></div>
            <div class="kv"><span>Paper excerpt</span><span>pdf</span></div>
            <div class="kv"><span>Run log</span><span>./logs/…</span></div>
          </section>
        </div>`,

  files: () => `
        ${head("Bestanden", btn("Upload") + btn("Ingest", true))}
        <div class="page-grid-2">
          <section class="card" style="padding:8px">
            <div class="tree-line active">📁 D:\\HADES\\data</div>
            <div class="tree-line indent">📁 custom-instruct</div>
            <div class="tree-line indent">📁 eval-holdout</div>
            <div class="tree-line indent">📄 README.md</div>
            <div class="tree-line">📁 D:\\HADES\\outputs</div>
            <div class="tree-line indent">📁 hades-lora-8b</div>
            <div class="tree-line">📁 D:\\HADES\\logs</div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Preview — README.md</h2>
            <div class="muted" style="font-size:12px;line-height:1.55;margin-top:10px">
              <p><strong style="color:#fff;font-size:16px">HADES data</strong></p>
              <p>Lokale datasets voor training en evaluatie. Offline-first; sync is optioneel.</p>
              <ul><li>custom-instruct — 8.1K</li><li>eval-holdout — 2.1K</li></ul>
            </div>
          </section>
        </div>`,

  performance: () => `
        ${head("Performance", btn("Refresh", true))}
        <div class="stat-grid-4" style="margin-bottom:12px">
          <div class="card card-pad"><div class="muted">CPU</div><div style="font-weight:700">34%</div><div class="bar" style="margin-top:6px"><span style="width:34%"></span></div></div>
          <div class="card card-pad"><div class="muted">RAM</div><div style="font-weight:700">32.1 / 64 GB</div><div class="bar" style="margin-top:6px"><span style="width:50%"></span></div></div>
          <div class="card card-pad"><div class="muted">VRAM</div><div style="font-weight:700">18.4 / 24 GB</div><div class="bar" style="margin-top:6px"><span style="width:77%"></span></div></div>
          <div class="card card-pad"><div class="muted">Disk</div><div style="font-weight:700">412 GB free</div><div class="bar" style="margin-top:6px"><span style="width:28%"></span></div></div>
        </div>
        <section class="card card-pad">
          <h2 class="section-title">Services</h2>
          <div class="list-row"><div class="grow"><strong>LM Studio</strong><div class="muted" style="font-size:11px">:1234</div></div><span class="tag green">OK</span></div>
          <div class="list-row"><div class="grow"><strong>HADES API</strong><div class="muted" style="font-size:11px">local</div></div><span class="tag green">OK</span></div>
          <div class="list-row"><div class="grow"><strong>Tool Router</strong><div class="muted" style="font-size:11px">strict policy</div></div><span class="tag green">OK</span></div>
          <div class="list-row"><div class="grow"><strong>Training worker</strong><div class="muted" style="font-size:11px">job running</div></div><span class="tag gold">Busy</span></div>
        </section>`,

  settings: () => `
        ${head("Instellingen", btn("Opslaan", true))}
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Algemeen</h2>
            <label class="field" style="grid-template-columns:140px 1fr"><span class="field-label">Taal</span><select class="control"><option>Nederlands</option><option>English</option></select></label>
            <label class="field" style="grid-template-columns:140px 1fr"><span class="field-label">Thema</span><select class="control"><option>FINALBETA Dark</option></select></label>
            <label class="field" style="grid-template-columns:140px 1fr"><span class="field-label">Chat-primary</span><span class="switch on"></span></label>
            <label class="field" style="grid-template-columns:140px 1fr"><span class="field-label">Internet optioneel</span><span class="switch on"></span></label>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Policies</h2>
            <div class="policy-row"><span class="policy-name">File read</span><span class="tag green">Toegestaan</span></div>
            <div class="policy-row"><span class="policy-name">Network</span><span class="tag warn">Beperkt</span></div>
            <div class="policy-row"><span class="policy-name">Subprocess</span><span class="tag green">Toegestaan</span></div>
            <div class="policy-row"><span class="policy-name">Autonomous tools</span><span class="tag warn">Confirm</span></div>
          </section>
        </div>`,

  tools: () => `
        ${head("Plugins", btn("Import .HadesPlugin") + btn("Install", true))}
        <div class="stat-grid-4" style="margin-bottom:12px">
          <div class="card card-pad"><div class="muted">Plugins</div><div style="font-weight:700">12</div></div>
          <div class="card card-pad"><div class="muted">Running</div><div style="font-weight:700;color:var(--success)">9</div></div>
          <div class="card card-pad"><div class="muted">Tool Router</div><div style="font-weight:700">Healthy</div></div>
          <div class="card card-pad"><div class="muted">Updates</div><div style="font-weight:700">2</div></div>
        </div>
        <section class="card list-card">
          ${[
            ["ui-ux-pro-max", "Design intelligence", "Running"],
            ["karpathy-skills", "Coding guidelines", "Running"],
            ["web-fetch-local", "Optional network fetch", "Idle"],
            ["evidence-vault", "Research evidence store", "Running"],
            ["media-pipeline", "Audio/video tools", "Running"],
          ]
            .map(
              ([n, d, s]) =>
                `<div class="list-row"><div class="grow"><strong>${n}</strong><div class="muted" style="font-size:11px">${d}</div></div><span class="tag ${s === "Running" ? "green" : ""}">${s}</span>${btn("Configure")}</div>`
            )
            .join("")}
        </section>`,

  mcp: () => `
        ${head("MCP", btn("Add server", true))}
        <section class="card list-card">
          <div class="list-row"><div class="grow"><strong>filesystem</strong><div class="muted" style="font-size:11px">stdio · local workspace</div></div><span class="tag green">Connected</span></div>
          <div class="list-row"><div class="grow"><strong>browser</strong><div class="muted" style="font-size:11px">optional · needsAuth</div></div><span class="tag warn">Idle</span></div>
          <div class="list-row"><div class="grow"><strong>memory</strong><div class="muted" style="font-size:11px">HADES memory bridge</div></div><span class="tag green">Connected</span></div>
        </section>
        <section class="card card-pad" style="margin-top:12px">
          <h2 class="section-title">Tools (filesystem)</h2>
          <div class="kv"><span>read_file</span><span class="tag green">allowed</span></div>
          <div class="kv"><span>write_file</span><span class="tag warn">confirm</span></div>
          <div class="kv"><span>list_dir</span><span class="tag green">allowed</span></div>
        </section>`,

  workflows: () => `
        ${head("Workflows", btn("Run") + btn("+ Workflow", true))}
        <div class="page-grid-2">
          <section class="card" style="padding:8px">
            <div class="list-row" style="background:rgba(240,180,41,.08)"><div class="grow"><strong>Ingest → Brain → Chat</strong><div class="muted" style="font-size:11px">3 nodes</div></div></div>
            <div class="list-row"><div class="grow"><strong>Train → Eval → Report</strong><div class="muted" style="font-size:11px">5 nodes</div></div></div>
            <div class="list-row"><div class="grow"><strong>Media export pack</strong><div class="muted" style="font-size:11px">4 nodes</div></div></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Ingest → Brain → Chat</h2>
            <div class="flow-area" style="margin-top:10px">
              <div class="flow-node gold" style="left:24px;top:40px"><strong>Ingest files</strong><small>Trigger</small></div>
              <div class="flow-node" style="left:200px;top:110px"><strong>Dataset Brain</strong><small>Index</small></div>
              <div class="flow-node" style="left:380px;top:40px"><strong>Notify Chat</strong><small>Output</small></div>
            </div>
          </section>
        </div>`,

  system: () => `
        ${head("Systeem", btn("Export diagnostics", true))}
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Build</h2>
            <div class="kv"><span>App</span><span>HADES FINALBETA</span></div>
            <div class="kv"><span>UI revision</span><span>v2 mockup</span></div>
            <div class="kv"><span>Node</span><span>local</span></div>
            <div class="kv"><span>OS</span><span>Windows 10</span></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Health checks</h2>
            <div class="list-row"><div class="grow">API reachability</div><span class="tag green">OK</span></div>
            <div class="list-row"><div class="grow">LM Studio</div><span class="tag green">OK</span></div>
            <div class="list-row"><div class="grow">Persistence</div><span class="tag green">OK</span></div>
            <div class="list-row"><div class="grow">Network (optional)</div><span class="tag">Skipped</span></div>
          </section>
        </div>
        <section class="card card-pad" style="margin-top:12px">
          <h2 class="section-title">Recente logs</h2>
          <pre style="margin:8px 0 0;font-family:var(--mono);font-size:11px;color:var(--muted);line-height:1.5;white-space:pre-wrap">[14:22:01] training.worker job=run-20241114-1422 started
[14:22:08] atme.planner strategy=adaptive confidence=0.92
[14:28:16] training.worker step=2480 loss=0.842 vram=13.6</pre>
        </section>`,
};

function channelPage(title, sub, tip, accent) {
  return `
        ${head(title, btn("Nieuw script") + btn("Generate", true))}
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">${title} pipeline</h2>
            <p class="section-sub">${sub}</p>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0">
              ${["Script", "Assets", "Edit", "Publish"]
                .map(
                  (s, i) =>
                    `<div class="card card-pad" style="text-align:center;border-color:${i === 0 ? accent : "var(--border)"}"><div style="font-weight:700">${i + 1}</div><div style="font-size:11px;margin-top:4px">${s}</div></div>`
                )
                .join("")}
            </div>
            <textarea class="control" style="height:140px;padding:12px;width:100%;resize:vertical">${tip}

HADES — lokale soevereine AI.
Train. Own. Control.</textarea>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Preview</h2>
            <div class="phone-preview" style="border-color:${accent}">${title.toUpperCase()}<div class="play-circle"><svg width="14" height="14" viewBox="0 0 24 24" fill="#fff"><path d="M8 5v14l11-7z"/></svg></div></div>
            <div style="display:flex;gap:8px;justify-content:center;margin-top:12px">${btn("Export")}${btn("Schedule", true)}</div>
          </section>
        </div>`;
}

function shell(pageId) {
  const meta = PAGE_META[pageId];
  const main = CONTENTS[pageId]();
  const inspTitle =
    pageId === "models"
      ? "Modeldetail"
      : pageId === "agents"
        ? "Agentprofiel"
        : pageId === "chat"
          ? "Context"
          : "Inspector";
  return `<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>HADES FINALBETA — ${meta.title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="../css/hades.css" />
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M12 2L4 7v5c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V7l-8-5z"/>
            <path d="M12 8v8M9 11h6"/>
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">HADES</span>
          <span class="brand-sub">FINALBETA</span>
          <span class="brand-tag">Control Intelligence</span>
        </div>
      </div>
${topnav(meta.top)}
      <div class="topright">
        <div class="status-pill">
          <span class="dot"></span>
          <div class="status-pill-copy">
            <span class="status-pill-title">HADES Local</span>
            <span class="status-pill-sub">All systems operational</span>
          </div>
        </div>
        <a class="icon-btn" href="settings.html" aria-label="Instellingen">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </a>
      </div>
    </header>
    <div class="body">
      <aside class="sidebar">
        <div class="sidebar-scene" aria-hidden="true"></div>
        <div class="sidebar-inner">
${sidebar(meta.section, pageId)}
        </div>
      </aside>
      <main class="main">
${main}
      </main>
${defaultInsp(inspTitle)}
    </div>
  </div>
  <script src="../js/hades.js"></script>
</body>
</html>
`;
}

const allIds = Object.keys(PAGE_META);
for (const id of allIds) {
  if (!CONTENTS[id]) throw new Error("Missing content for " + id);
  const file = `${id}.html`;
  fs.writeFileSync(path.join(pagesDir, file), shell(id), "utf8");
  console.log("wrote", file);
}

// Hub
const hubCards = allIds
  .map((id) => {
    const m = PAGE_META[id];
    const primary = id === "model-training" ? " primary" : "";
    return `      <a class="hub-card${primary}" href="pages/${id}.html">
        <strong>${m.title}${id === "model-training" ? " ★" : ""}</strong>
        <span>${m.section} · FinalBeta page</span>
      </a>`;
  })
  .join("\n");

fs.writeFileSync(
  path.join(__dirname, "hub.html"),
  `<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>HADES FINALBETA v2 — Alle pagina's</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="css/hades.css" />
  <style>
    body{overflow:auto}
    .hub{max-width:1100px;margin:40px auto;padding:0 24px 64px}
    .hub h1{font-size:28px;letter-spacing:.08em;color:var(--gold-3);margin:0 0 8px}
    .hub p{color:var(--muted);margin:0 0 24px;max-width:720px}
    .hub-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
    .hub-card{display:block;padding:16px 18px;border:1px solid var(--border);border-radius:10px;background:linear-gradient(180deg,rgba(14,26,36,.95),rgba(8,16,24,.96));transition:border-color .15s,box-shadow .15s}
    .hub-card:hover{border-color:rgba(240,180,41,.45);box-shadow:0 0 20px rgba(240,180,41,.12)}
    .hub-card strong{display:block;font-size:14px;margin-bottom:4px;color:#fff}
    .hub-card span{font-size:11px;color:var(--muted)}
    .hub-card.primary{border-color:rgba(240,180,41,.5);background:linear-gradient(135deg,rgba(240,180,41,.12),rgba(10,18,26,.95))}
    .hub-card.primary strong{color:var(--gold)}
    .note{margin-top:28px;padding:14px 16px;border:1px solid rgba(74,163,255,.25);border-radius:8px;background:rgba(74,163,255,.06);font-size:12.5px;color:var(--text-2);line-height:1.5}
    .count{color:var(--gold);font-weight:700}
  </style>
</head>
<body>
  <div class="hub">
    <h1>HADES FINALBETA v2</h1>
    <p>Volledige mockup-set: <span class="count">${allIds.length}</span> FinalBeta-pagina's in dezelfde stijl.
    Pixel-referentie Training Control blijft ook op <a href="index.html" style="color:var(--gold)">index.html</a>.</p>
    <div class="hub-grid">
${hubCards}
    </div>
    <div class="note">
      Bron van waarheid voor page IDs: <code>components/hades/finalbeta/routes.ts</code> (<code>FINALBETA_PAGES</code>).
      Open op ≥ 1440px breedte. Later integreren in de React FinalBeta shell.
    </div>
  </div>
</body>
</html>
`,
  "utf8"
);

console.log("wrote hub.html with", allIds.length, "pages");
console.log("DONE");
