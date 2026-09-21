/**
 * Generates sibling pages with identical shell for the FINALBETA v2 mockup.
 * Run: node docs/mockups/finalbeta-v2/_generate-pages.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pagesDir = path.join(__dirname, "pages");

const topnav = (active) => `
      <nav class="topnav" aria-label="Hoofdmenu">
        <a class="topnav-item${active === "ai" ? " active" : ""}" href="hades-ai.html">
          <svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>
          <span class="topnav-copy"><span class="topnav-label">Hades AI</span><span class="topnav-desc">Jouw persoonlijke assistent</span></span>
        </a>
        <a class="topnav-item${active === "llm" ? " active" : ""}" href="../index.html">
          <svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/></svg>
          <span class="topnav-copy"><span class="topnav-label">LLM</span><span class="topnav-desc">Train. Tune. Own.</span></span>
        </a>
        <a class="topnav-item${active === "media" ? " active" : ""}" href="media.html">
          <svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M10 9l5 3-5 3V9z"/></svg>
          <span class="topnav-copy"><span class="topnav-label">Media Control</span><span class="topnav-desc">Audio, video &amp; live</span></span>
        </a>
        <a class="topnav-item${active === "trading" ? " active" : ""}" href="trading.html">
          <svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 17l5-5 4 4 8-9"/><path d="M14 7h6v6"/></svg>
          <span class="topnav-copy"><span class="topnav-label">TradingCenter</span><span class="topnav-desc">Marktdata &amp; strategieën</span></span>
        </a>
        <a class="topnav-item${active === "research" ? " active" : ""}" href="research.html">
          <svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/><circle cx="11" cy="11" r="3"/></svg>
          <span class="topnav-copy"><span class="topnav-label">Onderzoek &amp; kennis</span><span class="topnav-desc">Analyseer. Ontdek. Bouw.</span></span>
        </a>
        <a class="topnav-item${active === "plugins" ? " active" : ""}" href="plugins.html">
          <svg class="topnav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
          <span class="topnav-copy"><span class="topnav-label">Plugin &amp; Runtime</span><span class="topnav-desc">Breid uit. Integreer. Automatiseer.</span></span>
        </a>
      </nav>`;

const brand = `
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
      </div>`;

const topright = `
      <div class="topright">
        <div class="status-pill">
          <span class="dot"></span>
          <div class="status-pill-copy">
            <span class="status-pill-title">HADES Local</span>
            <span class="status-pill-sub">All systems operational</span>
          </div>
        </div>
        <button class="icon-btn" type="button" data-toast="Instellingen (demo)" aria-label="Instellingen">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
      </div>`;

function sideItem(href, label, desc, icon, active) {
  return `
            <a class="side-item${active ? " active" : ""}" href="${href}">
              ${icon}
              <span class="side-copy"><span class="side-label">${label}</span><span class="side-desc">${desc}</span></span>
            </a>`;
}

const icons = {
  home: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 10.5L12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-9.5z"/></svg>`,
  db: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>`,
  cube: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3l7 4v10l-7 4-7-4V7l7-4z"/><path d="M12 12l7-4M12 12v10M12 12L5 8"/></svg>`,
  net: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/><circle cx="12" cy="12" r="2.5"/><path d="M7.5 7.5l3 3M16.5 7.5l-3 3M7.5 16.5l3-3M16.5 16.5l-3-3"/></svg>`,
  list: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/></svg>`,
  chip: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>`,
  chat: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  mem: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.2-2.5 5.5L15 17H9l-1.5-2.5C6.3 13.2 5 11.5 5 9a7 7 0 0 1 7-7z"/></svg>`,
  film: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M10 9l5 3-5 3V9z"/></svg>`,
  chart: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 17l5-5 4 4 8-9"/><path d="M14 7h6v6"/></svg>`,
  search: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>`,
  plug: `<svg class="side-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2v6M8 8H4v4a8 8 0 0 0 16 0V8h-4M8 8V2M16 8V2"/></svg>`,
};

function llmSidebar(active) {
  return `
          <div class="studio-card">
            <div class="studio-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.2-2.5 5.5L15 17H9l-1.5-2.5C6.3 13.2 5 11.5 5 9a7 7 0 0 1 7-7z"/><path d="M9 21h6M10 17v4M14 17v4"/></svg>
            </div>
            <div>
              <div class="studio-title">Training Studio</div>
              <div class="studio-sub">Train modellen. Breid HADES uit.</div>
            </div>
          </div>
          <nav class="side-nav">
            ${sideItem("../index.html", "Overzicht", "Status en snelle inzichten", icons.home, active === "overzicht")}
            ${sideItem("datasets.html", "Datasets", "Beheer je datasets", icons.db, active === "datasets")}
            ${sideItem("../index.html", "Model trainen", "LLM fine-tuning", icons.cube, active === "model")}
            ${sideItem("framework.html", "Framework trainen", "HADES Neural training", icons.net, active === "framework")}
            ${sideItem("runs.html", "Runs &amp; logs", "Voortgang en historie", icons.list, active === "runs")}
            ${sideItem("hardware.html", "Hardware &amp; ATME", "GPU, benchmarks en tuning", icons.chip, active === "hardware")}
          </nav>
          <div class="sidebar-motto">Higher Intelligence<br />A Brighter Tomorrow</div>`;
}

function sectionSidebar(title, sub, items, motto) {
  return `
          <div class="studio-card">
            <div class="studio-icon">${icons.mem}</div>
            <div>
              <div class="studio-title">${title}</div>
              <div class="studio-sub">${sub}</div>
            </div>
          </div>
          <nav class="side-nav">
            ${items.map((i) => sideItem(i.href, i.label, i.desc, i.icon, i.active)).join("")}
          </nav>
          <div class="sidebar-motto">${motto || "Higher Intelligence<br />A Brighter Tomorrow"}</div>`;
}

function inspector(quote, blocks) {
  return `
      <aside class="inspector">
        <p class="quote">${quote}</p>
        ${blocks}
      </aside>`;
}

function page({ file, title, topActive, sidebar, main, insp }) {
  const html = `<!DOCTYPE html>
<html lang="nl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>HADES FINALBETA — ${title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="../css/hades.css" />
</head>
<body>
  <div class="app">
    <header class="topbar">
${brand}
${topnav(topActive)}
${topright}
    </header>
    <div class="body">
      <aside class="sidebar">
        <div class="sidebar-scene" aria-hidden="true"></div>
        <div class="sidebar-inner">
${sidebar}
        </div>
      </aside>
      <main class="main">
${main}
      </main>
${insp}
    </div>
  </div>
  <script src="../js/hades.js"></script>
</body>
</html>
`;
  fs.writeFileSync(path.join(pagesDir, file), html, "utf8");
  console.log("wrote", file);
}

const defaultInsp = inspector(
  "“Sovereign AI. Local power.<br />Infinite possibilities.”",
  `
        <section class="insp-section">
          <h3 class="insp-title">Systeem</h3>
          <div class="insp-card">
            <div class="detail-row"><span class="k">Status</span><span class="v green">● Online</span></div>
            <div class="detail-row"><span class="k">Host</span><span class="v">DESKTOP-HADES</span></div>
            <div class="detail-row"><span class="k">Modus</span><span class="v">Lokaal / Offline-first</span></div>
            <div class="detail-row"><span class="k">UI revision</span><span class="v">FINALBETA v2 mockup</span></div>
          </div>
        </section>
        <section class="insp-section">
          <h3 class="insp-title">Snelacties</h3>
          <div class="insp-card" style="display:flex;flex-direction:column;gap:8px">
            <button class="btn btn-sm btn-outline btn-block" type="button" data-toast="Demo">Refresh status</button>
            <button class="btn btn-sm btn-gold btn-block" type="button" data-toast="Demo">Open Work Runtime</button>
          </div>
        </section>`
);

// --- Pages ---
page({
  file: "hades-ai.html",
  title: "Hades AI",
  topActive: "ai",
  sidebar: sectionSidebar("Hades AI", "Persoonlijke assistent", [
    { href: "hades-ai.html", label: "Chat", desc: "Gesprekken en taken", icon: icons.chat, active: true },
    { href: "hades-ai.html", label: "Agents", desc: "Gespecialiseerde helpers", icon: icons.net, active: false },
    { href: "hades-ai.html", label: "Geheugen", desc: "Context en voorkeuren", icon: icons.mem, active: false },
    { href: "hades-ai.html", label: "Tools", desc: "Beschikbare acties", icon: icons.plug, active: false },
  ]),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Hades AI</h1>
            <p class="page-sub">Jouw lokale assistent — chat-first, offline-capable, met toegang tot HADES capabilities.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline" type="button" data-toast="Nieuwe chat">+ Nieuwe chat</button>
            <button class="btn btn-gold" type="button" data-toast="Mission starten">Mission starten</button>
          </div>
        </div>
        <div class="chat-layout">
          <section class="card" style="padding:10px;overflow:auto">
            <div class="section-title" style="font-size:13px;margin:4px 6px 10px">Recente chats</div>
            <div class="list-row" style="border-radius:6px;background:rgba(240,180,41,.08);border:1px solid rgba(240,180,41,.25)">
              <div>
                <div style="font-weight:650">Training pipeline setup</div>
                <div class="muted" style="font-size:10px">Vandaag · 14:22</div>
              </div>
            </div>
            <div class="list-row">
              <div>
                <div style="font-weight:600">Dataset Brain sync</div>
                <div class="muted" style="font-size:10px">Gisteren</div>
              </div>
            </div>
            <div class="list-row">
              <div>
                <div style="font-weight:600">Research: ATME planner</div>
                <div class="muted" style="font-size:10px">12 nov</div>
              </div>
            </div>
          </section>
          <section class="card chat-thread">
            <div style="padding:12px 14px;border-bottom:1px solid var(--border-soft);display:flex;justify-content:space-between;align-items:center">
              <div>
                <div style="font-weight:650;font-size:15px">Training pipeline setup</div>
                <div class="muted" style="font-size:11px">Model: lokaal · Tools: aan · Memory: aan</div>
              </div>
              <span class="tag green">Live</span>
            </div>
            <div class="messages">
              <div class="bubble user">Kun je een QLoRA training voorbereiden voor Llama 3.1 8B met de HADES-Chat dataset?</div>
              <div class="bubble">Ja. Ik stel een ATME Adaptive plan voor met QLoRA 4-bit, seq 4096, batch 4 × grad accum 8. Geschat VRAM-piek ≈ 14.2 GB op je RTX 4090 — vertrouwen 92%.<br /><br />Wil je dat ik de run start vanuit Training Control?</div>
              <div class="bubble user">Ja, start met die instellingen.</div>
              <div class="bubble">Run <strong>HADES-Llama-8B</strong> is geconfigureerd. Open <a href="../index.html" style="color:var(--gold)">Training Control</a> om voortgang te volgen — stap 2.480 / 10.000 loopt al.</div>
            </div>
            <div class="composer">
              <input type="text" placeholder="Bericht aan HADES…" />
              <button class="btn btn-gold" type="button" data-toast="Bericht verzonden (demo)">Verstuur</button>
            </div>
          </section>
        </div>`,
  insp: defaultInsp,
});

page({
  file: "media.html",
  title: "Media Control",
  topActive: "media",
  sidebar: sectionSidebar("Media Studio", "Audio, video & live", [
    { href: "media.html", label: "Projecten", desc: "Scripts en shots", icon: icons.film, active: true },
    { href: "media.html", label: "Timeline", desc: "Montage en cuts", icon: icons.list, active: false },
    { href: "media.html", label: "Assets", desc: "Media bibliotheek", icon: icons.db, active: false },
    { href: "media.html", label: "Live", desc: "Streams & capture", icon: icons.chip, active: false },
  ]),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Media Control</h1>
            <p class="page-sub">Produceer audio, video en live content vanuit dezelfde lokale HADES-omgeving.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline" type="button" data-toast="Import">Import media</button>
            <button class="btn btn-gold" type="button" data-toast="Nieuw project">+ Nieuw project</button>
          </div>
        </div>
        <div class="status-strip">
          <div class="card status-card"><div class="status-meta"><span class="status-value">3 projecten</span><span class="status-hint">2 actief · 1 gearchiveerd</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-value">Render queue</span><span class="status-hint">Idle · GPU ready</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-value">Assets</span><span class="status-hint">248 bestanden · 18.4 GB</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-value">Live</span><span class="status-hint">Geen actieve stream</span></div></div>
        </div>
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Actief project — Sovereign Pitch</h2>
            <p class="section-sub">Script → Voice → Visual → Export</p>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:14px 0">
              ${["Script", "Voice", "Visual", "Export"]
                .map(
                  (s, i) =>
                    `<div class="card card-pad" style="text-align:center;${i < 2 ? "border-color:rgba(240,180,41,.45)" : ""}"><div style="font-weight:700;color:${i < 2 ? "var(--gold)" : "var(--muted)"}">${i + 1}</div><div style="font-size:11px;margin-top:4px">${s}</div></div>`
                )
                .join("")}
            </div>
            <textarea class="control" style="height:160px;padding:12px;resize:vertical;width:100%">HADES is lokale soevereine AI. Geen cloud-afhankelijkheid. Train je eigen modellen. Beheer je eigen kennis.</textarea>
            <div style="display:flex;gap:8px;margin-top:12px;justify-content:flex-end">
              <button class="btn btn-outline" type="button" data-toast="Preview">Preview</button>
              <button class="btn btn-gold" type="button" data-toast="Generate">Generate voice</button>
            </div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Preview</h2>
            <div style="height:280px;border:1px solid var(--border);border-radius:8px;background:linear-gradient(180deg,#0a1218,#05080c),url('../assets/mountain-scene.png') center/cover;display:grid;place-items:center;margin-top:10px">
              <div style="width:56px;height:56px;border:2px solid #fff;border-radius:50%;display:grid;place-items:center">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><path d="M8 5v14l11-7z"/></svg>
              </div>
            </div>
          </section>
        </div>`,
  insp: defaultInsp,
});

page({
  file: "trading.html",
  title: "TradingCenter",
  topActive: "trading",
  sidebar: sectionSidebar("TradingCenter", "Marktdata & strategieën", [
    { href: "trading.html", label: "Markets", desc: "Live charts", icon: icons.chart, active: true },
    { href: "trading.html", label: "Strategieën", desc: "Signals & rules", icon: icons.net, active: false },
    { href: "trading.html", label: "Portfolio", desc: "Posities", icon: icons.db, active: false },
    { href: "trading.html", label: "Alerts", desc: "Notificaties", icon: icons.list, active: false },
  ]),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">TradingCenter</h1>
            <p class="page-sub">Lokale marktdata, strategieën en signalen — analyse first, uitvoering onder jouw controle.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline" type="button" data-toast="Sync">Sync feeds</button>
            <button class="btn btn-gold" type="button" data-toast="Strategie">+ Strategie</button>
          </div>
        </div>
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
          <svg viewBox="0 0 900 220" style="width:100%;height:220px;display:block;background:#071018">
            <defs><linearGradient id="tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#22c55e" stop-opacity=".25"/><stop offset="100%" stop-color="#22c55e" stop-opacity="0"/></linearGradient></defs>
            <g stroke="#152433" stroke-width="1">${[40, 80, 120, 160, 200].map((y) => `<line x1="0" y1="${y}" x2="900" y2="${y}"/>`).join("")}</g>
            <path d="M0,160 C80,150 120,170 180,140 C240,110 280,130 340,100 C400,70 460,90 520,75 C580,60 640,95 700,70 C760,45 820,55 900,40 L900,220 L0,220 Z" fill="url(#tg)"/>
            <path d="M0,160 C80,150 120,170 180,140 C240,110 280,130 340,100 C400,70 460,90 520,75 C580,60 640,95 700,70 C760,45 820,55 900,40" fill="none" stroke="#22c55e" stroke-width="2.2"/>
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
  insp: defaultInsp,
});

page({
  file: "research.html",
  title: "Onderzoek & kennis",
  topActive: "research",
  sidebar: sectionSidebar("Onderzoek", "Analyseer. Ontdek. Bouw.", [
    { href: "research.html", label: "Projecten", desc: "Onderzoeksvragen", icon: icons.search, active: true },
    { href: "research.html", label: "Evidence Vault", desc: "Bewijsstukken", icon: icons.db, active: false },
    { href: "research.html", label: "Knowledge", desc: "Dataset Brain", icon: icons.mem, active: false },
    { href: "research.html", label: "Bronnen", desc: "Files & web (optioneel)", icon: icons.list, active: false },
  ]),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Onderzoek &amp; kennis</h1>
            <p class="page-sub">Structureer vragen, verzamel evidence en bouw kennis die HADES lokaal kan hergebruiken.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline" type="button" data-toast="Import">Import bron</button>
            <button class="btn btn-gold" type="button" data-toast="Nieuw">+ Nieuw onderzoek</button>
          </div>
        </div>
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Hoe verbetert ATME VRAM-planning?</h2>
            <p class="section-sub">Status: In uitvoering · 6 bronnen · 14 evidence items</p>
            <div style="margin-top:12px;display:flex;flex-direction:column;gap:8px">
              <div class="control" style="height:auto;padding:10px;align-items:flex-start;flex-direction:column;gap:4px">
                <strong>Claim</strong>
                <span class="muted">Adaptive batching reduceert piek-VRAM met 12–18% t.o.v. fixed schedules.</span>
              </div>
              <div class="control" style="height:auto;padding:10px;align-items:flex-start;flex-direction:column;gap:4px">
                <strong>Open vraag</strong>
                <span class="muted">Geldt dit ook bij sequence length ≥ 8192?</span>
              </div>
            </div>
            <div style="display:flex;gap:8px;margin-top:12px">
              <button class="btn btn-outline" type="button" data-toast="Zoek">Zoek evidence</button>
              <button class="btn btn-gold" type="button" data-toast="Synthese">Synthetiseer</button>
            </div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Evidence</h2>
            <div class="page-grid-2" style="margin-top:10px">
              <div class="card card-pad"><strong style="font-size:12px">Bench run #482</strong><p class="muted" style="font-size:11px;margin:4px 0 0">VRAM piek 13.6 → 11.9 GB</p></div>
              <div class="card card-pad"><strong style="font-size:12px">ATME notes</strong><p class="muted" style="font-size:11px;margin:4px 0 0">Planner v2.1 heuristics</p></div>
              <div class="card card-pad"><strong style="font-size:12px">Paper excerpt</strong><p class="muted" style="font-size:11px;margin:4px 0 0">Activation ckpt tradeoffs</p></div>
              <div class="card card-pad"><strong style="font-size:12px">Log snippet</strong><p class="muted" style="font-size:11px;margin:4px 0 0">Bottleneck=VRAM @71%</p></div>
            </div>
          </section>
        </div>`,
  insp: defaultInsp,
});

page({
  file: "plugins.html",
  title: "Plugin & Runtime",
  topActive: "plugins",
  sidebar: sectionSidebar("Plugin & Runtime", "Breid uit. Integreer.", [
    { href: "plugins.html", label: "Installed", desc: "Actieve plugins", icon: icons.plug, active: true },
    { href: "plugins.html", label: "Marketplace", desc: "Ontdek packages", icon: icons.search, active: false },
    { href: "plugins.html", label: "Tool Router", desc: "Routing & policies", icon: icons.net, active: false },
    { href: "plugins.html", label: "Services", desc: "Lifecycle", icon: icons.chip, active: false },
  ]),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Plugin &amp; Runtime</h1>
            <p class="page-sub">Beheer .HadesPlugin packages, dependencies en de lokale tool runtime.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline" type="button" data-toast="Import">Import .HadesPlugin</button>
            <button class="btn btn-gold" type="button" data-toast="Install">Install package</button>
          </div>
        </div>
        <div class="status-strip">
          <div class="card status-card"><div class="status-meta"><span class="status-value">12 plugins</span><span class="status-hint">9 running · 3 idle</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-value">Tool Router</span><span class="status-hint green">Healthy</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-value">Permissions</span><span class="status-hint">Strict local policy</span></div></div>
          <div class="card status-card"><div class="status-meta"><span class="status-value">Updates</span><span class="status-hint">2 beschikbaar</span></div></div>
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
              ([name, desc, st]) => `
          <div class="list-row">
            <div class="status-ico doc" style="width:34px;height:34px">${icons.plug}</div>
            <div class="grow"><div style="font-weight:650">${name}</div><div class="muted" style="font-size:11px">${desc}</div></div>
            <span class="tag ${st === "Running" ? "green" : ""}">${st}</span>
            <button class="btn btn-sm btn-outline" type="button" data-toast="Configure ${name}">Configure</button>
          </div>`
            )
            .join("")}
        </section>`,
  insp: defaultInsp,
});

// LLM subpages
page({
  file: "datasets.html",
  title: "Datasets",
  topActive: "llm",
  sidebar: llmSidebar("datasets"),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Datasets</h1>
            <p class="page-sub">Beheer lokale en gesynchroniseerde datasets voor training en evaluatie.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-outline" type="button" data-toast="Sync">Sync Hugging Face</button>
            <button class="btn btn-gold" type="button" data-toast="Import">+ Dataset toevoegen</button>
          </div>
        </div>
        <section class="card list-card">
          ${[
            ["HADES-Chat", "Dataset Brain · 142.6K", "Actief"],
            ["HuggingFaceTB/smoltalk", "HF sync · 12.4K", "Sync"],
            ["custom-instruct", "D:\\\\HADES\\\\data · 8.1K", "Lokaal"],
            ["eval-holdout-v2", "Eval split · 2.1K", "Holdout"],
          ]
            .map(
              ([n, d, t]) => `
          <div class="list-row">
            <div class="grow"><div style="font-weight:650">${n}</div><div class="muted" style="font-size:11px">${d}</div></div>
            <span class="tag ${t === "Actief" ? "gold" : ""}">${t}</span>
            <button class="btn btn-sm btn-outline" type="button" data-toast="Open ${n}">Open</button>
          </div>`
            )
            .join("")}
        </section>`,
  insp: defaultInsp,
});

page({
  file: "framework.html",
  title: "Framework trainen",
  topActive: "llm",
  sidebar: llmSidebar("framework"),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Framework trainen</h1>
            <p class="page-sub">Train de HADES Neural framework op maat van jouw lokale omgeving.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-gold" type="button" data-toast="Start framework training">Training starten</button>
          </div>
        </div>
        <div class="page-grid-2">
          <section class="card card-pad">
            <h2 class="section-title">Neural configuratie</h2>
            <div class="kv"><span>Neural mode</span><span>Hybrid (Memory+Tools)</span></div>
            <div class="kv"><span>Requirement</span><span>&gt;= 8B parameters</span></div>
            <div class="kv"><span>Dual memory</span><span>ATME (VRAM+RAM)</span></div>
            <div class="kv"><span>Domains</span><span>Core, Tools, Agents, Safety</span></div>
            <div class="kv"><span>Status</span><span class="green">Gereed</span></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Doelprofiel</h2>
            <p class="section-sub">Optimaliseer routing, memory retrieval en tool-use voor jouw workload.</p>
            <div style="margin-top:12px;display:flex;flex-direction:column;gap:8px">
              <label class="field" style="grid-template-columns:120px 1fr"><span class="field-label">Focus</span><select class="control"><option>Chat-primary</option><option>Research-heavy</option><option>Coding</option></select></label>
              <label class="field" style="grid-template-columns:120px 1fr"><span class="field-label">Safety</span><select class="control"><option>Strict local</option><option>Balanced</option></select></label>
            </div>
          </section>
        </div>`,
  insp: defaultInsp,
});

page({
  file: "runs.html",
  title: "Runs & logs",
  topActive: "llm",
  sidebar: llmSidebar("runs"),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Runs &amp; logs</h1>
            <p class="page-sub">Voortgang, historie en diagnostiek van training runs.</p>
          </div>
        </div>
        <section class="card list-card">
          ${[
            ["HADES-Llama-8B", "Actief · stap 2480/10000 · loss 0.842", "Actief"],
            ["ATME-bench-4090", "Voltooid · score 9.4/10", "Done"],
            ["Qwen14B-QLoRA", "Gestopt · VRAM OOM @ step 420", "Failed"],
            ["Mistral-7B-eval", "Voltooid · eval perplexity 5.21", "Done"],
          ]
            .map(
              ([n, d, t]) => `
          <div class="list-row">
            <div class="grow"><div style="font-weight:650">${n}</div><div class="muted" style="font-size:11px">${d}</div></div>
            <span class="tag ${t === "Actief" ? "gold" : t === "Failed" ? "warn" : "green"}">${t}</span>
            <button class="btn btn-sm btn-outline" type="button" data-toast="Log ${n}">Log</button>
          </div>`
            )
            .join("")}
        </section>`,
  insp: defaultInsp,
});

page({
  file: "hardware.html",
  title: "Hardware & ATME",
  topActive: "llm",
  sidebar: llmSidebar("hardware"),
  main: `
        <div class="page-head">
          <div>
            <h1 class="page-title">Hardware &amp; ATME</h1>
            <p class="page-sub">GPU, geheugen, benchmarks en de Adaptive Training Memory Engine.</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-gold" type="button" data-toast="Benchmark">ATME benchmark</button>
          </div>
        </div>
        <div class="page-grid-3">
          <section class="card card-pad">
            <h2 class="section-title">GPU</h2>
            <div class="kv"><span>Model</span><span>RTX 4090</span></div>
            <div class="kv"><span>VRAM</span><span>18.4 / 24 GB</span></div>
            <div class="bar-row" style="margin-top:8px"><div class="bar"><span style="width:77%"></span></div><span class="bar-pct">77%</span></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">System RAM</h2>
            <div class="kv"><span>Used</span><span>32.1 / 64 GB</span></div>
            <div class="kv"><span>Planner</span><span>ATME v2.1</span></div>
            <div class="bar-row" style="margin-top:8px"><div class="bar"><span style="width:50%"></span></div><span class="bar-pct">50%</span></div>
          </section>
          <section class="card card-pad">
            <h2 class="section-title">Benchmark</h2>
            <div class="kv"><span>Score</span><span class="green">9.4 / 10</span></div>
            <div class="kv"><span>Laatste run</span><span>14 nov 2024</span></div>
            <div class="kv"><span>Status</span><span class="tag green">Actief</span></div>
          </section>
        </div>`,
  insp: defaultInsp,
});

console.log("done");
