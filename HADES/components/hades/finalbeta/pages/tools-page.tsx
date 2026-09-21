/** FINALBETA Plugins overview — live PluginManager wiring (visual shell preserved). */
"use client";

import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  useHadesPlugins,
  type PluginCardView,
  type PluginUiStatus,
} from "@/components/hades/features/plugins/hooks/useHadesPlugins";
import { FbIcon } from "../icons";
import { McFooter } from "../media/media-chrome";
import { PR_PLUGINS_TABS, type PrPluginsTabId } from "../mocks/pr-plugins";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

const TONES = ["cyan", "green", "gold", "blue", "purple", "orange"] as const;

function toneFor(id: string): (typeof TONES)[number] {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) hash = (hash + id.charCodeAt(i) * (i + 1)) % TONES.length;
  return TONES[hash] ?? "cyan";
}

function iconFor(plugin: PluginCardView): string {
  const cat = (plugin.category || "").toLowerCase();
  if (cat.includes("trad")) return "chart";
  if (cat.includes("media")) return "play";
  if (cat.includes("research") || cat.includes("web")) return "search";
  if (cat.includes("vision") || cat.includes("image")) return "image";
  if (cat.includes("data")) return "database";
  if (plugin.name.toLowerCase().includes("chat")) return "chat";
  return "wrench";
}

function StatusIcon({ status }: { status: PluginUiStatus }) {
  if (status === "update") {
    return (
      <svg width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="currentColor" d="M12 3 2 21h20L12 3Zm0 5.5 6.2 10.5H5.8L12 8.5ZM11 12v4h2v-4h-2Zm0 5v2h2v-2h-2Z" />
      </svg>
    );
  }
  if (status === "inactive" || status === "blocked") {
    return <span className="mc-dot gray" style={{ width: 6, height: 6 }} />;
  }
  if (status === "broken") {
    return <span className="mc-dot" style={{ width: 6, height: 6, background: "#e85b5b" }} />;
  }
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="m8 12 3 3 5-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="m12 3.2 2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 15.6 7.2 18.1l.9-5.4L4.2 8.9l5.4-.8L12 3.2Z"
      />
    </svg>
  );
}

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function ToolsPage({ onNavigate }: Props) {
  const [tab, setTab] = useState<PrPluginsTabId>("overview");
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const zipInputRef = useRef<HTMLInputElement>(null);

  const {
    cards,
    stats,
    marketplace,
    loading,
    error,
    refresh,
    setEnabled,
    repair,
    update,
    installMarketplace,
    importPluginZip,
  } = useHadesPlugins({ includeMarketplace: true });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = !q
      ? cards
      : cards.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            p.description.toLowerCase().includes(q) ||
            p.tags.some((t) => t.toLowerCase().includes(q)) ||
            p.id.toLowerCase().includes(q),
        );
    return showAll ? list : list.slice(0, 12);
  }, [cards, query, showAll]);

  const selected = cards.find((c) => c.id === selectedId) ?? cards[0] ?? null;

  const categories = useMemo(() => {
    const map = new Map<string, number>();
    for (const card of cards) {
      const key = card.category || "general";
      map.set(key, (map.get(key) || 0) + 1);
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([id, count]) => ({ id, label: id, count }));
  }, [cards]);

  const marketplaceItems = useMemo(() => {
    const items = (marketplace?.items || []) as Array<Record<string, unknown>>;
    return items.slice(0, 8).map((item, index) => ({
      id: String(item.id || item.plugin_id || `mkt-${index}`),
      name: String(item.name || item.title || item.id || "Plugin"),
      version: String(item.version || "—"),
      publisher: String(item.publisher || item.author || "Marketplace"),
      rating: item.rating != null ? String(item.rating) : "—",
      description: String(item.description || ""),
    }));
  }, [marketplace]);

  const liveStats = [
    {
      id: "installed",
      label: "Geïnstalleerde plugins",
      value: loading && !cards.length ? "…" : String(stats.installed),
      hint: `${stats.enabled} enabled · ${stats.readyDisabled} ready (niet enabled)`,
      icon: "grid",
      tone: "blue" as const,
    },
    {
      id: "available",
      label: "Beschikbare plugins",
      value: stats.marketplaceCount == null ? "—" : String(stats.marketplaceCount),
      hint: marketplace?.note ? String(marketplace.note).slice(0, 48) : "in marktplaats",
      icon: "folder",
      tone: "gold" as const,
    },
    {
      id: "active",
      label: "Enabled plugins",
      value: loading && !cards.length ? "…" : String(stats.enabled),
      hint:
        stats.installed === 0
          ? "geen geïnstalleerd"
          : `${Math.round((stats.enabled / Math.max(1, stats.installed)) * 100)}% van geïnstalleerd`,
      icon: "play",
      tone: "gold" as const,
    },
    {
      id: "runtime",
      label: "Plugin runtime",
      value: stats.runtimeLabel,
      hint: stats.runtimeHint,
      icon: "line",
      tone: "green" as const,
      valueTone: stats.broken ? ("warn" as const) : ("green" as const),
    },
  ];

  async function runAction(key: string, fn: () => Promise<unknown>, okMsg: string) {
    setActionBusy(key);
    try {
      await fn();
      toast.success(okMsg);
      await refresh();
    } catch (err) {
      toast.error(errMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function onZipSelected(file: File | null) {
    if (!file) return;
    await runAction(
      "import-zip",
      () => importPluginZip(file, true, true, true),
      `Plugin geïmporteerd: ${file.name}`,
    );
  }

  const body = (
    <div className="mc-page pr-plugins-page" data-page="plugins" data-live="plugins">
      <div className="pr-plugins-welcome">
        <div>
          <h1>Plugins</h1>
          <p>
            Breid HADES uit met krachtige plugins. Installeer, beheer en ontdek nieuwe mogelijkheden.
            Ready betekent niet automatisch enabled — schakel expliciet in.
          </p>
        </div>
        <div className="pr-plugins-welcome-actions">
          <label className="pr-plugins-search">
            <FbIcon name="search" size={14} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Zoek plugins, auteur of functionaliteit..."
              aria-label="Zoek plugins"
            />
          </label>
          <input
            ref={zipInputRef}
            type="file"
            accept=".zip,.HadesPlugin,application/zip"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0] ?? null;
              e.target.value = "";
              void onZipSelected(file);
            }}
          />
          <button
            className="btn btn-outline"
            type="button"
            disabled={!!actionBusy}
            onClick={() => void refresh()}
          >
            Vernieuwen
          </button>
          <button
            className="btn btn-gold pr-plugins-install"
            type="button"
            disabled={!!actionBusy}
            onClick={() => zipInputRef.current?.click()}
          >
            + Plugin installeren
          </button>
        </div>
      </div>

      {error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Plugins laden mislukt.</strong> {error.message}
        </div>
      ) : null}

      <div className="pr-plugins-tabs" role="tablist" aria-label="Plugins secties">
        {PR_PLUGINS_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            className={`pr-plugins-tab${tab === item.id ? " active" : ""}`}
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="pr-plugins-stats">
        {liveStats.map((stat) => (
          <article key={stat.id} className="pr-plugins-stat">
            <span className={`pr-plugins-stat-ico ${stat.tone}`}>
              <FbIcon name={stat.icon} size={14} />
            </span>
            <div className="pr-plugins-stat-body">
              <div className="pr-plugins-stat-label">{stat.label}</div>
              <div className={`pr-plugins-stat-value${"valueTone" in stat && stat.valueTone ? ` ${stat.valueTone}` : ""}`}>
                {stat.value}
              </div>
              <div className="pr-plugins-stat-hint">{stat.hint}</div>
            </div>
          </article>
        ))}
      </div>

      {(tab === "overview" || tab === "installed") && (
        <section className="mc-panel pr-plugins-section">
          <div className="mc-panel-head">
            <div>
              <h2 className="pr-plugins-section-title">
                <FbIcon name="grid" size={14} />
                Geïnstalleerde plugins
              </h2>
              <p>Live state uit PluginManager — enabled, trust, health en tools.</p>
            </div>
          </div>

          {loading && !cards.length ? (
            <p className="muted" style={{ padding: 16 }}>
              Plugins laden…
            </p>
          ) : null}
          {!loading && cards.length === 0 ? (
            <p className="muted" style={{ padding: 16 }}>
              Geen plugins geïnstalleerd. Importeer een .zip / .HadesPlugin of installeer vanuit de marktplaats.
            </p>
          ) : null}

          <div className="pr-plugins-grid">
            {filtered.map((plugin) => {
              const tone = toneFor(plugin.id);
              const actionLabel = plugin.enabled ? "Uitschakelen" : "Inschakelen";
              const actionTone = plugin.enabled ? "outline" : "blue";
              return (
                <article
                  key={plugin.id}
                  className="pr-plugin-card"
                  data-plugin-id={plugin.id}
                  data-enabled={plugin.enabled ? "true" : "false"}
                  data-status={plugin.pluginStatus}
                  onClick={() => setSelectedId(plugin.id)}
                >
                  <div className="pr-plugin-card-top">
                    <span className={`pr-plugin-ico ${tone}`}>
                      <FbIcon name={iconFor(plugin)} size={16} />
                    </span>
                    <div className="pr-plugin-meta">
                      <strong>{plugin.name}</strong>
                      <small>{plugin.version}</small>
                    </div>
                    <span className={`pr-plugin-status ${plugin.status === "active" ? "active" : plugin.status === "broken" ? "update" : "inactive"}`}>
                      <StatusIcon status={plugin.status} />
                      {plugin.statusLabel}
                    </span>
                  </div>
                  <p className="pr-plugin-desc">{plugin.description}</p>
                  <div className="pr-plugin-tags">
                    {plugin.tags.map((tag) => (
                      <span key={tag} className="pr-plugin-tag">
                        {tag}
                      </span>
                    ))}
                    <span className="pr-plugin-tag">trust:{plugin.trust}</span>
                    {plugin.autonomous ? <span className="pr-plugin-tag">autonomous</span> : null}
                  </div>
                  <div className="pr-plugin-foot">
                    <span className="pr-plugin-perms">
                      <FbIcon name="shield" size={12} />
                      {plugin.permissions} machtigingen · {plugin.toolCount} tools
                    </span>
                    <div className="pr-plugin-actions">
                      {plugin.status === "broken" ? (
                        <button
                          type="button"
                          className="pr-plugin-action gold"
                          disabled={actionBusy === `repair:${plugin.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            void runAction(`repair:${plugin.id}`, () => repair(plugin.id), `${plugin.name} repair gestart`);
                          }}
                        >
                          Repair
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="pr-plugin-gear"
                        aria-label="Update"
                        disabled={!!actionBusy}
                        onClick={(e) => {
                          e.stopPropagation();
                          void runAction(`update:${plugin.id}`, () => update(plugin.id), `${plugin.name} bijgewerkt`);
                        }}
                      >
                        <FbIcon name="settings" size={13} />
                      </button>
                      <button
                        type="button"
                        className={`pr-plugin-action ${actionTone}`}
                        disabled={actionBusy === `toggle:${plugin.id}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          void runAction(
                            `toggle:${plugin.id}`,
                            () => setEnabled(plugin.id, !plugin.enabled),
                            plugin.enabled ? `${plugin.name} uitgeschakeld` : `${plugin.name} ingeschakeld`,
                          );
                        }}
                      >
                        {actionLabel}
                      </button>
                    </div>
                  </div>
                  {plugin.lastError ? (
                    <p className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                      {plugin.lastError}
                    </p>
                  ) : null}
                </article>
              );
            })}
          </div>

          {cards.length > 12 ? (
            <div className="pr-plugins-show-all">
              <button type="button" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Minder tonen" : `Toon alle geïnstalleerde plugins (${cards.length})`}
                <FbIcon name="chevron" size={12} className="chevron-down" />
              </button>
            </div>
          ) : null}
        </section>
      )}

      {(tab === "overview" || tab === "marketplace") && (
        <section className="mc-panel pr-plugins-section">
          <div className="mc-panel-head">
            <div>
              <h2 className="pr-plugins-section-title">
                <FbIcon name="bolt" size={14} style={{ color: "#eab94f" }} />
                Marktplaats
              </h2>
              <p>Lokale/catalogus marktplaats — installatie via PluginManager.</p>
            </div>
          </div>
          {!marketplaceItems.length ? (
            <p className="muted" style={{ padding: 16 }}>
              Geen marktplaats-items beschikbaar.
            </p>
          ) : (
            <div className="pr-plugins-rec-grid">
              {marketplaceItems.map((plugin) => (
                <article key={plugin.id} className="pr-rec-card">
                  <div className="pr-rec-top">
                    <span className={`pr-rec-ico ${toneFor(plugin.id)}`}>
                      <FbIcon name="download" size={15} />
                    </span>
                    <div className="pr-rec-copy">
                      <strong>{plugin.name}</strong>
                      <small>{plugin.version}</small>
                    </div>
                  </div>
                  <div className="pr-rec-meta">
                    <span>{plugin.publisher}</span>
                    <span className="pr-rec-rating">
                      <StarIcon />
                      {plugin.rating}
                    </span>
                  </div>
                  <button
                    type="button"
                    className="pr-rec-install"
                    disabled={!!actionBusy}
                    onClick={() =>
                      void runAction(
                        `mkt:${plugin.id}`,
                        () => installMarketplace(plugin.id),
                        `${plugin.name} geïnstalleerd (nog niet enabled)`,
                      )
                    }
                  >
                    <FbIcon name="download" size={12} />
                    Installeren
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === "categories" ? (
        <section className="mc-panel pr-plugins-section">
          <h2 className="pr-plugins-section-title">Categorieën (live)</h2>
          <div className="pr-plugins-cat-list" style={{ padding: 12 }}>
            {categories.length === 0 ? (
              <p className="muted">Geen categorieën — nog geen plugins.</p>
            ) : (
              categories.map((cat) => (
                <div key={cat.id} className="pr-plugins-cat-row">
                  <FbIcon name="grid" size={13} />
                  <span>{cat.label}</span>
                  <span className="count">{cat.count}</span>
                </div>
              ))
            )}
          </div>
        </section>
      ) : null}

      {tab === "permissions" || tab === "runtime" ? (
        <section className="mc-panel pr-plugins-section">
          <h2 className="pr-plugins-section-title">{tab === "permissions" ? "Machtigingen" : "Runtime"}</h2>
          <p className="muted" style={{ padding: 12 }}>
            Selecteer een plugin in Overzicht voor details. Globale policies staan onder Instellingen → Rechten &amp;
            Security.
          </p>
          {selected ? (
            <div className="mc-insp-card" style={{ margin: 12 }}>
              <div className="mc-detail-row">
                <span className="k">Plugin</span>
                <span className="v">{selected.name}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Status</span>
                <span className="v">{selected.pluginStatus}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Enabled</span>
                <span className="v">{selected.enabled ? "ja" : "nee"}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Trust</span>
                <span className="v">{selected.trust}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Health</span>
                <span className="v">{selected.health}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Autonomous</span>
                <span className="v">{selected.autonomous ? "ja" : "nee"}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Permissions</span>
                <span className="v">{(selected.raw.permissions || []).join(", ") || "—"}</span>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“More plugins. More possibilities.”</p>

      <section className="mc-insp-section">
        <div className="pr-plugins-insp-head">
          <h3 className="mc-insp-title">Plugin Runtime</h3>
          <button type="button" className="pr-plugins-insp-details" onClick={() => void refresh()}>
            Vernieuwen
          </button>
        </div>
        <div className="mc-insp-card">
          <div className="mc-detail-row">
            <span className="k">Status</span>
            <span className={`v ${stats.broken ? "" : "green"}`}>{stats.runtimeLabel}</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Installed</span>
            <span className="v">{stats.installed}</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Enabled</span>
            <span className="v">
              {stats.enabled} / {stats.installed}
            </span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Ready (niet enabled)</span>
            <span className="v">{stats.readyDisabled}</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Defect</span>
            <span className="v">{stats.broken}</span>
          </div>
          <div className="mc-detail-row">
            <span className="k">Bron</span>
            <span className="v">PluginManager /api/plugins</span>
          </div>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Selectie</h3>
        <div className="mc-insp-card">
          {selected ? (
            <>
              <div className="mc-detail-row">
                <span className="k">Naam</span>
                <span className="v">{selected.name}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Id</span>
                <span className="v">{selected.id}</span>
              </div>
              <div className="mc-detail-row">
                <span className="k">Tools</span>
                <span className="v">{selected.toolCount}</span>
              </div>
              {selected.failureState ? (
                <div className="mc-detail-row">
                  <span className="k">Failure</span>
                  <span className="v">{selected.failureState}</span>
                </div>
              ) : null}
            </>
          ) : (
            <p className="muted">Geen plugin geselecteerd.</p>
          )}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Categorieën</h3>
        <div className="mc-insp-card pr-plugins-cat-list">
          <div className="pr-plugins-cat-row gold">
            <FbIcon name="grid" size={13} />
            <span>Alle</span>
            <span className="count">{stats.installed}</span>
          </div>
          {categories.slice(0, 9).map((cat) => (
            <div key={cat.id} className="pr-plugins-cat-row">
              <FbIcon name="folder" size={13} />
              <span>{cat.label}</span>
              <span className="count">{cat.count}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="tools"
      appClassName="mc-app pr-app pr-plugins-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
