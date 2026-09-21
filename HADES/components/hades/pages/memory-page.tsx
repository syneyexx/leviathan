"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Boxes, BrainCircuit, Check, Database, Download, Import, Loader2, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, ProgressRow, StatCard, StatusBadge } from "@/components/hades/ui";
import { formatBytes, formatDate, hadesApi, MemoriesResponse, MemoryItem, AppSettings } from "@/lib/hades-api";
import { readHashSelection } from "@/lib/hash-query";

type MemoryScope = AppSettings["memory_default_scope"];
type MemoryDraft = Omit<MemoryItem, "id" | "created_at" | "updated_at">;
const emptyDraft = (scope: MemoryScope = "project"): MemoryDraft => ({
  title: "",
  content: "",
  summary: "",
  collection: "Algemeen",
  tags: [],
  source: "Handmatig",
  scope,
});

export function MemoryPage() {
  const [data, setData] = useState<MemoriesResponse>({ items: [], stats: { items: 0, collections: 0, indexed: 0, database_bytes: 0 }, collections: [] });
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<MemoryDraft>(emptyDraft());
  const [tagText, setTagText] = useState("");
  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState("all");
  const [scopeFilter, setScopeFilter] = useState<"all" | MemoryScope>("all");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [retrievalQuery, setRetrievalQuery] = useState("In welke taal communiceert HADES?");
  const [matches, setMatches] = useState<Array<MemoryItem & { score: number }>>([]);
  const [history, setHistory] = useState<MemoryItem[]>([]);
  const [defaultScope, setDefaultScope] = useState<MemoryScope>("project");
  const [scopeSaving, setScopeSaving] = useState(false);
  const [proposals, setProposals] = useState<Array<Record<string, unknown>>>([]);
  const [scanning, setScanning] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const packInput = useRef<HTMLInputElement>(null);

  const selected = useMemo(() => data.items.find((item) => item.id === selectedId), [data.items, selectedId]);

  const load = useCallback(async (search = query, selectedCollection = collection, selectedScope = scopeFilter) => {
    setLoading(true);
    try {
      const result = await hadesApi.memories(
        search,
        selectedCollection === "all" ? "" : selectedCollection,
        selectedScope === "all" ? "" : selectedScope,
      );
      setData(result);
      const deeplinkId = readHashSelection(["id"]);
      setSelectedId((current) => {
        const preferred = deeplinkId && result.items.some((item) => item.id === deeplinkId) ? deeplinkId : current;
        return result.items.some((item) => item.id === preferred) ? preferred : result.items[0]?.id ?? "";
      });
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Geheugen laden is mislukt.");
    } finally {
      setLoading(false);
    }
  }, [collection, query, scopeFilter]);

  useEffect(() => {
    const applyDeeplink = () => {
      const deeplinkId = readHashSelection(["id"]);
      if (!deeplinkId) return;
      setSelectedId((current) => (data.items.some((item) => item.id === deeplinkId) ? deeplinkId : current));
    };
    applyDeeplink();
    window.addEventListener("hashchange", applyDeeplink);
    window.addEventListener("popstate", applyDeeplink);
    return () => {
      window.removeEventListener("hashchange", applyDeeplink);
      window.removeEventListener("popstate", applyDeeplink);
    };
  }, [data.items]);

  useEffect(() => {
    void hadesApi.settings()
      .then((result) => setDefaultScope(result.values.memory_default_scope))
      .catch(() => undefined);
  }, []);

  const loadProposals = useCallback(async () => {
    try {
      setProposals(await hadesApi.memoryProposals());
    } catch {
      setProposals([]);
    }
  }, []);

  useEffect(() => {
    void loadProposals();
  }, [loadProposals]);

  const runSleepScan = async () => {
    setScanning(true);
    try {
      const result = await hadesApi.scanMemoryProposals();
      await loadProposals();
      toast.success(
        result.auto_written
          ? "Scan onverwacht schreef memory — controleer."
          : `Scan klaar: ${result.created} kandidaat(en) in inbox (geen auto-write).`
      );
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Memory-scan mislukt.");
    } finally {
      setScanning(false);
    }
  };

  const decideProposal = async (id: string, action: "accept" | "reject") => {
    try {
      await hadesApi.decideMemoryProposal(id, action);
      await loadProposals();
      await load();
      toast.success(action === "accept" ? "Voorstel geaccepteerd." : "Voorstel afgewezen.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Beslissing mislukt.");
    }
  };

  const saveDefaultScope = async (scope: MemoryScope) => {
    setScopeSaving(true);
    try {
      const latest = await hadesApi.settings();
      const saved = await hadesApi.saveSettings({ ...latest.values, memory_default_scope: scope });
      setDefaultScope(saved.values.memory_default_scope);
      toast.success("Standaard memory-scope opgeslagen.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Memory-scope opslaan mislukt.");
    } finally {
      setScopeSaving(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!selected) return;
      setDraft({
        title: selected.title,
        content: selected.content,
        summary: selected.summary,
        collection: selected.collection,
        tags: selected.tags,
        source: selected.source,
        scope: selected.scope || defaultScope,
      });
      setTagText(selected.tags.join(", "));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selected, defaultScope]);

  useEffect(() => {
    if (!selectedId) {
      setHistory([]);
      return;
    }
    void hadesApi.memoryHistory(selectedId)
      .then((result) => setHistory(result.items))
      .catch((reason) => {
        setHistory([]);
        toast.error(reason instanceof Error ? reason.message : "Geschiedenis laden mislukt.");
      });
  }, [selectedId]);

  const select = (item: MemoryItem) => {
    setSelectedId(item.id);
  };

  const startNew = () => {
    setSelectedId("");
    setDraft(emptyDraft(defaultScope));
    setTagText("");
    setHistory([]);
  };

  const draftPayload = () => ({
    ...draft,
    scope: draft.scope || defaultScope,
    tags: tagText.split(",").map((tag) => tag.trim()).filter(Boolean),
  });

  const save = async () => {
    if (!draft.title.trim() || !draft.content.trim()) return;
    setSaving(true);
    const values = draftPayload();
    try {
      const item = selectedId ? await hadesApi.updateMemory(selectedId, values) : await hadesApi.createMemory(values);
      await load();
      setSelectedId(item.id);
      toast.success(selectedId ? "Geheugen bijgewerkt." : "Geheugen toegevoegd.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  };

  const supersede = async () => {
    if (!selectedId || !draft.title.trim() || !draft.content.trim()) return;
    setSaving(true);
    try {
      const values = draftPayload();
      const item = await hadesApi.supersedeMemory(selectedId, values);
      await load();
      setSelectedId(item.id);
      toast.success("Nieuwe memory-versie opgeslagen; vorige versie is superseded.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Memory vervangen is mislukt.");
    } finally { setSaving(false); }
  };

  const remove = async () => {
    if (!selectedId) return;
    try {
      const preview = await hadesApi.forgetMemoryScope({ memory_id: selectedId, include_derived: true, preview_only: true });
      await hadesApi.forgetMemoryScope({ memory_id: selectedId, include_derived: true, preview_only: false });
      setSelectedId("");
      await load();
      const previewObj = (preview.preview || {}) as { memories?: string[] };
      const count = Array.isArray(previewObj.memories) ? previewObj.memories.length : 1;
      toast.success(`Geheugen vergeten (${count} versie(s) in supersession-keten).`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Verwijderen is mislukt.");
    }
  };

  const exportItems = async () => {
    try {
      const payload = await hadesApi.exportMemories();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `hades-geheugen-${new Date().toISOString().slice(0, 10)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Exporteren is mislukt.");
    }
  };

  const exportKnowledgePack = async () => {
    try {
      const pack = await hadesApi.exportKnowledgePack(500);
      const blob = new Blob([JSON.stringify(pack, null, 2)], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `hades-knowledge-pack-${new Date().toISOString().slice(0, 10)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      const total =
        Number(pack.memory_count || 0)
        + Number(pack.knowledge_count || 0)
        + Number(pack.agent_count || 0)
        + Number(pack.decision_count || 0);
      if (total > 0) {
        toast.success(
          `Knowledge pack: ${pack.memory_count} memories, ${pack.knowledge_count} bronnen`
          + (pack.agent_count != null ? `, ${pack.agent_count} agents` : "")
          + (pack.decision_count != null ? `, ${pack.decision_count} besluiten` : "")
          + ".",
        );
      } else {
        toast.message("Knowledge pack geëxporteerd maar leeg (0 items).");
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Knowledge pack exporteren mislukt.");
    }
  };

  const importItems = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as { items?: MemoryItem[] } | MemoryItem[];
      const items = Array.isArray(parsed) ? parsed : parsed.items;
      if (!Array.isArray(items) || !items.length) throw new Error("Dit bestand bevat geen geheugenitems.");
      const clean = items.map(({ title, content, summary = "", collection = "Algemeen", tags = [], source = "Import", scope = defaultScope }) => ({
        title, content, summary, collection, tags, source, scope: scope || defaultScope,
      }));
      const result = await hadesApi.importMemories(clean);
      await load();
      if (!result.imported || result.imported <= 0) {
        toast.message("Geen geheugenitems geïmporteerd.");
      } else {
        toast.success(`${result.imported} geheugenitem(s) geïmporteerd.`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Importeren is mislukt.");
    }
  };

  const importKnowledgePack = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const pack = JSON.parse(await file.text()) as Record<string, unknown>;
      if (!pack || typeof pack !== "object") throw new Error("Ongeldig knowledge pack.");
      const memories = Array.isArray(pack.memories) ? pack.memories : [];
      const knowledge_sources = Array.isArray(pack.knowledge_sources) ? pack.knowledge_sources : [];
      const agents = Array.isArray(pack.agents) ? pack.agents : [];
      if (!memories.length && !knowledge_sources.length && !agents.length) {
        toast.error("Knowledge pack is leeg (geen memories, bronnen of agents).");
        return;
      }
      const result = await hadesApi.importKnowledgePack({
        format: pack.format,
        memories: memories.map((item) => {
          const row = item as MemoryItem;
          return {
            title: row.title,
            content: row.content,
            summary: row.summary || "",
            collection: row.collection || "Algemeen",
            tags: row.tags || [],
            source: row.source || "Pack import",
            scope: row.scope || defaultScope,
          };
        }),
        knowledge_sources,
        agents,
        import_memories: true,
        import_knowledge_stubs: true,
        import_agent_states: true,
      });
      await load();
      const importedTotal =
        Number(result.imported_memories || 0)
        + Number(result.imported_knowledge_stubs || 0)
        + Number(result.updated_agents || 0);
      if (importedTotal <= 0) {
        toast.error("Pack import leverde 0 items op.");
        return;
      }
      toast.success(
        `Pack geïmporteerd: ${result.imported_memories} memories, ${result.imported_knowledge_stubs} bron-stubs`
        + (result.updated_agents ? `, ${result.updated_agents} agents` : "")
        + ". Chunks blijven lokaal te herindexeren.",
      );
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Knowledge pack importeren mislukt.");
    }
  };

  const retrieve = async () => {
    if (!retrievalQuery.trim()) return;
    try {
      const result = await hadesApi.retrieveMemory(retrievalQuery);
      setMatches(result.matches);
      if (!result.matches.length) toast.info("Geen relevante lokale match gevonden.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Retrieval-test is mislukt.");
    }
  };

  const scopeLabel = (scope?: string | null) => {
    if (scope === "session") return "Sessie";
    if (scope === "global") return "Globaal";
    return "Project";
  };

  return (
    <div className="page page-memory">
      <PageHeader
        title="Geheugen"
        description="Scoped lokale feiten (session/project/global) met supersession, forget en knowledge packs."
        actions={
          <>
            <input ref={fileInput} className="visually-hidden" type="file" accept="application/json,.json" onChange={importItems} />
            <input ref={packInput} className="visually-hidden" type="file" accept="application/json,.json" onChange={importKnowledgePack} />
            <Button variant="outline" onClick={() => fileInput.current?.click()}><Import />Importeren</Button>
            <Button variant="outline" onClick={() => packInput.current?.click()}><Import />Pack importeren</Button>
            <Button onClick={startNew}><Plus />Nieuw geheugen</Button>
          </>
        }
      />
      <section className="stat-grid four">
        <StatCard label="Items" value={String(data.stats.items)} note="Actief in SQLite" icon={<BrainCircuit />} />
        <StatCard label="Collecties" value={String(data.stats.collections)} note="Doorzoekbaar" icon={<Boxes />} />
        <StatCard label="Historisch" value={String(data.stats.historical ?? 0)} note="Superseded/forgotten" icon={<Check />} />
        <StatCard label="Database" value={formatBytes(data.stats.database_bytes)} note="SQLite · lokaal" icon={<Database />} />
      </section>
      <Panel title="Standaard memory-scope" actions={<StatusBadge>{defaultScope}</StatusBadge>}>
        <p className="panel-copy">Bepaalt de standaard scope voor nieuwe memories en /remember-promoties (session, project of global).</p>
        <div className="memory-toolbar" style={{ marginTop: ".5rem" }}>
          <Select value={defaultScope} onValueChange={(value: MemoryScope) => void saveDefaultScope(value)} disabled={scopeSaving}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="session">Sessie</SelectItem>
              <SelectItem value="project">Project</SelectItem>
              <SelectItem value="global">Globaal</SelectItem>
            </SelectContent>
          </Select>
          {scopeSaving ? <Loader2 className="spin muted-icon" /> : null}
        </div>
      </Panel>
      <Panel
        title="Memory-kandidaten (inbox)"
        actions={
          <Button variant="outline" size="sm" onClick={() => void runSleepScan()} disabled={scanning}>
            {scanning ? <Loader2 className="spin" /> : <Search />}
            Scan recente chats
          </Button>
        }
      >
        <p className="panel-copy">Idle/handmatige scan maakt alleen voorstellen. Nooit automatisch naar duurzaam geheugen.</p>
        {!proposals.length ? <p className="empty-copy">Geen openstaande voorstellen.</p> : null}
        <ul className="form-stack" style={{ marginTop: ".5rem" }}>
          {proposals.slice(0, 12).map((item) => {
            const id = String(item.id || "");
            return (
              <li key={id} className="memory-toolbar" style={{ justifyContent: "space-between", gap: ".5rem" }}>
                <div>
                  <strong>{String(item.title || id)}</strong>
                  <small style={{ display: "block" }}>{String(item.summary || item.content || "").slice(0, 160)}</small>
                </div>
                <div className="memory-toolbar">
                  <Button size="sm" variant="outline" onClick={() => void decideProposal(id, "reject")}>Afwijzen</Button>
                  <Button size="sm" onClick={() => void decideProposal(id, "accept")}>Accepteren</Button>
                </div>
              </li>
            );
          })}
        </ul>
      </Panel>
      <div className="memory-toolbar">
        <div className="inline-search"><Search /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Zoek in titel, inhoud of tags…" /></div>
        <Select value={collection} onValueChange={setCollection}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Alle collecties</SelectItem>
            {data.collections.map((item) => <SelectItem value={item} key={item}>{item}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={scopeFilter} onValueChange={(value: "all" | MemoryScope) => setScopeFilter(value)}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Alle scopes</SelectItem>
            <SelectItem value="session">Sessie</SelectItem>
            <SelectItem value="project">Project</SelectItem>
            <SelectItem value="global">Globaal</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="ghost" onClick={() => void exportItems()}><Download />Exporteren</Button>
        <Button variant="ghost" onClick={() => void exportKnowledgePack()}><Download />Knowledge pack</Button>
        {loading ? <Loader2 className="spin muted-icon" /> : null}
      </div>
      <div className="memory-layout">
        <Panel title="Geheugenitems" actions={<StatusBadge>{data.items.length} zichtbaar</StatusBadge>}>
          <div className="table-scroll">
            <table className="data-table memory-table">
              <thead>
                <tr>
                  <th>Titel</th>
                  <th>Samenvatting</th>
                  <th>Scope</th>
                  <th>Collectie</th>
                  <th>Tags</th>
                  <th>Bron</th>
                  <th>Gewijzigd</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr className={item.id === selectedId ? "selected-row clickable-row" : "clickable-row"} key={item.id} onClick={() => select(item)}>
                    <td><strong>{item.title}</strong></td>
                    <td>{item.summary || item.content.slice(0, 100)}</td>
                    <td><StatusBadge>{scopeLabel(item.scope)}</StatusBadge></td>
                    <td>{item.collection}</td>
                    <td><div className="tag-row">{item.tags.map((tag) => <em key={tag}>{tag}</em>)}</div></td>
                    <td>{item.source}</td>
                    <td>{formatDate(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.items.length && !loading ? <div className="table-empty">Geen geheugenitems gevonden.</div> : null}
          </div>
          <div className="table-footer">
            <span>{data.items.length} van {data.stats.items} items</span>
            <span>Wijzigingen worden direct lokaal opgeslagen</span>
          </div>
        </Panel>
        <div className="details-stack">
          <Panel
            title={selectedId ? draft.title || "Geheugenitem" : "Nieuw geheugen"}
            actions={<StatusBadge tone={selectedId ? "success" : "info"}>{selectedId ? "Opgeslagen" : "Concept"}</StatusBadge>}
          >
            <div className="form-stack">
              <label><span>Titel</span><Input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder="Duidelijke, herkenbare titel" /></label>
              <label><span>Inhoud</span><Textarea className="memory-content" value={draft.content} onChange={(event) => setDraft({ ...draft, content: event.target.value })} placeholder="Wat moet HADES blijvend onthouden?" /></label>
              <label><span>Samenvatting</span><Input value={draft.summary} onChange={(event) => setDraft({ ...draft, summary: event.target.value })} placeholder="Korte samenvatting voor retrieval" /></label>
            </div>
            <div className="form-grid three">
              <label>
                <span>Scope</span>
                <Select value={draft.scope || defaultScope} onValueChange={(value: MemoryScope) => setDraft({ ...draft, scope: value })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="session">Sessie</SelectItem>
                    <SelectItem value="project">Project</SelectItem>
                    <SelectItem value="global">Globaal</SelectItem>
                  </SelectContent>
                </Select>
              </label>
              <label><span>Collectie</span><Input value={draft.collection} onChange={(event) => setDraft({ ...draft, collection: event.target.value })} /></label>
              <label><span>Tags</span><Input value={tagText} onChange={(event) => setTagText(event.target.value)} placeholder="tag1, tag2" /></label>
            </div>
            <div className="form-grid two" style={{ marginTop: ".6rem" }}>
              <label><span>Bron</span><Input value={draft.source} onChange={(event) => setDraft({ ...draft, source: event.target.value })} /></label>
              {selected ? (
                <div className="record-meta" style={{ margin: 0 }}>
                  <span>Status<br /><strong>{selected.status || "active"}</strong></span>
                  <span>Supersedes<br /><code>{selected.supersedes || "—"}</code></span>
                  <span>ID<br /><code>{selected.id}</code></span>
                </div>
              ) : null}
            </div>
            {selected ? (
              <div className="record-meta">
                <span>Gemaakt<br /><strong>{formatDate(selected.created_at)}</strong></span>
                <span>Gewijzigd<br /><strong>{formatDate(selected.updated_at)}</strong></span>
                <span>Scope<br /><strong>{scopeLabel(selected.scope)}</strong></span>
              </div>
            ) : null}
            <div className="button-row end">
              {selectedId ? <Button variant="outline" onClick={supersede} disabled={saving}><BrainCircuit />Nieuwe versie</Button> : null}
              {selectedId ? (
                <AlertDialog>
                  <AlertDialogTrigger asChild><Button variant="destructive"><Trash2 />Vergeten</Button></AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Geheugen vergeten (inclusief supersession-keten)?</AlertDialogTitle>
                      <AlertDialogDescription>
                        Forget markeert dit item en gerelateerde versies als forgotten, wist inhoud uit retrieval, en behoudt auditsporen. Dit kan niet vanuit de GUI worden teruggedraaid.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Annuleren</AlertDialogCancel>
                      <AlertDialogAction onClick={remove}>Vergeten</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              ) : null}
              <Button onClick={save} disabled={saving || !draft.title.trim() || !draft.content.trim()}>
                {saving ? <Loader2 className="spin" /> : <Check />}Opslaan
              </Button>
            </div>
          </Panel>
          {history.length > 1 ? (
            <Panel title="Supersession-geschiedenis" actions={<StatusBadge>{history.length} versies</StatusBadge>}>
              <div className="source-list">
                {history.map((item) => (
                  <div className="source-item" key={item.id}>
                    <span className="source-icon"><BrainCircuit /></span>
                    <span>
                      <strong>{item.title}</strong>
                      <small>
                        {item.status || "active"} · {scopeLabel(item.scope)} · {formatDate(item.updated_at)}
                        {item.id === selectedId ? " · huidig" : ""}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
          <Panel title="Retrieval-test">
            <label className="retrieval-input">
              <Input value={retrievalQuery} onChange={(event) => setRetrievalQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void retrieve(); }} />
              <Button onClick={retrieve}>Test</Button>
            </label>
            {matches[0] ? (
              <div className="retrieval-result">
                <span>
                  <strong>Beste match</strong>
                  <small>{matches[0].title} · {scopeLabel(matches[0].scope)}</small>
                </span>
                <ProgressRow label="Lexicale overeenkomst" value={Math.round(matches[0].score * 100)} detail={matches[0].score.toFixed(2)} />
              </div>
            ) : (
              <p className="empty-copy">Test welke opgeslagen notitie het beste overeenkomt.</p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
