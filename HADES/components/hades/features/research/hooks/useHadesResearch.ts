"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import {
  hadesApi,
  type KnowledgeSource,
  type KnowledgeStats,
  type ResearchCoverageSummary,
  type ResearchEvent,
  type ResearchProject,
} from "@/lib/hades-api";
import { applyResearchRobotsPolicy } from "@/lib/research-robots-policy";
import { RESEARCH_ACTIVE_POLL_MS } from "@/lib/ui-poll-intervals";

const LIST_KEY = "hades:research";

export const RESEARCH_DEPTH_DEFAULTS: Record<
  ResearchProject["depth"],
  { rounds: number; agents: number }
> = {
  quick: { rounds: 1, agents: 1 },
  standard: { rounds: 1, agents: 1 },
  deep: { rounds: 2, agents: 2 },
  expert: { rounds: 6, agents: 3 },
};

export type ResearchCreateInput = {
  topic: string;
  depth?: ResearchProject["depth"];
  allow_web?: boolean;
  sources?: string[];
  respect_robots_txt?: boolean;
  authorized_downloads?: boolean;
  max_rounds?: number | null;
  agent_count?: number;
  auto_start?: boolean;
};

export type ResearchDetail = {
  project: ResearchProject;
  events: ResearchEvent[];
  sources: KnowledgeSource[];
  coverage: ResearchCoverageSummary | null;
  coverageError: string | null;
};

export function useHadesResearch() {
  const [selectedId, setSelectedId] = useState("");
  const [depth, setDepth] = useState<ResearchProject["depth"]>("deep");
  const [maxRounds, setMaxRounds] = useState(RESEARCH_DEPTH_DEFAULTS.deep.rounds);
  const [agentCount, setAgentCount] = useState(RESEARCH_DEPTH_DEFAULTS.deep.agents);
  const [allowWeb, setAllowWeb] = useState(false);
  const [respectRobotsTxt, setRespectRobotsTxt] = useState(true);
  const [authorizedDownloads, setAuthorizedDownloads] = useState(false);

  const listQuery = useHadesQuery(LIST_KEY, async () => hadesApi.research(), {
    staleTime: 3_000,
  });

  const projects = listQuery.data?.projects ?? [];
  const knowledge: KnowledgeStats | undefined = listQuery.data?.knowledge;

  useEffect(() => {
    if (!selectedId && projects[0]?.id) setSelectedId(projects[0].id);
  }, [projects, selectedId]);

  const detailKey = selectedId ? `${LIST_KEY}:detail:${selectedId}` : `${LIST_KEY}:detail:none`;
  const detailQuery = useHadesQuery(
    detailKey,
    async () => {
      if (!selectedId) return null;
      const result = await hadesApi.researchProject(selectedId);
      let coverage: ResearchCoverageSummary | null = null;
      let coverageError: string | null = null;
      try {
        coverage = await hadesApi.researchCoverage(selectedId);
      } catch (reason) {
        coverageError = reason instanceof Error ? reason.message : "Coverage laden mislukt.";
      }
      return {
        project: result.project,
        events: result.events,
        sources: result.sources,
        coverage,
        coverageError,
      } satisfies ResearchDetail;
    },
    { enabled: Boolean(selectedId), staleTime: 2_000 },
  );

  useEffect(() => {
    void hadesApi
      .settings()
      .then((result) => {
        const next = result.values.research_default_depth;
        if (next === "quick" || next === "standard" || next === "deep" || next === "expert") {
          setDepth(next);
          const defaults = RESEARCH_DEPTH_DEFAULTS[next];
          setMaxRounds(defaults.rounds);
          setAgentCount(defaults.agents);
          if (typeof result.values.expert_max_cycles === "number" && next === "expert") {
            setMaxRounds(result.values.expert_max_cycles);
          }
        }
      })
      .catch(() => undefined);
  }, []);

  const applyDepthDefaults = useCallback((next: ResearchProject["depth"]) => {
    setDepth(next);
    const defaults = RESEARCH_DEPTH_DEFAULTS[next];
    setMaxRounds(defaults.rounds);
    setAgentCount(defaults.agents);
  }, []);

  const refresh = useCallback(async () => {
    invalidateHadesQuery(LIST_KEY);
    if (selectedId) invalidateHadesQuery(`${LIST_KEY}:detail:${selectedId}`);
    await listQuery.refetch(true);
    if (selectedId) await detailQuery.refetch(true);
  }, [detailQuery, listQuery, selectedId]);

  const hasActive = useMemo(
    () => projects.some((item) => item.status === "running" || item.status === "queued"),
    [projects],
  );

  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void refresh();
    }, RESEARCH_ACTIVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [hasActive, refresh]);

  const selected =
    (detailQuery.data?.project && detailQuery.data.project.id === selectedId
      ? detailQuery.data.project
      : null) ??
    projects.find((item) => item.id === selectedId) ??
    null;

  const events = detailQuery.data?.events ?? [];
  const sources = detailQuery.data?.sources ?? [];
  const coverage = detailQuery.data?.coverage ?? null;
  const coverageError = detailQuery.data?.coverageError ?? null;

  const create = useCallback(
    async (input: ResearchCreateInput) => {
      const topic = input.topic.trim();
      if (!topic) throw new Error("Onderzoeksvraag is verplicht.");
      const nextDepth = input.depth ?? depth;
      const nextAllowWeb = input.allow_web ?? allowWeb;
      const sourceInputs = (input.sources ?? []).map((item) => item.trim()).filter(Boolean);
      const respect = input.respect_robots_txt ?? respectRobotsTxt;
      const project = await hadesApi.createResearch({
        topic,
        depth: nextDepth,
        allow_web: nextAllowWeb,
        sources: applyResearchRobotsPolicy(sourceInputs, respect),
        auto_start: input.auto_start !== false,
        approved_network: nextAllowWeb,
        approved_file_read: true,
        authorized_downloads: input.authorized_downloads ?? authorizedDownloads,
        max_rounds: input.max_rounds ?? maxRounds,
        agent_count: input.agent_count ?? agentCount,
      });
      setSelectedId(project.id);
      await refresh();
      return project;
    },
    [agentCount, allowWeb, authorizedDownloads, depth, maxRounds, refresh, respectRobotsTxt],
  );

  const run = useCallback(
    async (id: string) => {
      const project = await hadesApi.runResearch(id);
      await refresh();
      return project;
    },
    [refresh],
  );

  const cancel = useCallback(
    async (id: string) => {
      const project = await hadesApi.cancelResearch(id);
      await refresh();
      return project;
    },
    [refresh],
  );

  return {
    projects,
    knowledge,
    selectedId,
    setSelectedId,
    selected,
    events,
    sources,
    coverage,
    coverageError,
    depth,
    setDepth: applyDepthDefaults,
    maxRounds,
    setMaxRounds,
    agentCount,
    setAgentCount,
    allowWeb,
    setAllowWeb,
    respectRobotsTxt,
    setRespectRobotsTxt,
    authorizedDownloads,
    setAuthorizedDownloads,
    loading: listQuery.status === "loading" && !listQuery.data,
    detailLoading: Boolean(selectedId) && detailQuery.status === "loading" && !detailQuery.data,
    error: listQuery.error,
    detailError: detailQuery.error,
    refresh,
    create,
    run,
    cancel,
  };
}
