"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpenCheck, Check, CircleDashed, Download, FileUp, Globe2, LibraryBig, Loader2, Pause, Play, RefreshCcw, Repeat, Search, Sparkles, TriangleAlert, Users } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, StatCard, StatusBadge, type StatusTone } from "@/components/hades/ui";
import { formatDate, hadesApi, KnowledgeSource, ResearchCoverageSummary, ResearchEvent, ResearchProject } from "@/lib/hades-api";
import { applyHarvestRobotsPolicy, applyResearchRobotsPolicy } from "@/lib/research-robots-policy";
import { RESEARCH_ACTIVE_POLL_MS } from "@/lib/ui-poll-intervals";

const statusTone = (status: string): StatusTone => status === "completed" ? "success" : status === "failed" ? "danger" : status === "running" ? "info" : "warning";

const DEPTH_DEFAULTS: Record<ResearchProject["depth"], { rounds: number; agents: number }> = {
  quick: { rounds: 1, agents: 1 },
  standard: { rounds: 1, agents: 1 },
  deep: { rounds: 2, agents: 2 },
  expert: { rounds: 6, agents: 3 },
};

export function ResearchPage() {
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [events, setEvents] = useState<ResearchEvent[]>([]);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [knowledge, setKnowledge] = useState({ sources: 0, chunks: 0, token_estimate: 0, types: {} as Record<string, number> });
  const [topic, setTopic] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [depth, setDepth] = useState<ResearchProject["depth"]>("deep");
  const [maxRounds, setMaxRounds] = useState(DEPTH_DEFAULTS.deep.rounds);
  const [agentCount, setAgentCount] = useState(DEPTH_DEFAULTS.deep.agents);
  const [allowWeb, setAllowWeb] = useState(false);
  const [respectRobotsTxt, setRespectRobotsTxt] = useState(true);
  const [authorizedDownloads, setAuthorizedDownloads] = useState(false);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [harvesting, setHarvesting] = useState(false);
  const [harvestUrl, setHarvestUrl] = useState("");
  const [coverage, setCoverage] = useState<ResearchCoverageSummary | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);

  const selected = useMemo(() => projects.find((item) => item.id === selectedId) ?? projects[0], [projects, selectedId]);

  const applyDepthDefaults = (next: ResearchProject["depth"]) => {
    setDepth(next);
    const defaults = DEPTH_DEFAULTS[next];
    setMaxRounds(defaults.rounds);
    setAgentCount(defaults.agents);
  };

  const refresh = useCallback(async () => {
    try {
      const result = await hadesApi.research();
      setProjects(result.projects);
      setKnowledge(result.knowledge);
      setSelectedId((current) => current || result.projects[0]?.id || "");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Onderzoek laden is mislukt.");
    }
  }, []);

  const loadSelected = useCallback(async (id: string) => {
    if (!id) return;
    try {
      const result = await hadesApi.researchProject(id);
      setEvents(result.events);
      setSources(result.sources);
      setProjects((current) => current.map((item) => item.id === id ? result.project : item));
      try {
        const coverageResult = await hadesApi.researchCoverage(id);
        setCoverage(coverageResult);
        setCoverageError(null);
      } catch (coverageReason) {
        setCoverageError(coverageReason instanceof Error ? coverageReason.message : "Coverage laden mislukt.");
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Onderzoeksdetails laden is mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    void hadesApi.settings().then((result) => {
      const next = result.values.research_default_depth;
      applyDepthDefaults(next);
      if (typeof result.values.expert_max_cycles === "number" && next === "expert") {
        setMaxRounds(result.values.expert_max_cycles);
      }
    }).catch(() => undefined);
  }, [refresh]);
  useEffect(() => { if (selectedId) void loadSelected(selectedId); else { setCoverage(null); setCoverageError(null); } }, [selectedId, loadSelected]);
  useEffect(() => {
    const active = projects.some((item) => item.status === "running" || item.status === "queued");
    if (!active) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void refresh();
      if (selectedId) void loadSelected(selectedId);
    }, RESEARCH_ACTIVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [projects, refresh, loadSelected, selectedId]);

  const start = async () => {
    if (!topic.trim()) return;
    setCreating(true);
    try {
      const sourceInputs = sourceText.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
      const project = await hadesApi.createResearch({
        topic: topic.trim(),
        depth,
        allow_web: allowWeb,
        sources: applyResearchRobotsPolicy(sourceInputs, respectRobotsTxt),
        auto_start: true,
        approved_network: allowWeb,
        approved_file_read: true,
        authorized_downloads: authorizedDownloads,
        max_rounds: maxRounds,
        agent_count: agentCount,
      });
      setSelectedId(project.id);
      setTopic("");
      await refresh();
      toast.success("Onderzoek gestart.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Onderzoek starten is mislukt.");
    } finally {
      setCreating(false);
    }
  };

  const uploadDocuments = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    setUploading(true);
    const paths: string[] = [];
    let ready = 0;
    let failed = 0;
    for (const file of files) {
      try {
        const result = await hadesApi.uploadFile(file, true);
        const status = String((result as { file?: { status?: string }; path?: string }).file?.status || "");
        const path = String((result as { path?: string }).path || "");
        if (status === "ready" && path) {
          paths.push(path);
          ready += 1;
        } else {
          failed += 1;
          toast.error(`${file.name}: indexatie mislukt (${status || "onbekend"}).`);
        }
      } catch (reason) {
        failed += 1;
        toast.error(`${file.name}: ${reason instanceof Error ? reason.message : "upload mislukt"}`);
      }
    }
    if (paths.length) {
      setSourceText((current) => [current.trim(), ...paths].filter(Boolean).join("\n"));
      toast.success(`${ready} document(en) geüpload en geïndexeerd.`);
    } else if (failed) {
      toast.error("Geen documenten konden worden geïndexeerd.");
    }
    setUploading(false);
  };

  const harvestSite = async () => {
    const url = harvestUrl.trim() || sourceText.split(/\r?\n/).map((item) => item.trim()).find((item) => /^https?:\/\//i.test(item)) || "";
    if (!url) {
      toast.error("Geef een site-URL op om documenten te harvesten.");
      return;
    }
    setHarvesting(true);
    try {
      const result = await hadesApi.harvestKnowledgeSite({
        url: applyHarvestRobotsPolicy(url, respectRobotsTxt),
        authorized_downloads: true,
        approved_network: true,
        max_documents: 40,
        max_pages: 25,
        max_depth: 2,
        include_html_pages: true,
      });
      setHarvestUrl(url);
      await refresh();
      const ingested = Number(result.documents_ingested || 0);
      const pages = Number(result.pages_crawled || 0);
      const failures = Array.isArray(result.failures) ? result.failures.length : 0;
      const message = `Harvest: ${ingested} document(en), ${pages} pagina(s)` + (failures ? `, ${failures} mislukt` : "");
      if (ingested <= 0) {
        toast.error(failures ? `${message}. Geen documenten geïndexeerd.` : "Harvest leverde geen geïndexeerde documenten op.");
      } else {
        toast.success(message);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Site-harvest mislukt. Zet netwerkbeleid op allow.");
    } finally {
      setHarvesting(false);
    }
  };

  const rerun = async () => {
    if (!selected) return;
    try { await hadesApi.runResearch(selected.id); await refresh(); } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Herstarten mislukt."); }
  };

  const cancel = async () => {
    if (!selected) return;
    try { await hadesApi.cancelResearch(selected.id); await refresh(); } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Annuleren mislukt."); }
  };

  const exportReport = () => {
    if (!selected?.report) return;
    const blob = new Blob([selected.report], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${selected.title.replace(/[^a-z0-9-_]+/gi, "-") || "hades-research"}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page page-research">
      <PageHeader title="Onderzoek" description="Bouw brongebonden lokale kennis op uit websites, documenten, mappen en onderwerpen." actions={<Button variant="outline" onClick={() => void refresh()}><RefreshCcw />Vernieuwen</Button>} />
      <section className="stat-grid four">
        <StatCard label="Projecten" value={String(projects.length)} note="Persistent in SQLite" icon={<Search />} />
        <StatCard label="Kennisbronnen" value={String(knowledge.sources)} note="Knowledge Library" icon={<LibraryBig />} />
        <StatCard label="Chunks" value={String(knowledge.chunks)} note="Doorzoekbare passages" icon={<BookOpenCheck />} />
        <StatCard label="Tokens geschat" value={knowledge.token_estimate.toLocaleString("nl-NL")} note="Niet in prompt geladen" icon={<Sparkles />} />
      </section>

      <Panel className="research-query" title="Nieuw researchproject">
        <div className="query-row"><Search /><Input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Onderwerp of onderzoeksvraag…" aria-label="Onderzoeksvraag" /><Button onClick={start} disabled={!topic.trim() || creating}>{creating ? <Loader2 className="spin" /> : <Sparkles />}Onderzoek starten</Button></div>
        <div className="form-stack" style={{ marginTop: 14 }}>
          <label><span>Bronnen · één URL, bestandspad of mappad per regel</span><Textarea value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder={"https://example.org/docs\nD:\\Knowledge\\Books\nD:\\Research\\paper.pdf"} /></label>
          <label><span>Snelle site-harvest (ebooks/PDF/EPUB-links → Knowledge)</span>
            <div className="query-row">
              <Globe2 />
              <Input
                value={harvestUrl}
                onChange={(event) => setHarvestUrl(event.target.value)}
                placeholder="https://www.freebookcentre.net/"
                aria-label="Harvest site URL"
              />
              <Button variant="outline" onClick={() => void harvestSite()} disabled={harvesting}>
                {harvesting ? <Loader2 className="spin" /> : <Download />}
                Harvest site
              </Button>
            </div>
          </label>
        </div>
        <div className="research-controls">
          <label><LibraryBig /><span><strong>Lokale kennis</strong><small>Automatisch ophalen en opnieuw gebruiken</small></span><Switch checked disabled /></label>
          <label><Globe2 /><span><strong>Web research</strong><small>Respecteert netwerkbeleid; robots.txt is apart instelbaar</small></span><Switch checked={allowWeb} onCheckedChange={setAllowWeb} /></label>
          <label><BookOpenCheck /><span><strong>robots.txt respecteren</strong><small>Standaard aan; geldt voor web research en site-harvest</small></span><Switch checked={respectRobotsTxt} onCheckedChange={setRespectRobotsTxt} /></label>
          <label><Download /><span><strong>Open/geautoriseerde downloads</strong><small>Sta PDF/EPUB/DOCX-download toe voor bronnen die jij mag binnenhalen</small></span><Switch checked={authorizedDownloads} disabled={!allowWeb} onCheckedChange={setAuthorizedDownloads} /></label>
          <Select value={depth} onValueChange={(value) => applyDepthDefaults(value as ResearchProject["depth"])}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="quick">Quick</SelectItem><SelectItem value="standard">Standard</SelectItem><SelectItem value="deep">Deep</SelectItem><SelectItem value="expert">Expert</SelectItem></SelectContent></Select>
          <input ref={uploadRef} className="visually-hidden" type="file" multiple accept=".pdf,.docx,.epub,.pptx,.xlsx,.xlsm,.txt,.md,.html,.csv,.json,.py,.ts,.tsx,.js" onChange={uploadDocuments} />
          <Button variant="outline" onClick={() => uploadRef.current?.click()} disabled={uploading}>{uploading ? <Loader2 className="spin" /> : <FileUp />}Documenten uploaden</Button>
        </div>
        <div className="form-grid two research-depth-controls">
          <label>
            <span><Repeat style={{ width: "0.85rem", display: "inline", marginRight: 4, verticalAlign: "text-bottom" }} />Researchrondes</span>
            <Input
              type="number"
              min={1}
              max={60}
              value={maxRounds}
              onChange={(event) => setMaxRounds(Math.max(1, Math.min(60, Number(event.target.value) || 1)))}
              aria-label="Aantal researchrondes"
            />
            <small>Meer rondes = diepere gap-filling. Expert standaard 6.</small>
          </label>
          <label>
            <span><Users style={{ width: "0.85rem", display: "inline", marginRight: 4, verticalAlign: "text-bottom" }} />Research agents</span>
            <Input
              type="number"
              min={1}
              max={8}
              value={agentCount}
              onChange={(event) => setAgentCount(Math.max(1, Math.min(8, Number(event.target.value) || 1)))}
              aria-label="Aantal research agents"
            />
            <small>Parallelle workers per ronde (1–8). Expert standaard 3.</small>
          </label>
        </div>
      </Panel>

      <div className="research-grid">
        <Panel title="Researchprojecten" actions={<StatusBadge>{projects.length}</StatusBadge>}>
          <div className="source-list">
            {projects.map((project) => <button className={project.id === selected?.id ? "source-item" : "source-item"} key={project.id} type="button" onClick={() => setSelectedId(project.id)}><span className="source-icon">{project.status === "completed" ? <Check /> : project.status === "needs_more_evidence" ? <TriangleAlert /> : <CircleDashed className={project.status === "running" ? "spin" : ""} />}</span><span><strong>{project.title}</strong><small>{project.depth} · {project.agent_count ?? 1} agent(s) · {project.max_rounds ?? "auto"} ronde(s) · {formatDate(project.updated_at)}</small></span><span className="confidence">{project.metrics.coverage_score ?? project.metrics.mastery ?? project.progress}%<small>{project.status}</small></span></button>)}
            {!projects.length ? <p className="empty-copy">Nog geen researchprojecten.</p> : null}
          </div>
        </Panel>

        <Panel title={selected?.title ?? "Resultaat"} eyebrow={selected ? `${selected.depth} research` : "Selecteer een project"} actions={selected ? <StatusBadge tone={statusTone(selected.status)}>{selected.status} · {selected.progress}%</StatusBadge> : undefined}>
          {selected ? <>
            <Progress value={selected.progress} />
            <div className="research-draft" style={{ marginTop: 16 }}>
              {selected.error ? <div className="inline-error">{selected.error}</div> : null}
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>{selected.report || selected.findings || "Onderzoek is bezig; bevindingen verschijnen hier na synthese en verificatie."}</pre>
            </div>
            <div className="button-row" style={{ marginTop: 16 }}>
              {selected.status === "running" || selected.status === "queued" ? <Button variant="outline" onClick={cancel}><Pause />Annuleren</Button> : <Button variant="outline" onClick={rerun}><Play />Opnieuw onderzoeken</Button>}
              <Button variant="outline" onClick={exportReport} disabled={!selected.report}><Download />Rapport exporteren</Button>
            </div>
          </> : <p className="empty-copy">Maak of selecteer een project.</p>}
        </Panel>

        <Panel title="Mastery & evidence" actions={coverage?.incomplete ? <StatusBadge tone="warning">Dekkingshiaten</StatusBadge> : coverage?.complete ? <StatusBadge tone="success">Drempel bereikt</StatusBadge> : undefined}>
          {selected ? <>
            {coverageError ? <p className="empty-copy inline-error" style={{ marginBottom: 12 }}>{coverageError}</p> : null}
            {coverage?.metric_note ? <p className="empty-copy" style={{ marginBottom: 12 }}>{coverage.metric_note}</p> : null}
            {coverage && (coverage.incomplete || coverage.needs_more_evidence) ? (
              <div className="security-note compact" style={{ marginBottom: 12 }}>
                <TriangleAlert />
                <span>
                  <strong>Dekkingshiaten / incompleet</strong>
                  <small>
                    {coverage.gaps.length
                      ? coverage.gaps.join(" ")
                      : "Meer bewijs nodig — geen expert-compleet gemarkeerd."}
                  </small>
                </span>
              </div>
            ) : null}
            {coverage?.contradictions?.length ? (
              <ul className="empty-copy" style={{ marginBottom: 12, paddingLeft: 18 }}>
                {coverage.contradictions.slice(0, 6).map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : null}
            <dl className="detail-list spaced">
              <div><dt>Dekkingsscore</dt><dd>{coverage?.coverage_score ?? selected.metrics.coverage_score ?? selected.metrics.mastery ?? 0}%</dd></div>
              <div><dt>Drempel</dt><dd>{coverage?.mastery_target ?? selected.metrics.mastery_target ?? 90}%</dd></div>
              <div><dt>Bronnen gebruikt</dt><dd>{coverage?.source_count ?? selected.metrics.source_count ?? sources.length}{coverage ? ` / ${coverage.source_target}` : ""}</dd></div>
              <div><dt>Evidence chunks</dt><dd>{coverage?.evidence_chunks ?? selected.metrics.evidence_chunks ?? 0}</dd></div>
              <div><dt>Webdomeinen</dt><dd>{coverage?.domain_diversity ?? selected.metrics.domain_diversity ?? 0}</dd></div>
              <div><dt>Researchrondes</dt><dd>{selected.metrics.research_rounds ?? 0}{selected.metrics.configured_rounds ? ` / ${selected.metrics.configured_rounds}` : selected.max_rounds ? ` (max ${selected.max_rounds})` : ""}</dd></div>
              <div><dt>Research agents</dt><dd>{selected.metrics.agent_count ?? selected.agent_count ?? 1}</dd></div>
              <div><dt>Webdocumenten</dt><dd>{selected.authorized_downloads ? "geautoriseerd" : "alleen HTML"}</dd></div>
              <div><dt>Status</dt><dd>{selected.metrics.status ?? selected.status}</dd></div>
            </dl>
            <div className="source-list" style={{ marginTop: 12 }}>{sources.slice(0, 8).map((source) => <div className="source-item" key={source.id}><span className="source-icon"><BookOpenCheck /></span><span><strong>{source.title}</strong><small>{source.source_type} · {source.uri}</small></span></div>)}</div>
          </> : <p className="empty-copy">Geen project geselecteerd.</p>}
        </Panel>
      </div>

      {selected ? <Panel title="Live researchlog"><div className="task-log">{events.length ? events.slice().reverse().map((event) => <code key={event.id}>{formatDate(event.created_at)}  {event.level.toUpperCase()}  {event.message}</code>) : <span className="empty-copy">Nog geen events.</span>}</div></Panel> : null}
    </div>
  );
}