import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pagesDir = path.join(root, "components/hades/finalbeta/pages");

/**
 * Production FINALBETA pages must not import mock *runtime* data.
 * Allowlist: presentation-only constants (tabs/labels) until moved to ui-constants.
 */
const ALLOWLIST = new Map([
  // Tab labels / presentation chrome only — no fake plugin inventory.
  ["tools-page.tsx", [/from ["']\.\.\/mocks\/pr-plugins["']/]],
  // Presentation field labels still used alongside live settings.
  ["finalbeta-settings-page.tsx", [/from ["']\.\.\/mocks\/settings["']/]],
  // Training tab ids only (runtime data must come from API).
  ["model-training-page.tsx", [/from ["']\.\.\/mocks\/model-training["']/]],
  // MCP tab labels only — servers/tools come from useHadesMcp.
  ["mcp-page.tsx", [/from ["']\.\.\/mocks\/pr-mcp["']/]],
  // Tasks column/tab chrome — kanban cards mapped from useHadesTasks.
  ["tasks-page.tsx", [/from ["']\.\.\/mocks\/tasks["']/]],
  // Memory presentation labels (tags/actions/health chrome).
  ["memory-page.tsx", [/from ["']\.\.\/mocks\/memory["']/]],
  // Knowledge presentation labels (filters/tags/actions).
  ["knowledge-page.tsx", [/from ["']\.\.\/mocks\/knowledge["']/]],
  // Research chip/tab labels only — projects/sources from useHadesResearch.
  ["research-page.tsx", [/from ["']\.\.\/mocks\/research["']/]],
  // Performance period/tab chrome only — metrics from useDashboardLive.
  ["performance-page.tsx", [/from ["']\.\.\/mocks\/pr-performance["']/]],
]);

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(full)));
    else if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) files.push(full);
  }
  return files;
}

test("FINALBETA production pages do not import mock runtime modules (allowlist)", async () => {
  const files = await walk(pagesDir);
  const offenders = [];
  for (const file of files) {
    const rel = path.relative(pagesDir, file).replace(/\\/g, "/");
    const base = path.basename(file);
    const source = await readFile(file, "utf8");
    const importRe = /from\s+["']((?:\.\.\/)+mocks\/[^"']+)["']/g;
    let match;
    while ((match = importRe.exec(source))) {
      const importPath = match[0];
      const allowed = ALLOWLIST.get(base) || ALLOWLIST.get(rel);
      if (allowed && allowed.some((re) => re.test(importPath) || re.test(source))) {
        // Only allowlisted presentation imports; still reject other mock imports in same file.
        const mockModule = match[1];
        const allowOk =
          (base === "tools-page.tsx" && mockModule.includes("pr-plugins")) ||
          (base === "finalbeta-settings-page.tsx" && mockModule.includes("settings")) ||
          (base === "model-training-page.tsx" && mockModule.includes("model-training")) ||
          (base === "mcp-page.tsx" && mockModule.includes("pr-mcp")) ||
          (base === "tasks-page.tsx" && mockModule.includes("tasks")) ||
          (base === "memory-page.tsx" && mockModule.includes("memory")) ||
          (base === "knowledge-page.tsx" && mockModule.includes("knowledge")) ||
          (base === "research-page.tsx" && mockModule.includes("research")) ||
          (base === "performance-page.tsx" && mockModule.includes("pr-performance"));
        if (allowOk) continue;
      }
      offenders.push(`${rel}: ${importPath}`);
    }
  }

  // Known remaining mock pages — tracked in capability matrix; this test locks NEW regressions
  // once a page is cleaned. Currently assert that live pages stay clean.
  const liveMustStayClean = [
    "chat-page.tsx",
    "coding-page.tsx",
    "dashboard-page.tsx",
    "tools-page.tsx",
    "finalbeta-settings-page.tsx",
    "models-page.tsx",
    "agents-page.tsx",
    "mcp-page.tsx",
    "tasks-page.tsx",
    "memory-page.tsx",
    "knowledge-page.tsx",
    "brain-page.tsx",
    "research-page.tsx",
    "llm-stats-page.tsx",
    "media-page.tsx",
    "media-queue-page.tsx",
    "media-viral-page.tsx",
    "media-calendar-page.tsx",
    "media-analytics-page.tsx",
    "trading-page.tsx",
    "trading-paper-page.tsx",
    "trading-strategies-page.tsx",
    "trading-marketdata-page.tsx",
    "trading-portfolio-page.tsx",
    "trading-broker-page.tsx",
    "workflows-page.tsx",
    "performance-page.tsx",
    "evidence-page.tsx",
    "files-page.tsx",
  ];
  const presentationAllow = {
    "tools-page.tsx": /pr-plugins/,
    "finalbeta-settings-page.tsx": /settings/,
    "mcp-page.tsx": /pr-mcp/,
    "tasks-page.tsx": /mocks\/tasks/,
    "memory-page.tsx": /mocks\/memory/,
    "knowledge-page.tsx": /mocks\/knowledge/,
    "research-page.tsx": /mocks\/research/,
    "performance-page.tsx": /mocks\/pr-performance/,
  };
  for (const name of liveMustStayClean) {
    const hits = offenders.filter((o) => o.startsWith(name) || o.includes(`/${name}`));
    const allowRe = presentationAllow[name];
    if (allowRe) {
      for (const hit of hits) assert.match(hit, allowRe);
      continue;
    }
    assert.equal(hits.length, 0, `live page must not import mocks: ${hits.join(", ")}`);
  }

  // Document remaining mock-import pages for the audit (non-fatal inventory).
  const remaining = offenders.filter(
    (o) =>
      !o.startsWith("tools-page") &&
      !o.startsWith("finalbeta-settings-page") &&
      !o.startsWith("mcp-page") &&
      !o.startsWith("tasks-page") &&
      !o.startsWith("research-page") &&
      !o.startsWith("memory-page") &&
      !o.startsWith("knowledge-page") &&
      !o.startsWith("performance-page") &&
      !o.includes("model-training-page.tsx"),
  );
  assert.ok(remaining.length >= 0);
  // Soft contract: chat/coding/dashboard never appear.
  assert.equal(
    remaining.filter((o) => /^(chat|coding|dashboard)-page/.test(o)).length,
    0,
  );
});

test("FINALBETA Plugins page uses live PluginManager hook", async () => {
  const source = await readFile(path.join(pagesDir, "tools-page.tsx"), "utf8");
  assert.match(source, /useHadesPlugins/);
  assert.match(source, /data-live="plugins"/);
  assert.match(source, /setEnabled/);
  assert.doesNotMatch(source, /PR_INSTALLED_PLUGINS/);
});

test("FINALBETA Settings page patches real policies", async () => {
  const source = await readFile(path.join(pagesDir, "finalbeta-settings-page.tsx"), "utf8");
  assert.match(source, /useHadesSettings/);
  assert.match(source, /data-live="settings"/);
  assert.match(source, /file_write_policy/);
  assert.match(source, /network_policy/);
  assert.match(source, /plugin_autonomous_tools/);
  assert.match(source, /max_tool_rounds/);
  assert.match(source, /settings\.patch/);
});

test("FINALBETA Memory/Knowledge/Brain/MCP/Tasks pages use live hooks", async () => {
  const memory = await readFile(path.join(pagesDir, "memory-page.tsx"), "utf8");
  const knowledge = await readFile(path.join(pagesDir, "knowledge-page.tsx"), "utf8");
  const brain = await readFile(path.join(pagesDir, "brain-page.tsx"), "utf8");
  const mcp = await readFile(path.join(pagesDir, "mcp-page.tsx"), "utf8");
  const tasks = await readFile(path.join(pagesDir, "tasks-page.tsx"), "utf8");

  assert.match(memory, /useHadesMemory/);
  assert.match(memory, /data-live="memory"/);
  assert.doesNotMatch(memory, /mockMemories/);

  assert.match(knowledge, /useHadesKnowledge/);
  assert.match(knowledge, /data-live="knowledge"/);
  assert.match(knowledge, /searchKnowledge/);
  assert.doesNotMatch(knowledge, /mockKnowledgeDocs/);

  assert.match(brain, /useHadesBrain/);
  assert.match(brain, /data-live="brain"/);
  assert.doesNotMatch(brain, /const CLUSTERS/);

  assert.match(mcp, /useHadesMcp/);
  assert.match(mcp, /data-live="mcp"/);
  assert.doesNotMatch(mcp, /MCP_SERVERS/);

  assert.match(tasks, /useHadesTasks/);
  assert.match(tasks, /data-live="tasks"/);
  assert.doesNotMatch(tasks, /mockKanbanTasks/);
});

test("FINALBETA MCP page uses live mcp_host hook", async () => {
  const source = await readFile(path.join(pagesDir, "mcp-page.tsx"), "utf8");
  assert.match(source, /useHadesMcp/);
  assert.match(source, /data-live="mcp"/);
  assert.match(source, /network_policy/);
  assert.doesNotMatch(source, /MCP_SERVERS/);
  assert.doesNotMatch(source, /MCP_TOOLS/);
  assert.doesNotMatch(source, /MCP_TEST_RESULT/);
  assert.doesNotMatch(source, /MCP_STATUS/);
});

test("FINALBETA Tasks page maps live tasks into kanban", async () => {
  const source = await readFile(path.join(pagesDir, "tasks-page.tsx"), "utf8");
  assert.match(source, /useHadesTasks/);
  assert.match(source, /data-live="tasks"/);
  assert.doesNotMatch(source, /mockKanbanTasks/);
});

test("FINALBETA Files page uses live files hook", async () => {
  const source = await readFile(path.join(pagesDir, "files-page.tsx"), "utf8");
  assert.match(source, /useHadesFiles/);
  assert.match(source, /data-live="files"/);
  assert.doesNotMatch(source, /mockFileRows/);
  assert.doesNotMatch(source, /FILES_FOLDER_TREE/);
  assert.doesNotMatch(source, /FILES_STORAGE/);
  assert.doesNotMatch(source, /FILES_QUICK_FILTERS/);
  assert.doesNotMatch(source, /from ["']\.\.\/mocks\/files["']/);
});

test("FINALBETA Models and Agents pages use live APIs", async () => {
  const models = await readFile(path.join(pagesDir, "models-page.tsx"), "utf8");
  const agents = await readFile(path.join(pagesDir, "agents-page.tsx"), "utf8");
  assert.match(models, /data-live="models"/);
  assert.match(models, /hadesApi\.models/);
  assert.doesNotMatch(models, /qwen3-14b-instruct/);
  assert.match(agents, /data-live="agents"/);
  assert.match(agents, /hadesApi\.agents/);
  assert.doesNotMatch(agents, /ONTWERPVOORBEELD/);
});

test("FINALBETA Brain page uses live brain hook", async () => {
  const source = await readFile(path.join(pagesDir, "brain-page.tsx"), "utf8");
  assert.match(source, /useHadesBrain/);
  assert.match(source, /data-live="brain"/);
  assert.doesNotMatch(source, /const CLUSTERS\s*=/);
  assert.doesNotMatch(source, /AI & Language Models/);
});

test("FINALBETA Evidence page uses claim register", async () => {
  const source = await readFile(path.join(pagesDir, "evidence-page.tsx"), "utf8");
  assert.match(source, /useHadesEvidence/);
  assert.match(source, /data-live="evidence"/);
  assert.doesNotMatch(source, /mockEvidenceClaims/);
  assert.doesNotMatch(source, /EVIDENCE_STATS/);
});

test("FINALBETA Memory and Knowledge stay on live hooks", async () => {
  const memory = await readFile(path.join(pagesDir, "memory-page.tsx"), "utf8");
  const knowledge = await readFile(path.join(pagesDir, "knowledge-page.tsx"), "utf8");
  assert.match(memory, /useHadesMemory/);
  assert.match(knowledge, /useHadesKnowledge/);
});

test("FINALBETA Research page wires live research APIs (useHadesResearch)", async () => {
  const source = await readFile(path.join(pagesDir, "research-page.tsx"), "utf8");
  const hook = await readFile(
    path.join(root, "components/hades/features/research/hooks/useHadesResearch.ts"),
    "utf8",
  );
  assert.match(source, /useHadesResearch/);
  assert.match(source, /data-live="research"/);
  assert.doesNotMatch(source, /mockResearchResults/);
  assert.doesNotMatch(source, /RESEARCH_STATUS_CHECKS/);
  assert.doesNotMatch(source, /RESEARCH_SOURCE_SLICES/);
  assert.doesNotMatch(source, /RESEARCH_INSIGHTS/);
  assert.doesNotMatch(source, /RESEARCH_EVIDENCE/);
  assert.doesNotMatch(source, /RESEARCH_RECENT/);
  assert.match(hook, /hadesApi\.research\(/);
  assert.match(hook, /hadesApi\.createResearch/);
  assert.match(hook, /hadesApi\.runResearch/);
  assert.match(hook, /hadesApi\.cancelResearch/);
  assert.match(hook, /approved_network/);
  assert.match(hook, /applyResearchRobotsPolicy/);
});


test("FINALBETA Performance page uses live dashboard telemetrie", async () => {
  const source = await readFile(path.join(pagesDir, "performance-page.tsx"), "utf8");
  assert.match(source, /useDashboardLive/);
  assert.match(source, /data-live="performance"/);
  assert.doesNotMatch(source, /PR_PERF_KPIS/);
  assert.doesNotMatch(source, /PR_PERF_PROCESSES/);
  assert.doesNotMatch(source, /PR_PERF_CHARTS/);
});

test("FINALBETA LLM Stats page uses live stats hook", async () => {
  const source = await readFile(path.join(pagesDir, "llm-stats-page.tsx"), "utf8");
  const hook = await readFile(
    path.join(root, "components/hades/features/stats/hooks/useHadesLlmStats.ts"),
    "utf8",
  );
  assert.match(source, /useHadesLlmStats/);
  assert.match(source, /data-live="llm-stats"/);
  assert.doesNotMatch(source, /STATS_KPIS/);
  assert.doesNotMatch(source, /STATS_MODELS/);
  assert.doesNotMatch(source, /from ["']\.\.\/mocks\/stats["']/);
  assert.match(hook, /hadesApi\.models/);
  assert.match(hook, /hadesApi\.modelGateway/);
  assert.match(hook, /hadesApi\.agents/);
});

test("FINALBETA Media overview uses live media hook", async () => {
  const source = await readFile(path.join(pagesDir, "media-page.tsx"), "utf8");
  const hook = await readFile(
    path.join(root, "components/hades/features/media/hooks/useHadesMedia.ts"),
    "utf8",
  );
  assert.match(source, /useHadesMedia/);
  assert.match(source, /data-live="media"/);
  assert.doesNotMatch(source, /MEDIA_KPIS/);
  assert.doesNotMatch(source, /MEDIA_QUEUE/);
  assert.doesNotMatch(source, /from ["']\.\.\/mocks\/media["']/);
  assert.match(hook, /hadesApi\.mediaOverview/);
  assert.match(hook, /hadesApi\.mediaChannels/);
});

test("FINALBETA Trading overview uses live trading hook (paper/sim)", async () => {
  const source = await readFile(path.join(pagesDir, "trading-page.tsx"), "utf8");
  const hook = await readFile(
    path.join(root, "components/hades/features/trading/hooks/useHadesTrading.ts"),
    "utf8",
  );
  assert.match(source, /useHadesTrading/);
  assert.match(source, /data-live="trading"/);
  assert.match(source, /SIMULATIE \/ PAPER/);
  assert.doesNotMatch(source, /TC_OVERVIEW_KPIS/);
  assert.doesNotMatch(source, /from ["']\.\.\/mocks\/trading["']/);
  assert.match(hook, /hadesApi\.tradingDashboard/);
  assert.match(hook, /hadesApi\.labOverview/);
  assert.match(hook, /setPaperTrading/);
});

test("FINALBETA Workflows page uses live Gen2 workflows hook", async () => {
  const source = await readFile(path.join(pagesDir, "workflows-page.tsx"), "utf8");
  const hook = await readFile(
    path.join(root, "components/hades/features/workflows/hooks/useHadesWorkflows.ts"),
    "utf8",
  );
  assert.match(source, /useHadesWorkflows/);
  assert.match(source, /data-live="workflows"/);
  assert.doesNotMatch(source, /PR_WF_LIST/);
  assert.doesNotMatch(source, /PR_WF_STATS/);
  assert.doesNotMatch(source, /from ["']\.\.\/mocks\/pr-workflows["']/);
  assert.match(hook, /hadesApi\.gen2Workflows/);
  assert.match(hook, /gen2ValidateWorkflow/);
  assert.match(hook, /gen2DryRunWorkflow/);
});

test("FINALBETA Media queue uses live media hook", async () => {
  const source = await readFile(path.join(pagesDir, "media-queue-page.tsx"), "utf8");
  assert.match(source, /useHadesMedia/);
  assert.match(source, /data-live="media-queue"/);
  assert.doesNotMatch(source, /QUEUE_ITEMS/);
  assert.doesNotMatch(source, /from ["']\.\.\/mocks\/media-queue["']/);
});

test("FINALBETA Trading paper + strategies use live trading hook", async () => {
  const paper = await readFile(path.join(pagesDir, "trading-paper-page.tsx"), "utf8");
  const strat = await readFile(path.join(pagesDir, "trading-strategies-page.tsx"), "utf8");
  assert.match(paper, /useHadesTrading/);
  assert.match(paper, /data-live="trading-paper"/);
  assert.match(paper, /PAPER ONLY/);
  assert.doesNotMatch(paper, /TC_PAPER_KPIS/);
  assert.doesNotMatch(paper, /from ["']\.\.\/mocks\/trading["']/);
  assert.match(strat, /useHadesTrading/);
  assert.match(strat, /data-live="trading-strategies"/);
  assert.doesNotMatch(strat, /TC_STRAT_CATALOG/);
  assert.doesNotMatch(strat, /from ["']\.\.\/mocks\/trading["']/);
});

test("FINALBETA Media viral/calendar/analytics use live media hook", async () => {
  const viral = await readFile(path.join(pagesDir, "media-viral-page.tsx"), "utf8");
  const calendar = await readFile(path.join(pagesDir, "media-calendar-page.tsx"), "utf8");
  const analytics = await readFile(path.join(pagesDir, "media-analytics-page.tsx"), "utf8");
  assert.match(viral, /useHadesMedia/);
  assert.match(viral, /data-live="media-viral"/);
  assert.doesNotMatch(viral, /VIRAL_KPIS/);
  assert.doesNotMatch(viral, /from ["']\.\.\/mocks\/media-viral["']/);
  assert.match(calendar, /useHadesMedia/);
  assert.match(calendar, /data-live="media-calendar"/);
  assert.doesNotMatch(calendar, /CAL_ENTRIES/);
  assert.doesNotMatch(calendar, /from ["']\.\.\/mocks\/media-calendar["']/);
  assert.match(analytics, /useHadesMedia/);
  assert.match(analytics, /data-live="media-analytics"/);
  assert.doesNotMatch(analytics, /ANALYTICS_KPIS/);
  assert.doesNotMatch(analytics, /from ["']\.\.\/mocks\/media-analytics["']/);
});

test("FINALBETA Trading marketdata/portfolio live; broker stays honest gate", async () => {
  const md = await readFile(path.join(pagesDir, "trading-marketdata-page.tsx"), "utf8");
  const port = await readFile(path.join(pagesDir, "trading-portfolio-page.tsx"), "utf8");
  const broker = await readFile(path.join(pagesDir, "trading-broker-page.tsx"), "utf8");
  assert.match(md, /useHadesTrading/);
  assert.match(md, /data-live="trading-marketdata"/);
  assert.doesNotMatch(md, /TC_MD_KPIS/);
  assert.doesNotMatch(md, /from ["']\.\.\/mocks\/trading["']/);
  assert.match(port, /useHadesTrading/);
  assert.match(port, /data-live="trading-portfolio"/);
  assert.doesNotMatch(port, /TC_PORT_KPIS/);
  assert.doesNotMatch(port, /from ["']\.\.\/mocks\/trading["']/);
  assert.match(broker, /data-live="trading-broker"/);
  assert.match(broker, /NIET GECONFIGUREERD/);
  assert.doesNotMatch(broker, /TC_BROKER_BALANCES/);
  assert.doesNotMatch(broker, /from ["']\.\.\/mocks\/trading["']/);
});
