import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("FINALBETA chat wires to shared HADES chat runtime", async () => {
  const hook = await read("components/hades/finalbeta/hooks/use-chat-live.ts");
  const runtime = await read("components/hades/features/chat/hooks/useHadesChatRuntime.ts");
  const core = await read("components/hades/features/chat/chat-runtime-core.ts");
  const merge = await read("components/hades/features/chat/live-execution-merge.ts");
  const page = await read("components/hades/finalbeta/pages/chat-page.tsx");
  const app = await read("components/hades/finalbeta/finalbeta-app.tsx");
  const classic = await read("components/hades/pages/chat-page.tsx");

  assert.match(hook, /useHadesChatRuntime as useChatLive/);
  assert.match(runtime, /mergeChatToolCalls/);
  assert.match(runtime, /mergeLiveExecutionEvents/);
  assert.match(merge, /export function mergeChatToolCalls/);
  assert.match(merge, /export function mergeLiveExecutionEvents/);
  assert.match(merge, /LIVE_TOOL_CALL_LIMIT = 30/);
  assert.match(merge, /LIVE_EVENT_LIMIT = 40/);
  // Classic/Lux keeps its own append path — FINALBETA-only reconciliation.
  assert.match(classic, /\[\.\.\.\(current\?\.tools \|\| \[\]\), \.\.\.progress\.tools\]\.slice\(-30\)/);
  assert.doesNotMatch(classic, /mergeChatToolCalls/);

  assert.match(runtime, /hadesApi\.sendMessage/);
  assert.match(runtime, /hadesApi\.conversationRuns/);
  assert.match(runtime, /hadesApi\.forgetMemoryScope/);
  assert.match(runtime, /hadesApi\.uploadChatAttachment/);
  assert.match(runtime, /hadesApi\.decideApproval/);
  assert.match(runtime, /hadesApi\.buildJobCancel/);
  assert.match(runtime, /hadesApi\.cancelResearch/);
  assert.match(runtime, /hadesApi\.cancelTask/);
  assert.match(runtime, /hadesApi\.listConversationBranches/);
  assert.match(runtime, /hadesApi\.getConversationPins/);
  assert.match(runtime, /hadesApi\.chatUsageTelemetry/);
  assert.match(runtime, /consumeChatHandoff/);
  assert.match(runtime, /draftAttachmentsFromIds/);
  assert.match(runtime, /attachmentIdsFromPending/);
  assert.match(runtime, /resolveConversationModelId/);
  assert.match(runtime, /collectUnifiedStopTargets/);
  assert.match(runtime, /shouldApplyStreamToSelection/);
  assert.match(runtime, /mapSendResultToExecution/);
  assert.match(runtime, /revise_message_id/);
  assert.match(runtime, /regenerate_of/);
  assert.match(runtime, /attachment_ids/);
  assert.match(runtime, /client_request_id/);
  assert.match(runtime, /reasoningProfileForRequest/);

  assert.match(core, /export function resolveConversationModelId/);
  assert.match(core, /export function collectUnifiedStopTargets/);
  assert.match(core, /CHAT_MAX_ATTACHMENTS = 10/);

  assert.match(page, /useChatLive/);
  assert.match(page, /cancelGeneration/);
  assert.match(page, /deleteConversation/);
  assert.match(page, /ApprovalCard/);
  assert.match(page, /CodingCard/);
  assert.match(page, /ResearchCard/);
  assert.match(page, /WorkCard/);
  assert.match(page, /ExecutionTrace/);
  assert.match(page, /VerificationSummary/);
  assert.match(page, /ContextTurnPanel/);
  assert.match(page, /ModelUsageCard/);
  assert.match(page, /ResultsPanel/);
  assert.match(page, /MentionAutocompleteList/);
  assert.match(page, /VoiceComposerControls/);
  assert.match(page, /ChatDoctorBanner/);
  assert.match(page, /changeReasoningMode/);
  assert.match(page, /changeModel/);
  assert.match(page, /FinalBetaShell/);
  assert.match(page, /chat-layout/);
  assert.doesNotMatch(page, /mocks\/chat/);
  assert.doesNotMatch(page, /data-toast/);
  assert.doesNotMatch(page, /mockChat/);
  assert.doesNotMatch(page, /system_prompt_override/);
  assert.doesNotMatch(page, /update_system_prompt/);

  assert.match(app, /page === "chat"/);
  assert.match(app, /<ChatPage onNavigate=\{navigate\}/);
});

test("FINALBETA chat keeps visual shell classes from mockup", async () => {
  const page = await read("components/hades/finalbeta/pages/chat-page.tsx");
  const css = await read("components/hades/styles/finalbeta/v2/hades.css");

  assert.match(page, /page-title">Chatten/);
  assert.match(page, /className="chat-layout"/);
  assert.match(page, /className="card chat-thread"/);
  assert.match(page, /className="composer"/);
  assert.match(page, /insp-title/);
  assert.match(page, /Open Work Runtime|Work Runtime/);
  assert.match(css, /\.fb-root \.chat-layout/);
  assert.match(css, /\.fb-root \.bubble\.user/);
  assert.match(css, /\.fb-root \.composer textarea/);
  assert.match(css, /\.fb-root \.chat-runtime-panel/);
});

test("Lux chat uses shared model resolution helper", async () => {
  const lux = await read("components/hades/pages/chat-page.tsx");
  assert.match(lux, /resolveConversationModelId/);
  assert.match(lux, /setActiveDefaultModelId/);
});

test("draft save path never hardcodes empty attachment list in shared runtime", async () => {
  const runtime = await read("components/hades/features/chat/hooks/useHadesChatRuntime.ts");
  assert.match(runtime, /saveDraft\(selectedId, draft, attachmentIdsFromPending\(attachments\)\)/);
  assert.doesNotMatch(runtime, /saveDraft\([^)]*,\s*\[\s*\]\s*\)/);
});
