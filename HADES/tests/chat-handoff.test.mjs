import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

function resolveDashboardRoute(opts) {
  if (opts.selected === "lokaal") return "lokaal";
  if (opts.selected === "omniroute") {
    if (!opts.omniUsable) throw new Error("OmniRoute is niet beschikbaar.");
    return "omniroute";
  }
  if (opts.lmConnected) return "lokaal";
  if (opts.omniUsable) return "omniroute";
  return "lokaal";
}

test("chat-handoff module exposes Dashboard → Chat/Coding keys", async () => {
  const source = await read("lib/chat-handoff.ts");
  assert.match(source, /hades-pending-chat-draft/);
  assert.match(source, /hades-pending-chat-handoff/);
  assert.match(source, /hades-pending-coding-goal/);
  assert.match(source, /resolveDashboardRoute/);
  assert.match(source, /writeChatHandoff/);
  assert.match(source, /consumeChatHandoff/);
});

test("resolveDashboardRoute Auto prefers local when LM connected", () => {
  assert.equal(resolveDashboardRoute({ selected: "auto", omniUsable: true, lmConnected: true }), "lokaal");
});

test("resolveDashboardRoute Auto falls back to OmniRoute when LM offline", () => {
  assert.equal(resolveDashboardRoute({ selected: "auto", omniUsable: true, lmConnected: false }), "omniroute");
});

test("resolveDashboardRoute refuses unavailable OmniRoute", () => {
  assert.throws(() => resolveDashboardRoute({ selected: "omniroute", omniUsable: false, lmConnected: true }));
});

test("FINALBETA dashboard is mockup landing with shell navigation", async () => {
  const dash = await read("components/hades/finalbeta/pages/dashboard-page.tsx");
  assert.match(dash, /FinalBetaShell/);
  assert.match(dash, /dash-app/);
  assert.match(dash, /dash-welcome/);
  assert.match(dash, /useDashboardLive/);
  assert.match(dash, /Actieve chatmodel/);
  assert.match(dash, /Actieve code model/);
  assert.match(dash, /onNavigate/);
  assert.match(dash, /model-training/);
  assert.match(dash, /tasks/);
  assert.match(dash, /Snelle acties/);
  assert.doesNotMatch(dash, /SIDE_LINKS/);
  assert.doesNotMatch(dash, /Beschrijf je volgende missie/);
});

test("FINALBETA dashboard CSS uses v2 dash-app layout", async () => {
  const css = await read("components/hades/styles/finalbeta/v2/dashboard.css");
  const indexCss = await read("components/hades/styles/finalbeta/index.css");
  const contractCss = await read("components/hades/styles/finalbeta/contract.css");
  assert.match(css, /\.fb-root \.dash-app/);
  assert.match(css, /\.fb-root \.dash-main/);
  assert.match(css, /\.fb-root \.dash-welcome/);
  assert.match(indexCss, /@import "\.\/v2\/dashboard\.css"/);
  assert.match(indexCss, /@import "\.\/contract\.css"/);
  assert.match(contractCss, /\.fb-root \.fb-toast/);
});

test("Chat page consumes structured handoff with autoSend", async () => {
  const chat = await read("components/hades/pages/chat-page.tsx");
  assert.match(chat, /consumeChatHandoff/);
  assert.match(chat, /pendingAutoSendRef/);
});
