import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type {
  DownloadJob,
  GatewaySnapshot,
  ModelDescriptor,
  ModelProfile,
  ModelProvider,
  ModelsStatus,
  RouterConfig,
  VerifiedCapability,
} from "../../types/api";
import type { FilterKey, SortKey } from "./types";
import { ModelCatalog } from "./ModelCatalog";
import { ModelInspector } from "./ModelInspector";
import { ModelStatusCards } from "./ModelStatusCards";
import { ProviderManager } from "./ProviderManager";
import { ModelGatewayPanel } from "./ModelGatewayPanel";
import { ModelRouterPanel } from "./ModelRouterPanel";
import { ModelImportDialog } from "./ModelImportDialog";
import { ModelDownloadManager } from "./ModelDownloadManager";

export type { FilterKey, SortKey } from "./types";

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function ModelsPage() {
  const toast = useAppToast();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [status, setStatus] = useState<ModelsStatus | null>(null);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [gateway, setGateway] = useState<GatewaySnapshot | null>(null);
  const [router, setRouter] = useState<RouterConfig | null>(null);
  const [downloads, setDownloads] = useState<DownloadJob[]>([]);
  const [telemetry, setTelemetry] = useState<Record<string, unknown> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [profile, setProfile] = useState<ModelProfile | null>(null);
  const [capabilities, setCapabilities] = useState<VerifiedCapability[]>([]);
  const [preflight, setPreflight] = useState<Record<string, unknown> | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<SortKey>("name");
  const [busy, setBusy] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<
    | "overview"
    | "capabilities"
    | "profile"
    | "runtime"
    | "resources"
    | "benchmarks"
    | "diagnostics"
    | "test"
  >("overview");

  const selected = useMemo(
    () => models.find((m) => m.id === selectedId) ?? null,
    [models, selectedId],
  );

  const providerFilters = useMemo(() => {
    const types = new Set(providers.map((p) => p.type));
    return Array.from(types);
  }, [providers]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, providersRes, gatewayRes, routerRes, downloadsRes, statusRes] = await Promise.all([
        api.listModels(),
        api.listModelProviders(),
        api.getGateway(),
        api.getRouter(),
        api.listModelDownloads(),
        api.modelsStatus(),
      ]);
      setModels(list.models);
      setStatus(list.status);
      setProviders(providersRes.providers);
      setGateway(gatewayRes.gateway);
      setRouter(routerRes.router);
      setDownloads(downloadsRes.downloads);
      setTelemetry(statusRes.telemetry);
      if (!selectedId && list.models.length > 0) {
        const active = list.models.find((m) => m.active) ?? list.models[0];
        setSelectedId(active.id);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load models");
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void loadAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- initial load only

  useEffect(() => {
    if (!selectedId) {
      setProfile(null);
      setCapabilities([]);
      setPreflight(null);
      setSelectedProvider(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await api.getModel(selectedId);
        if (cancelled) return;
        setProfile(detail.profile);
        setCapabilities(detail.capabilities);
        setPreflight(detail.preflight);
        setSelectedProvider(detail.provider);
      } catch (err) {
        if (!cancelled) {
          toast(err instanceof ApiError ? err.message : "Failed to load model detail");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, toast]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = models.filter((model) => {
      if (filter === "local" && !["local", "imported", "downloaded"].includes(model.source)) return false;
      if (filter === "remote" && model.source !== "remote") return false;
      if (filter === "api" && model.source !== "api") return false;
      if (filter === "loaded" && model.loaded !== true) return false;
      if (filter === "available" && model.lifecycleState !== "available" && model.lifecycleState !== "active")
        return false;
      if (filter === "active" && !model.active) return false;
      if (filter === "offline" && model.lifecycleState !== "offline" && model.health !== "offline") return false;
      if (filter === "error" && model.lifecycleState !== "error" && model.health !== "error") return false;
      if (providerFilters.includes(filter) && model.runtimeId !== filter && !model.providerId.includes(filter)) {
        const provider = providers.find((p) => p.id === model.providerId);
        if (!provider || provider.type !== filter) return false;
      }
      if (!q) return true;
      const hay = [
        model.id,
        model.displayName,
        model.providerId,
        model.family ?? "",
        model.architecture ?? "",
        model.format ?? "",
        ...(model.tags ?? []),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });

    const nullLast = <T,>(a: T | null | undefined, b: T | null | undefined, cmp: (x: T, y: T) => number) => {
      if (a == null && b == null) return 0;
      if (a == null) return 1;
      if (b == null) return -1;
      return cmp(a, b);
    };

    rows = [...rows].sort((a, b) => {
      switch (sort) {
        case "provider":
          return a.providerId.localeCompare(b.providerId);
        case "recent":
          return nullLast(a.lastUsedAt, b.lastUsedAt, (x, y) => y.localeCompare(x));
        case "size":
          return nullLast(a.diskSizeBytes, b.diskSizeBytes, (x, y) => y - x);
        case "parameters":
          return nullLast(a.parameterCount, b.parameterCount, (x, y) => y - x);
        case "context":
          return nullLast(a.contextWindow, b.contextWindow, (x, y) => y - x);
        case "status":
          return a.lifecycleState.localeCompare(b.lifecycleState);
        case "name":
        default:
          return a.displayName.localeCompare(b.displayName);
      }
    });
    return rows;
  }, [models, query, filter, sort, providerFilters, providers]);

  async function onRefresh() {
    setBusy(true);
    try {
      const result = await api.refreshModels();
      setModels(result.models);
      setStatus(result.status);
      toast("Discovery refresh complete");
      const providersRes = await api.listModelProviders();
      setProviders(providersRes.providers);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Refresh failed");
    } finally {
      setBusy(false);
    }
  }

  async function onActivate(modelId: string) {
    setBusy(true);
    try {
      const result = await api.activateModel(modelId);
      toast(`Activated ${result.model.displayName}`);
      await loadAll();
      setSelectedId(modelId);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Activation failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveProfile(next: ModelProfile, activate: boolean) {
    if (!selectedId) return;
    setBusy(true);
    try {
      const result = await api.saveModelProfile(selectedId, {
        temperature: next.temperature,
        topP: next.topP,
        topK: next.topK,
        maxTokens: next.maxTokens,
        repeatPenalty: next.repeatPenalty,
        seed: next.seed,
        systemPrompt: next.systemPrompt,
        activate,
      });
      setProfile(result.profile);
      toast(activate ? "Profile saved & activated" : "Profile saved");
      await loadAll();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Save failed");
      throw err;
    } finally {
      setBusy(false);
    }
  }

  async function onLoad(modelId: string) {
    setBusy(true);
    try {
      await api.loadModel(modelId);
      toast("Load requested");
      await loadAll();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Load failed");
    } finally {
      setBusy(false);
    }
  }

  async function onUnload(modelId: string) {
    setBusy(true);
    try {
      await api.unloadModel(modelId);
      toast("Unload requested");
      await loadAll();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Unload failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(modelId: string) {
    if (!window.confirm(`Remove model ${modelId} from the registry?`)) return;
    setBusy(true);
    try {
      await api.deleteModel(modelId);
      toast("Model removed");
      setSelectedId(null);
      await loadAll();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Remove failed");
    } finally {
      setBusy(false);
    }
  }

  async function onProbe(modelId: string) {
    setBusy(true);
    try {
      const result = await api.probeModel(modelId);
      setCapabilities(result.results);
      toast("Capability probe complete");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Probe failed");
    } finally {
      setBusy(false);
    }
  }

  async function onBenchmark(modelId: string) {
    setBusy(true);
    try {
      const result = await api.benchmarkModel(modelId);
      toast(`Benchmark latency: ${dash(result.benchmark.requestLatencyMs as number)} ms`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Benchmark failed");
    } finally {
      setBusy(false);
    }
  }

  const offlineProviders = status?.offlineProviders ?? [];

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Models Mode"
      searchPlaceholder="Search models, tags, capabilities..."
      pageClass="lv-app--models"
    >
      <main className="lv-main lv-models-main">
        <header className="lv-models-header">
          <div>
            <p className="lv-models-kicker">POWER INTELLIGENCE.</p>
            <h1 className="lv-models-title">MODELS</h1>
          </div>
          <div className="lv-models-header-actions">
            <button className="lv-btn" type="button" disabled={busy || loading} onClick={() => void onRefresh()}>
              Refresh
            </button>
            <button className="lv-btn" type="button" onClick={() => setShowImport(true)}>
              Import / Download
            </button>
            <Link className="lv-btn lv-btn-gold" to="/training">
              Open Model Training
            </Link>
          </div>
        </header>

        <SubMenu />

        <ModelStatusCards status={status} loading={loading} />

        {error ? (
          <div className="lv-models-banner is-error" role="alert">
            <strong>Error</strong>
            <span>{error}</span>
            <button className="lv-btn" type="button" onClick={() => void loadAll()}>
              Retry
            </button>
          </div>
        ) : null}

        {offlineProviders.length > 0 ? (
          <div className="lv-models-banner is-warn" role="status">
            <strong>RUNTIME OFFLINE</strong>
            <span>
              {offlineProviders
                .map((p) => `${p.name} (${p.endpoint}) — ${p.lastError ?? p.health}`)
                .join(" · ")}
            </span>
            <button className="lv-btn" type="button" onClick={() => void onRefresh()}>
              Retry discovery
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className="lv-models-banner" role="status">
            Discovering providers &amp; loading registry…
          </div>
        ) : null}

        {!loading && models.length === 0 ? (
          <div className="lv-models-empty">
            <h2>NO MODELS AVAILABLE</h2>
            <p>Connect a runtime, import a local file, or download a model.</p>
            <div className="lv-models-empty-actions">
              <button className="lv-btn lv-btn-gold" type="button" onClick={() => setShowImport(true)}>
                Import Local Model
              </button>
              <button className="lv-btn" type="button" onClick={() => setShowImport(true)}>
                Download Model
              </button>
              <button className="lv-btn" type="button" onClick={() => void onRefresh()}>
                Connect Runtime
              </button>
            </div>
          </div>
        ) : (
          <ModelCatalog
            rows={filtered}
            selectedId={selectedId}
            query={query}
            filter={filter}
            sort={sort}
            providerFilters={providerFilters}
            onQuery={setQuery}
            onFilter={setFilter}
            onSort={setSort}
            onSelect={setSelectedId}
            onActivate={(id) => void onActivate(id)}
            onLoad={(id) => void onLoad(id)}
            onUnload={(id) => void onUnload(id)}
            providers={providers}
            busy={busy}
          />
        )}

        {selected && profile ? (
          <ModelInspector
            model={selected}
            profile={profile}
            capabilities={capabilities}
            provider={selectedProvider}
            preflight={preflight}
            tab={inspectorTab}
            onTab={setInspectorTab}
            onSaveProfile={onSaveProfile}
            onActivate={() => void onActivate(selected.id)}
            onLoad={() => void onLoad(selected.id)}
            onUnload={() => void onUnload(selected.id)}
            onDelete={() => void onDelete(selected.id)}
            onProbe={() => void onProbe(selected.id)}
            onBenchmark={() => void onBenchmark(selected.id)}
            busy={busy}
          />
        ) : null}

        <div className="lv-models-panels">
          <ModelGatewayPanel gateway={gateway} />
          {router ? (
            <ModelRouterPanel
              router={router}
              models={models}
              onSave={async (next) => {
                const saved = await api.saveRouter(next);
                setRouter(saved.router);
                toast("Router saved");
              }}
            />
          ) : null}
        </div>

        <ProviderManager
          providers={providers}
          onChanged={async () => {
            await loadAll();
          }}
        />

        <ModelDownloadManager
          downloads={downloads}
          onRefresh={async () => {
            const res = await api.listModelDownloads();
            setDownloads(res.downloads);
          }}
          onCancel={async (id) => {
            await api.cancelModelDownload(id);
            const res = await api.listModelDownloads();
            setDownloads(res.downloads);
          }}
        />

        {telemetry && telemetry.available === false ? (
          <p className="lv-muted lv-models-telemetry-note">Telemetry unavailable</p>
        ) : null}
      </main>

      {showImport ? (
        <ModelImportDialog
          providers={providers}
          onClose={() => setShowImport(false)}
          onDone={async () => {
            setShowImport(false);
            await loadAll();
            const res = await api.listModelDownloads();
            setDownloads(res.downloads);
          }}
        />
      ) : null}
    </AppShell>
  );
}
