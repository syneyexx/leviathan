import { useMemo, useState } from "react";
import { mediaPageArt, mediaPageHeroes } from "../../assets/mediaPagesAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { PageHero, Panel, Pill, Spark } from "./mr-shared";

type AssetKind = "image" | "video" | "audio" | "document" | "template" | "3d" | "other";

type LibraryAsset = {
  id: string;
  name: string;
  kind: AssetKind;
  size: string;
  sizeMb: number;
  starred: boolean;
  thumb: string;
};

const TABS = [
  { id: "all", label: "Alle Assets" },
  { id: "image", label: "Afbeeldingen" },
  { id: "video", label: "Video" },
  { id: "audio", label: "Audio" },
  { id: "document", label: "Documenten" },
  { id: "template", label: "Templates" },
  { id: "3d", label: "3D" },
  { id: "other", label: "Overig" },
] as const;

const FOLDERS = [
  { id: "all", label: "Alle Assets", count: "124.680" },
  { id: "merken", label: "Merken", count: "18.240" },
  { id: "campagnes", label: "Campagnes", count: "42.110" },
  { id: "types", label: "Content Types", count: "31.904" },
  { id: "jaar", label: "Jaar", count: "124.680" },
  { id: "smart", label: "Smart Collecties", count: "2.384" },
] as const;

const ASSETS: LibraryAsset[] = [
  { id: "a1", name: "leviathan_hero_01.jpg", kind: "image", size: "JPG · 4.2 MB", sizeMb: 4.2, starred: true, thumb: mediaPageArt.libraryTiles[0] },
  { id: "a2", name: "campaign_reel_cut.mp4", kind: "video", size: "MP4 · 86 MB", sizeMb: 86, starred: false, thumb: mediaPageArt.libraryTiles[1] },
  { id: "a3", name: "voiceover_nl_v3.wav", kind: "audio", size: "WAV · 28 MB", sizeMb: 28, starred: false, thumb: mediaPageArt.libraryTiles[2] },
  { id: "a4", name: "brief_q2_outline.pdf", kind: "document", size: "PDF · 1.1 MB", sizeMb: 1.1, starred: true, thumb: mediaPageArt.libraryTiles[3] },
  { id: "a5", name: "story_template_gold.psd", kind: "template", size: "PSD · 62 MB", sizeMb: 62, starred: false, thumb: mediaPageArt.libraryTiles[4] },
  { id: "a6", name: "product_scan_01.glb", kind: "3d", size: "GLB · 41 MB", sizeMb: 41, starred: false, thumb: mediaPageArt.libraryTiles[5] },
  { id: "a7", name: "moodboard_night.png", kind: "image", size: "PNG · 9.8 MB", sizeMb: 9.8, starred: true, thumb: mediaPageArt.libraryTiles[6] },
  { id: "a8", name: "caption_pack_raw.txt", kind: "other", size: "TXT · 42 KB", sizeMb: 0.04, starred: false, thumb: mediaPageArt.libraryTiles[7] },
];

const PREVIEW_META = [
  { label: "Bestandsnaam", value: "leviathan_hero_01.jpg" },
  { label: "Type", value: "Afbeelding · JPG" },
  { label: "Afmetingen", value: "3840 × 2160" },
  { label: "Grootte", value: "4.2 MB" },
  { label: "Auteur", value: "Studio LEVIATHAN" },
  { label: "Aangemaakt", value: "12 mrt 2026 · 14:22" },
  { label: "Laatst gebruikt", value: "Vandaag · 09:41" },
  { label: "Licentie", value: "Intern · Commercial OK" },
] as const;

const USAGE = [
  { when: "Vandaag 09:41", where: "Publicatie wachtrij · Discipline Changes" },
  { when: "Gisteren 18:02", where: "Campagne · Night Markets" },
  { when: "10 mrt 2026", where: "Template · Story Gold" },
] as const;

const CAMPAIGNS = ["Night Markets Q2", "Discipline Series", "Brand Kit Refresh"] as const;

export function MediaLibraryPage() {
  const toast = useAppToast();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("all");
  const [folder, setFolder] = useState<(typeof FOLDERS)[number]["id"]>("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("a1");
  const [checked, setChecked] = useState<Record<string, boolean>>({ a1: true, a2: true, a7: true });
  const [stars, setStars] = useState<Record<string, boolean>>(
    Object.fromEntries(ASSETS.map((a) => [a.id, a.starred])),
  );

  const filtered = useMemo(() => {
    return ASSETS.filter((asset) => {
      if (tab !== "all" && asset.kind !== tab) return false;
      if (!query.trim()) return true;
      return asset.name.toLowerCase().includes(query.trim().toLowerCase());
    });
  }, [tab, query]);

  const selected = ASSETS.find((a) => a.id === selectedId) ?? ASSETS[0];
  const selectedList = ASSETS.filter((a) => checked[a.id]);
  const selectedMb = selectedList.reduce((sum, a) => sum + a.sizeMb, 0);
  const storagePct = Math.round((842 / 2000) * 100);

  const toggleCheck = (id: string) => {
    setChecked((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Library Mode"
      searchPlaceholder="Zoek bestanden, tags, campagnes, auteurs of content..."
      systemItems={["MEMORY ONLINE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--media-research"
    >
      <main className="lv-main lv-mr-main">
        <PageHero image={mediaPageHeroes.library} title="BIBLIOTHEEK" imageOnly />

        <section className="lv-mr-kpi-row">
          <article className="lv-mr-kpi is-cyan">
            <div className="lbl">Totaal Assets</div>
            <div className="val">124.680</div>
            <div className="sub">
              <span className="delta">↑ +3.2%</span>
              <Spark points={[18, 22, 20, 28, 32, 30, 36, 40]} />
            </div>
          </article>
          <article className="lv-mr-kpi is-gold">
            <div className="lbl">Recent</div>
            <div className="val">2.384</div>
            <div className="sub">
              <span className="delta">↑ +186</span>
              <Spark points={[10, 14, 12, 18, 22, 20, 26, 30]} color="#f0c875" />
            </div>
          </article>
          <article className="lv-mr-kpi is-green">
            <div className="lbl">Goedgekeurd</div>
            <div className="val">98.6%</div>
            <div className="sub">
              <Pill tone="green">● LIVE</Pill>
              <Spark points={[88, 90, 91, 93, 94, 96, 97, 99]} color="#4ade80" />
            </div>
          </article>
          <article className="lv-mr-kpi is-cyan">
            <div className="lbl">Opslag</div>
            <div className="val" style={{ fontSize: 20 }}>
              842GB<span className="lv-mr-muted" style={{ fontSize: 14, fontWeight: 500 }}>
                {" "}/ 2TB
              </span>
            </div>
            <div className="lv-mr-bar" style={{ marginTop: 6 }} aria-label={`Opslag ${storagePct}%`}>
              <span style={{ width: `${storagePct}%`, background: "#22c9d6" }} />
            </div>
          </article>
          <aside className="lv-mr-quote-card" style={{ flexDirection: "column", gap: 10, alignItems: "stretch" }}>
            <span style={{ fontStyle: "normal", fontSize: 11, letterSpacing: "0.08em", color: "#8ea3af" }}>
              QUICK ACTION
            </span>
            <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Upload Asset")}>
              ↑ Upload Asset
            </button>
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
                {t.label}
              </button>
            ))}
          </div>
        </Panel>

        <section className="lv-ml-layout">
          <Panel title="Mappen">
            <div className="lv-ml-tree">
              {FOLDERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={folder === f.id ? "is-active" : undefined}
                  onClick={() => {
                    setFolder(f.id);
                    toast(`Map: ${f.label}`);
                  }}
                >
                  <span>{f.label}</span>
                  <span className="lv-mr-muted">{f.count}</span>
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title={`Assets · ${filtered.length}`}
            action={
              <div className="lv-mr-toolbar" style={{ margin: 0, padding: 0, border: 0 }}>
                <input
                  className="lv-mr-input"
                  style={{ minWidth: 160, flex: 1 }}
                  placeholder="Zoek in bibliotheek..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <select className="lv-mr-select" defaultValue="recent" aria-label="Filter">
                  <option value="recent">Recent</option>
                  <option value="name">Naam</option>
                  <option value="size">Grootte</option>
                  <option value="approved">Goedgekeurd</option>
                </select>
                <select className="lv-mr-select" defaultValue="all" aria-label="Status">
                  <option value="all">Alle statussen</option>
                  <option value="approved">Goedgekeurd</option>
                  <option value="review">In review</option>
                  <option value="draft">Concept</option>
                </select>
              </div>
            }
          >
            <div className="lv-ml-grid">
              {filtered.map((asset) => (
                <button
                  key={asset.id}
                  type="button"
                  className={`lv-ml-card${asset.id === selected.id ? " is-active" : ""}`}
                  onClick={() => setSelectedId(asset.id)}
                >
                  <div className="lv-ml-card-media">
                    <img src={asset.thumb} alt="" />
                    <label
                      style={{
                        position: "absolute",
                        top: 8,
                        left: 8,
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        background: "rgba(0,0,0,0.55)",
                        borderRadius: 4,
                        padding: "2px 4px",
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={Boolean(checked[asset.id])}
                        onChange={() => toggleCheck(asset.id)}
                        aria-label={`Selecteer ${asset.name}`}
                      />
                    </label>
                    <button
                      type="button"
                      aria-label={stars[asset.id] ? "Verwijder favoriet" : "Maak favoriet"}
                      onClick={(e) => {
                        e.stopPropagation();
                        setStars((prev) => ({ ...prev, [asset.id]: !prev[asset.id] }));
                      }}
                      style={{
                        position: "absolute",
                        top: 6,
                        right: 6,
                        border: 0,
                        background: "rgba(0,0,0,0.45)",
                        color: stars[asset.id] ? "#f0c875" : "#9db0bc",
                        borderRadius: 4,
                        cursor: "pointer",
                        width: 28,
                        height: 28,
                      }}
                    >
                      {stars[asset.id] ? "★" : "☆"}
                    </button>
                  </div>
                  <div className="lv-ml-card-body">
                    <strong>{asset.name}</strong>
                    <span className="lv-mr-muted">{asset.size}</span>
                  </div>
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title="ASSET PREVIEW"
            action={<Pill tone="green">Goedgekeurd</Pill>}
          >
            <div className="lv-ml-preview">
              <img src={mediaPageArt.libraryPreview} alt="" />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
              <strong style={{ color: "#f0ebe3" }}>{selected.name}</strong>
              <button type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast("Bewerken")}>
                Bewerken
              </button>
            </div>
            <div className="lv-ml-meta">
              {PREVIEW_META.map((row) => (
                <div key={row.label}>
                  <span className="lv-mr-muted">{row.label}</span>
                  <strong>{row.value}</strong>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 8 }}>
                Gebruikshistorie
              </div>
              {USAGE.map((u) => (
                <div key={u.when} style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12, padding: "4px 0", borderBottom: "1px solid rgba(40,60,80,0.3)" }}>
                  <span className="lv-mr-muted">{u.when}</span>
                  <span>{u.where}</span>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="lv-mr-panel-title" style={{ marginBottom: 8 }}>
                Gekoppelde campagnes
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {CAMPAIGNS.map((c) => (
                  <button key={c} type="button" className="lv-mr-btn lv-mr-btn--ghost" onClick={() => toast(c)}>
                    {c}
                  </button>
                ))}
              </div>
            </div>
          </Panel>
        </section>

        {selectedList.length > 0 ? (
          <div className="lv-ml-fab" role="status">
            <strong style={{ color: "#f0ebe3", marginRight: 8 }}>
              {selectedList.length} items geselecteerd | {selectedMb < 1 ? `${Math.round(selectedMb * 1000)} KB` : `${Math.round(selectedMb)} MB`}
            </strong>
            <button type="button" className="lv-mr-btn" onClick={() => toast("Download")}>
              Download
            </button>
            <button type="button" className="lv-mr-btn" onClick={() => toast("Verplaats")}>
              Verplaats
            </button>
            <button type="button" className="lv-mr-btn" onClick={() => toast("Tag")}>
              Tag
            </button>
            <button type="button" className="lv-mr-btn lv-mr-btn--gold" onClick={() => toast("Goedkeuren")}>
              Goedkeuren
            </button>
            <button type="button" className="lv-mr-btn" onClick={() => toast("Verwijderen")}>
              Verwijderen
            </button>
          </div>
        ) : null}
      </main>
    </AppShell>
  );
}
