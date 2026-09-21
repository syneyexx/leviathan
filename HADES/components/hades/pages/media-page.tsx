"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  Clapperboard,
  FlaskConical,
  Library,
  Loader2,
  Radar,
  RefreshCw,
  Settings2,
  Sparkles,
  Users,
  Workflow,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, StatusBadge, type StatusTone } from "@/components/hades/ui";
import {
  hadesApi,
  MediaChannel,
  MediaOverview,
  MediaProject,
  MediaCapabilityItem,
} from "@/lib/hades-api";

type MediaTab =
  | "overview"
  | "channels"
  | "trends"
  | "intelligence"
  | "ideas"
  | "production"
  | "publish"
  | "calendar"
  | "analytics"
  | "experiments"
  | "library"
  | "personas"
  | "automation"
  | "setup";

const TABS: Array<{ id: MediaTab; label: string; icon: typeof Radar }> = [
  { id: "overview", label: "Overview", icon: Sparkles },
  { id: "channels", label: "Channels", icon: Users },
  { id: "trends", label: "Trend Radar", icon: Radar },
  { id: "intelligence", label: "Content Intelligence", icon: Clapperboard },
  { id: "ideas", label: "Ideas", icon: Sparkles },
  { id: "production", label: "Production", icon: Workflow },
  { id: "publish", label: "Publish Queue", icon: CalendarDays },
  { id: "calendar", label: "Calendar", icon: CalendarDays },
  { id: "analytics", label: "Analytics", icon: FlaskConical },
  { id: "experiments", label: "Experiments", icon: FlaskConical },
  { id: "library", label: "Media Library", icon: Library },
  { id: "personas", label: "Personas", icon: Users },
  { id: "automation", label: "Automation", icon: Workflow },
  { id: "setup", label: "Setup", icon: Settings2 },
];

const PLATFORMS = ["tiktok", "youtube", "instagram", "facebook"] as const;

function truthTone(status: string): StatusTone {
  if (status === "READY") return "success";
  if (status === "PARTIAL" || status === "DEGRADED" || status === "PRIVATE_ONLY" || status === "UNVERIFIED_ON_HOST") return "warning";
  if (status === "FAILED") return "danger";
  return "info";
}

function stageTone(stage: string): StatusTone {
  if (stage === "FAILED") return "danger";
  if (stage === "COMPLETE" || stage === "PUBLISHED" || stage === "READY_TO_PUBLISH") return "success";
  if (stage.includes("WAITING") || stage === "SCHEDULED") return "warning";
  return "info";
}

const emptyOverview: MediaOverview = {
  engine_status: "ACTIVE",
  channels: 0,
  trend_signals: 0,
  opportunities: 0,
  projects_producing: 0,
  ready_to_publish: 0,
  published_today: 0,
  failures: 0,
  platforms: {},
  campaigns: [],
  active_generation: [],
  publish_queue: [],
  trending_opportunities: [],
  experiments: [],
  learning_findings: [],
  blockers: [],
  budget: {},
  recent_failures: [],
};

export function MediaPage() {
  const [tab, setTab] = useState<MediaTab>("overview");
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState<MediaOverview>(emptyOverview);
  const [channels, setChannels] = useState<MediaChannel[]>([]);
  const [projects, setProjects] = useState<MediaProject[]>([]);
  const [setup, setSetup] = useState<Record<string, unknown> | null>(null);
  const [trends, setTrends] = useState<Array<Record<string, unknown>>>([]);
  const [opportunities, setOpportunities] = useState<Array<Record<string, unknown>>>([]);
  const [ideas, setIdeas] = useState<Array<Record<string, unknown>>>([]);
  const [publishJobs, setPublishJobs] = useState<Array<Record<string, unknown>>>([]);
  const [experiments, setExperiments] = useState<Array<Record<string, unknown>>>([]);
  const [learning, setLearning] = useState<Array<Record<string, unknown>>>([]);
  const [assets, setAssets] = useState<Array<Record<string, unknown>>>([]);
  const [selectedProject, setSelectedProject] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const [channelForm, setChannelForm] = useState({
    name: "",
    niche: "Strange historical facts",
    language: "en",
    platforms: ["tiktok", "youtube", "instagram", "facebook"] as string[],
    autonomy_level: "OFF",
    posting_frequency: "3/day",
    target_audience: "History enthusiasts 18–34",
    description: "Grow audience while maintaining factual quality.",
  });

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, ch, pr, su, tr, opp, id, pub, exp, lr, as] = await Promise.all([
        hadesApi.mediaOverview(),
        hadesApi.mediaChannels(),
        hadesApi.mediaProjects(),
        hadesApi.mediaSetup(),
        hadesApi.mediaTrends(),
        hadesApi.mediaOpportunities(),
        hadesApi.mediaIdeas(),
        hadesApi.mediaPublishJobs(),
        hadesApi.mediaExperiments(),
        hadesApi.mediaLearning(),
        hadesApi.mediaAssets(),
      ]);
      setOverview(ov);
      setChannels(ch.items || []);
      setProjects(pr.items || []);
      setSetup(su);
      setTrends(tr.items || []);
      setOpportunities(opp.items || []);
      setIdeas(id.items || []);
      setPublishJobs(pub.items || []);
      setExperiments(exp.items || []);
      setLearning(lr.items || []);
      setAssets(as.items || []);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Media overview laden mislukt");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const platformCards = useMemo(() => {
    return PLATFORMS.map((id) => overview.platforms?.[id] as MediaCapabilityItem | undefined).filter(Boolean) as MediaCapabilityItem[];
  }, [overview.platforms]);

  async function createChannel() {
    if (!channelForm.name.trim()) {
      toast.error("Channel name is required");
      return;
    }
    setBusy(true);
    try {
      await hadesApi.createMediaChannel({
        name: channelForm.name.trim(),
        niche: channelForm.niche,
        language: channelForm.language,
        platforms: channelForm.platforms,
        autonomy_level: channelForm.autonomy_level,
        posting_frequency: channelForm.posting_frequency,
        target_audience: channelForm.target_audience,
        description: channelForm.description,
        preferred_topics: [channelForm.niche],
      });
      toast.success("Channel created");
      setChannelForm((prev) => ({ ...prev, name: "" }));
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Channel create failed");
    } finally {
      setBusy(false);
    }
  }

  async function createAndRunProject(channelId: string) {
    setBusy(true);
    try {
      const created = await hadesApi.createMediaProject({
        channel_id: channelId,
        topic: channelForm.niche || "Strange historical facts",
        title: `Production · ${channelForm.niche || "topic"}`,
      });
      const result = await hadesApi.runMediaProject(created.project.id);
      toast.success(`Project ${(result.project as MediaProject | undefined)?.stage || "advanced"}`);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Project run failed");
    } finally {
      setBusy(false);
    }
  }

  async function discoverTrends() {
    setBusy(true);
    try {
      await hadesApi.discoverMediaTrends({ query: channelForm.niche || "history" });
      toast.success("Trend discovery completed (evidence-backed providers)");
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Trend discovery failed");
    } finally {
      setBusy(false);
    }
  }

  async function inspectProject(projectId: string) {
    setBusy(true);
    try {
      const detail = await hadesApi.mediaProject(projectId);
      setSelectedProject(detail as Record<string, unknown>);
      setTab("production");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Project load failed");
    } finally {
      setBusy(false);
    }
  }

  async function approveSelected(jobIds: string[]) {
    setBusy(true);
    try {
      await hadesApi.approveMediaPublish({ job_ids: jobIds });
      toast.success("Publish jobs updated");
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Approve failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page media-page">
      <PageHeader
        title="Media"
        description="Autonomous media intelligence — discovery, creation, production, distribution, measurement, learning. No viral guarantees."
        actions={
          <Button variant="outline" onClick={() => void refresh()} disabled={loading || busy}>
            {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            Refresh
          </Button>
        }
      />

      <div className="media-tabs" role="tablist" aria-label="Media workspace">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`media-tab${tab === id ? " is-active" : ""}`}
            onClick={() => setTab(id)}
          >
            <Icon size={14} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="media-grid">
          <Panel title="Media Engine">
            <div className="media-stat-grid">
              <div><strong>{overview.engine_status}</strong><span>Engine</span></div>
              <div><strong>{overview.channels}</strong><span>Channels</span></div>
              <div><strong>{overview.trend_signals}</strong><span>Trend signals</span></div>
              <div><strong>{overview.opportunities}</strong><span>Opportunities</span></div>
              <div><strong>{overview.projects_producing}</strong><span>Producing</span></div>
              <div><strong>{overview.ready_to_publish}</strong><span>Ready to publish</span></div>
              <div><strong>{overview.published_today}</strong><span>Published today</span></div>
              <div><strong>{overview.failures}</strong><span>Failures</span></div>
            </div>
          </Panel>
          <Panel title="Selected platforms">
            <div className="media-list">
              {platformCards.length === 0 && <span className="media-muted">No platform probes yet.</span>}
              {platformCards.map((item) => (
                <div key={item.id} className="media-row">
                  <span>{item.label}</span>
                  <StatusBadge tone={truthTone(item.status)}>{item.status}</StatusBadge>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Trending opportunities">
            <div className="media-list">
              {(overview.trending_opportunities || []).slice(0, 6).map((item) => (
                <div key={String(item.id)} className="media-row">
                  <span>Opportunity {Math.round(Number(item.score) || 0)}/100</span>
                  <span className="media-muted">{String(item.explanation || "").slice(0, 80)}</span>
                </div>
              ))}
              {!overview.trending_opportunities?.length && <span className="media-muted">No opportunities yet — run Trend Radar.</span>}
            </div>
          </Panel>
          <Panel title="Blockers">
            <div className="media-list">
              {(overview.blockers || []).slice(0, 8).map((item, index) => (
                <div key={`${item.id}-${index}`} className="media-alert">
                  <AlertTriangle size={14} />
                  <div>
                    <strong>{item.label || item.id}</strong>
                    <div className="media-muted">{item.status}: {item.detail}</div>
                  </div>
                </div>
              ))}
              {!overview.blockers?.length && <span className="media-muted">No hard blockers detected.</span>}
            </div>
          </Panel>
          <Panel title="Learning findings">
            <div className="media-list">
              {(overview.learning_findings || []).slice(0, 5).map((item) => (
                <div key={String(item.id)}>
                  <div>{String(item.finding)}</div>
                  <div className="media-muted">confidence={String(item.confidence)} · n={String(item.sample_size)}</div>
                </div>
              ))}
              {!overview.learning_findings?.length && <span className="media-muted">No learning findings yet.</span>}
            </div>
          </Panel>
          <Panel title="Publish queue">
            <div className="media-list">
              {(overview.publish_queue || []).slice(0, 8).map((job) => (
                <div key={String(job.id)} className="media-row">
                  <span>{String(job.platform)} · {String(job.status)}</span>
                  <StatusBadge tone={stageTone(String(job.status))}>{String(job.approval_state)}</StatusBadge>
                </div>
              ))}
              {!overview.publish_queue?.length && <span className="media-muted">Queue empty.</span>}
            </div>
          </Panel>
        </div>
      )}

      {tab === "channels" && (
        <div className="media-grid">
          <Panel title="Create channel / campaign">
            <div className="media-list">
              <Input placeholder="Channel name" value={channelForm.name} onChange={(e) => setChannelForm({ ...channelForm, name: e.target.value })} />
              <Input placeholder="Niche" value={channelForm.niche} onChange={(e) => setChannelForm({ ...channelForm, niche: e.target.value })} />
              <Textarea value={channelForm.description} onChange={(e) => setChannelForm({ ...channelForm, description: e.target.value })} />
              <div className="media-chip-row">
                {PLATFORMS.map((platform) => {
                  const active = channelForm.platforms.includes(platform);
                  return (
                    <button
                      key={platform}
                      type="button"
                      className={`media-chip${active ? " is-active" : ""}`}
                      onClick={() =>
                        setChannelForm((prev) => ({
                          ...prev,
                          platforms: active
                            ? prev.platforms.filter((p) => p !== platform)
                            : [...prev.platforms, platform],
                        }))
                      }
                    >
                      {platform}
                    </button>
                  );
                })}
              </div>
              <label className="media-muted">Autonomy</label>
              <select
                className="media-select"
                value={channelForm.autonomy_level}
                onChange={(e) => setChannelForm({ ...channelForm, autonomy_level: e.target.value })}
              >
                {["OFF", "RESEARCH", "PRODUCE", "QUEUE", "AUTONOMOUS"].map((level) => (
                  <option key={level} value={level}>{level}</option>
                ))}
              </select>
              <Button onClick={() => void createChannel()} disabled={busy || channelForm.platforms.length === 0}>
                Create channel
              </Button>
            </div>
          </Panel>
          <Panel title="Channels">
            <div className="media-list">
              {channels.map((channel) => (
                <div key={channel.id} className="media-card">
                  <div className="media-row">
                    <strong>{channel.name}</strong>
                    <StatusBadge tone="info">{channel.autonomy_level}</StatusBadge>
                  </div>
                  <div className="media-muted">{channel.niche} · {(channel.platforms || []).join(", ")}</div>
                  <div className="button-row">
                    <Button size="sm" variant="outline" onClick={() => void createAndRunProject(channel.id)} disabled={busy}>
                      Produce once
                    </Button>
                  </div>
                </div>
              ))}
              {!channels.length && <span className="media-muted">No channels yet.</span>}
            </div>
          </Panel>
        </div>
      )}

      {tab === "trends" && (
        <Panel
          title="Trend Radar"
          actions={<Button onClick={() => void discoverTrends()} disabled={busy}>Discover</Button>}
        >
          <p className="media-muted">Trends require evidence. LLMs alone do not declare “this is trending.” Unsupported metrics stay empty — never fake zeros.</p>
          <div className="media-list" style={{ marginTop: 12 }}>
            {trends.map((trend) => (
              <div key={String(trend.id)} className="media-card">
                <strong>{String(trend.display_topic)}</strong>
                <div className="media-muted">evidence={(Array.isArray(trend.evidence) ? trend.evidence.length : 0)} · last={String(trend.last_seen_at)}</div>
              </div>
            ))}
            {!trends.length && <span className="media-muted">No normalized trends yet.</span>}
          </div>
          <h4 style={{ marginTop: 16 }}>Opportunities</h4>
          <div className="media-list">
            {opportunities.map((item) => (
              <div key={String(item.id)} className="media-card">
                <div className="media-row">
                  <strong>Opportunity {Math.round(Number(item.score) || 0)}/100</strong>
                </div>
                <div className="media-muted">{String(item.explanation)}</div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {tab === "intelligence" && (
        <Panel title="Content Intelligence">
          <p className="media-muted">Pattern analysis learns creative structure (hooks, pacing, retention architecture) — never copies copyrighted scripts verbatim.</p>
          <div className="media-list" style={{ marginTop: 12 }}>
            {projects.slice(0, 10).map((project) => (
              <div key={project.id} className="media-card">
                <div className="media-row">
                  <strong>{project.title || project.topic || project.id}</strong>
                  <StatusBadge tone={stageTone(project.stage)}>{project.stage}</StatusBadge>
                </div>
                <Button size="sm" variant="outline" onClick={() => void inspectProject(project.id)}>Inspect artifacts</Button>
              </div>
            ))}
            {!projects.length && <span className="media-muted">No projects yet.</span>}
          </div>
        </Panel>
      )}

      {tab === "ideas" && (
        <Panel title="Ideas">
          <div className="media-list">
            {ideas.filter((idea) => !idea.rejected).map((idea) => {
              const payload = (idea.payload || {}) as Record<string, unknown>;
              return (
                <div key={String(idea.id)} className="media-card">
                  <strong>{String(payload.hook || payload.topic || idea.id)}</strong>
                  <div className="media-muted">
                    format={String(payload.format)} · rank={String(idea.rank_score)} · risk={String(payload.risk)}
                  </div>
                </div>
              );
            })}
            {!ideas.length && <span className="media-muted">No ideas yet — produce a project or discover opportunities.</span>}
          </div>
        </Panel>
      )}

      {tab === "production" && (
        <div className="media-grid">
          <Panel title="Production pipeline">
            <div className="media-list">
              {projects.map((project) => (
                <div key={project.id} className="media-card">
                  <div className="media-row">
                    <strong>{project.title}</strong>
                    <StatusBadge tone={stageTone(project.stage)}>{project.stage}</StatusBadge>
                  </div>
                  <div className="media-muted">progress={Math.round((project.progress || 0) * 100)}% · {(project.platforms || []).join(", ")}</div>
                  <div className="button-row">
                    <Button size="sm" onClick={() => void hadesApi.runMediaProject(project.id).then(refresh)} disabled={busy}>Advance</Button>
                    <Button size="sm" variant="outline" onClick={() => void inspectProject(project.id)}>Inspect</Button>
                    <Button size="sm" variant="outline" onClick={() => void hadesApi.cancelMediaProject(project.id).then(refresh)}>Cancel</Button>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Preview / artifacts">
            {!selectedProject && <span className="media-muted">Select a project to inspect trend evidence, script, storyboard, QA, variants.</span>}
            {selectedProject && (
              <div className="code-block"><pre className="media-pre">{JSON.stringify(selectedProject, null, 2).slice(0, 8000)}</pre></div>
            )}
          </Panel>
        </div>
      )}

      {tab === "publish" && (
        <Panel title="Publish queue">
          <div className="media-list">
            {publishJobs.map((job) => (
              <div key={String(job.id)} className="media-card">
                <div className="media-row">
                  <strong>{String(job.platform)}</strong>
                  <StatusBadge tone={stageTone(String(job.status))}>{String(job.status)}</StatusBadge>
                </div>
                <div className="media-muted">
                  approval={String(job.approval_state)} · consent={String(job.platform_consent_state)} · attempts={String(job.attempt_count)}
                </div>
                <div className="button-row">
                  <Button size="sm" variant="outline" onClick={() => void approveSelected([String(job.id)])}>Approve</Button>
                  <Button size="sm" onClick={() => void hadesApi.executeMediaPublish(String(job.id)).then(refresh)} disabled={busy}>Execute</Button>
                </div>
              </div>
            ))}
            {!publishJobs.length && <span className="media-muted">No publish jobs.</span>}
          </div>
        </Panel>
      )}

      {tab === "calendar" && (
        <Panel title="Calendar">
          <p className="media-muted">Scheduled publish jobs appear here from durable queue state.</p>
          <div className="media-list">
            {publishJobs.filter((job) => job.scheduled_for).map((job) => (
              <div key={String(job.id)} className="media-row">
                <span>{String(job.platform)}</span>
                <span>{String(job.scheduled_for)}</span>
              </div>
            ))}
            {!publishJobs.some((job) => job.scheduled_for) && <span className="media-muted">Nothing scheduled.</span>}
          </div>
        </Panel>
      )}

      {tab === "analytics" && (
        <Panel title="Analytics">
          <p className="media-muted">Metric snapshots are time-series. Unsupported platform metrics remain empty — never displayed as zero.</p>
          <Button variant="outline" onClick={() => void hadesApi.mediaAnalytics().then((r) => toast.message(`${(r.items || []).length} snapshots`))}>
            Load snapshots
          </Button>
        </Panel>
      )}

      {tab === "experiments" && (
        <Panel title="Experiments">
          <div className="media-list">
            {experiments.map((exp) => (
              <div key={String(exp.id)} className="media-card">
                <strong>{String(exp.name)}</strong>
                <div className="media-muted">{String(exp.hypothesis)}</div>
                <div className="media-muted">metric={String(exp.primary_metric)} · min_samples={String(exp.min_samples)} · {String(exp.status)}</div>
              </div>
            ))}
            {!experiments.length && <span className="media-muted">No experiments yet.</span>}
            {learning.length > 0 && (
              <>
                <h4>Learning</h4>
                {learning.map((item) => (
                  <div key={String(item.id)} className="media-card">{String(item.finding)}</div>
                ))}
              </>
            )}
          </div>
        </Panel>
      )}

      {tab === "library" && (
        <Panel title="Media library">
          <div className="media-list">
            {assets.map((asset) => (
              <div key={String(asset.id)} className="media-row">
                <span>{String(asset.asset_type)} · {String(asset.license_state)}</span>
                <span className="media-muted">{String(asset.provider)}</span>
              </div>
            ))}
            {!assets.length && <span className="media-muted">No assets yet.</span>}
          </div>
        </Panel>
      )}

      {tab === "personas" && (
        <Panel title="Personas">
          <p className="media-muted">Voice/visual personas are stored per channel. Do not clone a real person’s voice without explicit authorization.</p>
          <div className="media-list">
            {channels.map((channel) => (
              <div key={channel.id} className="media-card">
                <strong>{channel.name}</strong>
                <div className="code-block"><pre className="media-pre">{JSON.stringify({ voice: channel.voice_persona, visual: channel.visual_persona }, null, 2)}</pre></div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {tab === "automation" && (
        <Panel title="Automation">
          <p className="media-muted">Durable scheduler with leases, budgets and restart recovery — not an unbounded while-true loop.</p>
          <Button onClick={() => void hadesApi.mediaSchedulerTick().then(() => { toast.success("Scheduler tick"); void refresh(); })} disabled={busy}>
            Run scheduler tick
          </Button>
          <div className="media-list" style={{ marginTop: 12 }}>
            {channels.filter((c) => c.autonomy_level !== "OFF").map((channel) => (
              <div key={channel.id} className="media-row">
                <span>{channel.name}</span>
                <StatusBadge tone="info">{channel.autonomy_level}</StatusBadge>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {tab === "setup" && (
        <Panel title="Capability Doctor / Setup">
          <p className="media-muted">Every status explains why. Missing credentials are AUTH_REQUIRED — never fake READY.</p>
          <div className="code-block"><pre className="media-pre">{JSON.stringify(setup || overview.capabilities || {}, null, 2)}</pre></div>
        </Panel>
      )}
    </div>
  );
}
