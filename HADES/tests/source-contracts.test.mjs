import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const readChat = async () => (await Promise.all([
  "components/hades/pages/chat-page.tsx",
  "components/hades/features/chat/ChatTimeline.tsx",
  "components/hades/features/chat/ChatComposer.tsx",
  "components/hades/features/chat/hooks/useChatRun.ts",
].map(read))).join("\n");

test("Windows scripts no longer use Unix-only inline environment syntax", async () => {
  const pkg = JSON.parse(await read("package.json"));
  assert.equal(pkg.scripts.dev, "vite");
  assert.doesNotMatch(pkg.scripts.dev, /WRANGLER_LOG_PATH|^[A-Z_]+=.+\s/);
  const start = await read("START_HADES.bat");
  assert.match(start, /npm run dev/);
});

test("Work Runtime persists plans, checkpoints and verification", async () => {
  const main = await read("backend/main.py");
  const verification = await read("backend/reasoning/verification.py");
  const storage = await read("backend/platform_db.py");
  assert.match(main, /HADES Work Planner/);
  assert.match(main, /build_verification_prompt/);
  assert.match(main, /parse_verification_result/);
  assert.match(main, /verification_allows_success/);
  assert.match(verification, /Verification\/Critic/);
  assert.match(verification, /passed=false/);
  // Strict bool parse writes repaired/out["passed"] (not legacy parsed["passed"]).
  assert.match(verification, /out\["passed"\]|repaired\["passed"\]|parse_strict_bool/);
  assert.match(storage, /CREATE TABLE IF NOT EXISTS work_steps/);
  assert.match(storage, /CREATE TABLE IF NOT EXISTS work_checkpoints/);
});

test("Research, knowledge and plugin APIs are present in the release", async () => {
  const main = await read("backend/main.py");
  for (const route of ["/api/knowledge", "/api/research", "/api/plugins", "/api/files", "/api/agents"]) {
    assert.ok(main.includes(route), `missing ${route}`);
  }
  for (const marker of [
    '/api/files/workspaces/{workspace_id}/rescan',
    '/api/files/{file_id}/reindex',
    'uploads_count',
  ]) {
    assert.ok(main.includes(marker), `missing files API marker ${marker}`);
  }
  const filesPage = await read("components/hades/pages/files-page.tsx");
  assert.match(filesPage, /rescanWorkspace/);
  assert.match(filesPage, /searchKnowledge/);
  assert.match(filesPage, /upload-zone/);
  assert.match(filesPage, /focusArtifactId/);
});

test("release no longer ships inactive Cloudflare/OpenAI Sites scaffolding", async () => {
  const { existsSync } = await import("node:fs");
  for (const path of [".openai", "worker", "build", "db", "drizzle", "next.config.ts", "drizzle.config.ts", "data/mock-data.ts"]) {
    assert.equal(existsSync(new URL(`../${path}`, import.meta.url)), false, `legacy scaffold still present: ${path}`);
  }
});

test("package.json and package-lock root dependencies match", async () => {
  const pkg = JSON.parse(await read("package.json"));
  const lock = JSON.parse(await read("package-lock.json"));
  assert.deepEqual(lock.packages[""].dependencies, pkg.dependencies);
  assert.deepEqual(lock.packages[""].devDependencies, pkg.devDependencies);
});


test("v0.4 chat prompts, autonomous tools, labels and one-click launcher are wired", async () => {
  const main = await read("backend/main.py");
  const db = await read("backend/database.py");
  const plugins = `${await read("components/hades/pages/plugins-page.tsx")}\n${await read("components/hades/pages/plugins-page-core.tsx")}`;
  const chat = await readChat();
  const launcher = await read("HADES_LAUNCHER.py");
  assert.match(db, /system_prompt_override/);
  assert.match(main, /allow_methods=\[["']GET["'],\s*["']POST["'],\s*["']PUT["'],\s*["']PATCH["']/);
  assert.match(main, /max_tool_rounds/);
  assert.match(main, /maybe_refresh_web_knowledge/);
  assert.match(plugins, /plugin\.category/);
  assert.match(chat, /saveConversationMeta/);
  assert.match(launcher, /webbrowser\.open/);
});

test("v0.4.1 Plugin Runtime exposes structured calls and verified lifecycle output", async () => {
  const main = await read("backend/main.py");
  const runtime = `${await read("backend/platform_services.py")}\n${await read("backend/platform_services_core.py")}`;
  const storage = await read("backend/platform_db.py");
  const plugins = `${await read("components/hades/pages/plugins-page.tsx")}\n${await read("components/hades/pages/plugins-page-core.tsx")}`;
  assert.match(main, /\/api\/plugins\/\{plugin_id\}\/tool-calls/);
  assert.match(main, /approved_by_user/);
  assert.match(runtime, /_wait_for_health/);
  assert.match(runtime, /shell=False/);
  assert.match(storage, /stdout_text/);
  for (const field of ["Resultaat", "stdout", "stderr", "Exit code", "Duur", "Gestart", "Voltooid", "Persistente toolcalls"]) {
    assert.ok(plugins.includes(field), `missing structured tool result field: ${field}`);
  }
});

test("dependency repair exposes bounded live diagnostics without moving controls into Settings", async () => {
  const runtime = await read("backend/platform_services.py");
  const commandRuntime = await read("backend/plugin_dependency_runtime.py");
  const plugins = await read("components/hades/pages/plugins-page.tsx");
  assert.match(runtime, /_DEPENDENCY_TIMEOUT_DEFAULTS/);
  assert.match(runtime, /stall_timeout_seconds/);
  assert.match(runtime, /Dependency output:/);
  assert.match(commandRuntime, /MAX_LOG_BYTES/);
  assert.match(commandRuntime, /redact_dependency_output/);
  assert.match(commandRuntime, /taskkill/);
  assert.match(plugins, /Dependency-installatie/);
  assert.match(plugins, /pluginEvents/);
});

test("Settings page exposes every DEFAULT_SETTINGS key as an editable control", async () => {
  const database = await read("backend/database.py");
  const settingsPage = await read("components/hades/pages/settings-page.tsx");
  const voiceSettings = await read("components/hades/voice/voice-settings-panel.tsx");
  const speechPanel = await read("components/hades/speech-settings-panel.tsx");
  // Neural keys live on the FINALBETA Neural control surface (default OFF).
  const neuralPanel = await read("components/hades/finalbeta/neural/neural-control-panel.tsx");
  const settingsSurface = `${settingsPage}\n${voiceSettings}\n${speechPanel}\n${neuralPanel}`;

  const apiTypes = await read("lib/hades-api.ts");
  const match = database.match(/DEFAULT_SETTINGS: dict\[str, Any\] = \{([\s\S]*?)\n\}/);
  assert.ok(match, "DEFAULT_SETTINGS block missing");
  const keys = [...match[1].matchAll(/"([a-z0-9_]+)":/g)].map((item) => item[1]);
  assert.ok(keys.includes("expert_max_cycles"), "expert_max_cycles must remain a persisted setting");
  assert.ok(keys.length >= 20, `expected a full settings schema, got ${keys.length} keys`);
  for (const key of keys) {
    assert.ok(settingsSurface.includes(`settings.${key}`), `settings UI missing editable binding for ${key}`);

    assert.ok(apiTypes.includes(`${key}:`), `AppSettings type missing ${key}`);
  }
  assert.match(settingsPage, /expert_max_cycles/);
  assert.match(settingsPage, /Expert max\. cycli/);
  assert.match(settingsPage, /Spraak/);
  assert.match(settingsPage, /retrieval_multilingual_expand/);
  assert.match(voiceSettings, /voice_asr_model/);
  assert.match(speechPanel, /tts_provider/);
  assert.match(neuralPanel, /settings\.neural_mode/);
  assert.match(neuralPanel, /settings\.neural_max_concurrent_infer/);

});

test("Agents page is wired to live /api/agents console without mock production data", async () => {
  const page = await read("components/hades/pages/agents-page.tsx");
  const api = await read("lib/hades-api.ts");
  const main = await read("backend/main.py");
  assert.match(page, /hadesApi\.agents/);
  assert.match(page, /hadesApi\.setAgentState/);
  assert.match(page, /hadesApi\.cancelAgentCurrent/);
  assert.doesNotMatch(page, /\bconst AGENTS\b/);
  assert.doesNotMatch(page, /Mockdata|Mock ·|fake token|dummy/i);
  assert.doesNotMatch(page, /cpu:\s*\d+|ram:\s*\d+/);
  assert.match(api, /AgentsConsoleResponse/);
  assert.match(api, /cancelAgentCurrent/);
  assert.match(main, /\/api\/agents\/\{agent_id\}\/state/);
  assert.match(main, /\/api\/agents\/\{agent_id\}\/cancel-current/);
  assert.match(main, /build_agents_snapshot/);
});

test("Plugin Converter packages source without dependency installation or source execution", async () => {
  const plugins = await read("components/hades/pages/plugins-page-core.tsx");
  assert.match(plugins, /Source → \.HadesPlugin converter/);
  assert.match(plugins, /Converteren & downloaden/);
  assert.match(plugins, /install_dependencies: false/);
  assert.match(plugins, /Geen dependency-installatie, geen toolrun/);
  assert.match(plugins, /setPluginState\(result\.plugin\.id, false\)/);
});

test("Plugins page can pack a selected folder into a usable .HadesPlugin", async () => {
  const plugins = await read("components/hades/pages/plugins-page-core.tsx");
  const apiBarrel = await read("lib/hades-api.ts");
  const pluginApi = await read("lib/api/plugins.ts");
  const main = await read("backend/main.py");
  assert.match(plugins, /Map → \.HadesPlugin/);
  assert.match(plugins, /Deze computer/);
  assert.match(plugins, /Via browser/);
  assert.match(plugins, /webkitdirectory/);
  assert.match(plugins, /pickPluginFolder/);
  assert.match(plugins, /importPluginFolder/);
  // Plugin HTTP methods live in the extracted client; the barrel must still expose them on hadesApi.
  assert.match(pluginApi, /pickPluginFolder/);
  assert.match(pluginApi, /importPluginFolder/);
  assert.match(apiBarrel, /createPluginApi/);
  assert.match(apiBarrel, /\.\.\.pluginApi/);
  assert.match(main, /\/api\/plugins\/pick-folder/);
  assert.match(main, /\/api\/plugins\/import-folder/);
});

test("Voice-to-task path is paste/local STT; built-in ASR lives in voice mode", async () => {
  const tasks = await read("components/hades/pages/tasks-page.tsx");
  const routes = await read("backend/capability_routes.py");
  const voice = await read("backend/voice_tasks.py");
  const voicePkg = await read("backend/voice/__init__.py");
  const plugin = await read("plugins/local-stt-paste/hades-plugin.json");
  const pluginReadme = await read("plugins/local-stt-paste/README.md");
  const vsReadme = await read("plugins/voicestudio/README.md");
  const api = await read("lib/hades-api.ts");
  assert.match(tasks, /Spraak → taak/);
  assert.match(tasks, /geen cloud-STT/);
  assert.match(tasks, /voiceAutoStart/);
  assert.match(tasks, /readVoiceQueryFlag/);
  assert.match(tasks, /local-stt-paste/);
  assert.match(tasks, /VoiceStudio/);
  assert.match(routes, /@router\.post\("\/voice\/to-task"\)/);
  assert.match(routes, /model_id=None/);
  assert.match(routes, /auto_start/);
  assert.match(voice, /voice-to-task-pad doet zelf geen ASR|geen ASR/);
  assert.match(voicePkg, /built-in local speech|local voice subsystem/i);
  assert.match(plugin, /transcribe_paste/);
  assert.match(pluginReadme, /paste-only|no built-in ASR|does \*\*not\*\* perform speech recognition/i);
  assert.match(vsReadme, /complements HADES voice/i);
  assert.match(api, /voiceToTask/);
  assert.match(api, /voiceTranscribe|voiceSpeak|voiceSessionStart/);
});

test("VoiceStudio is a swappable local TTS provider for spoken answers", async () => {
  const speechRuntime = await read("backend/speech/runtime.py");
  const speechClient = await read("backend/speech/voicestudio_client.py");
  const speakable = await read("backend/speech/speakable.py");
  const speechRoutes = await read("backend/speech/routes.py");
  const settingsPage = await read("components/hades/pages/settings-page.tsx");
  const speechPanel = await read("components/hades/speech-settings-panel.tsx");
  const chat = await readChat();
  const api = await read("lib/hades-api.ts");
  const docs = await read("docs/VOICE_STUDIO_TTS.md");
  const vsReadme = await read("plugins/voicestudio/README.md");
  assert.match(speechClient, /\/audio\/voices/);
  assert.match(speechClient, /\/audio\/speech/);
  assert.match(speechClient, /streaming_speech/);
  assert.match(speechClient, /complete audio clip|do not invent/i);
  assert.match(speakable, /prepare_speakable_text/);
  assert.match(speakable, /_CODE_FENCE_RE/);
  assert.match(speechRuntime, /echo_guard/);
  assert.match(speechRuntime, /InterruptedError/);
  assert.match(speechRoutes, /prefix=\"\/speech\"/);
  assert.match(settingsPage, /Spraak/);
  assert.match(speechPanel, /Voorbeeldbeluisteren/);
  assert.match(speechPanel, /Geen stille cloud-fallback/);
  assert.match(chat, /Gesproken antwoorden/);
  assert.match(chat, /Voorlezen/);
  assert.match(chat, /hadesSpeechPlayer/);
  assert.match(api, /speechStatus/);
  assert.match(api, /speechSpeak/);
  assert.match(docs, /VoiceStudio/);
  assert.match(vsReadme, /POST \/v1\/audio\/speech/);
  assert.match(vsReadme, /Not claimed/i);
});

test("Coding Agent composer/indexer/debug/release surfaces are wired", async () => {
  const runtime = await read("components/hades/features/coding/hooks/useHadesCodingRuntime.ts");
  const core = await read("components/hades/features/coding/coding-runtime-core.ts");
  const fb = await read("components/hades/finalbeta/pages/coding-page.tsx");
  const api = await read("lib/hades-api.ts");
  const symbols = await read("backend/workspace_symbols.py");
  const release = await read("backend/release_confidence.py");
  const debug = await read("backend/debug_agent.py");
  assert.match(api, /buildPlan/);
  assert.match(api, /buildPreview/);
  assert.match(api, /buildApply/);
  assert.match(api, /buildRestore/);
  assert.match(api, /searchSymbols/);
  assert.match(api, /refreshSymbols/);
  assert.match(api, /debugDiagnose/);
  assert.match(api, /releaseConfidence/);
  assert.match(runtime, /previewComposerPlan/);
  assert.match(runtime, /repairWavesJson|repair_waves/);
  assert.match(runtime, /buildFromGoalAsync|attachJob/);
  assert.match(runtime, /loadProposedEditsIntoComposer/);
  assert.match(runtime, /runReleaseSmoke|loadReleaseConfidence/);
  assert.match(runtime, /debugDiagnose|runDebugDiagnose/);
  assert.match(runtime, /parseContextFiles|debugContextJson/);
  assert.match(core, /loopPhaseLabel/);
  assert.match(core, /mergeJobEvents|JOB_TERMINAL/);
  assert.match(fb, /useCodingLive|Nieuwe taak/);
  assert.match(symbols, /embeddings": False|embeddings": False/);
  assert.match(symbols, /embeddings_note/);
  assert.match(release, /"status": "manual"/);
  assert.match(debug, /review_required/);
  assert.match(debug, /proposed_edits/);
});

test("P0 chat: optimistic replace, provisional stream, live usage card", async () => {
  const chat = await readChat();
  const usage = await read("components/hades/model-usage-card.tsx");
  const main = await read("backend/main.py");
  assert.match(chat, /const optimistic: ChatMessage/);
  assert.match(chat, /filter\(\(item\) => item\.id !== optimistic\.id\)/);
  assert.match(chat, /stream-provisional/);
  assert.match(chat, /model_usage/);
  assert.match(chat, /ModelUsageCard/);
  assert.match(usage, /CURRENT/);
  assert.match(usage, /PEAK/);
  assert.match(usage, /TOTAL/);
  assert.match(usage, /schatting|provider|n\.v\.t\./);
  assert.match(main, /max_parallel_tool_calls/);
  assert.match(main, /estimate_usage_from_response/);
  assert.match(main, /\/api\/chat\/usage-telemetry/);
});

test("HADES-10 Chat-primary navigation and defaults", async () => {
  const app = await read("components/hades/hades-app.tsx");
  const decisions = await read("docs/DECISIONS.md");
  const agents = await read("AGENTS.md");
  const database = await read("backend/database.py");
  assert.match(decisions, /D018 — Chat is the primary intelligence surface/);
  assert.match(agents, /Chat-primary HADES-10/);
  // Lux Atelier IA (werk / kennis / systeem) replaced primary / daily / advanced.
  assert.match(app, /group: "werk"/);
  assert.match(app, /group: "kennis"/);
  assert.match(app, /group: "systeem"/);
  assert.match(app, /id: "chat".*group: "werk"/s);
  assert.match(app, /id: "mission-control".*group: "werk"/s);
  assert.match(app, /return navigation\.some\(\(item\) => item\.id === value\) \? value : "chat"/);
  const composer = await read("components/hades/features/chat/ChatComposer.tsx");
  assert.doesNotMatch(composer, /Multi-file wijzigingen\?/);
  assert.match(composer, /footerMeta/);
  const doctor = await read("components/hades/features/chat/ChatDoctorBanner.tsx");
  assert.match(doctor, /LM Studio werkt, maar er is geen model geladen/);
  assert.match(doctor, /diagnoseChatDoctor/);
  // Fresh-install defaults (Phase 2); explicit stored false remains honored via INSERT OR IGNORE.
  assert.match(database, /"streaming":\s*True/);
  assert.match(database, /"enable_context_compiler_chat":\s*True/);
});
