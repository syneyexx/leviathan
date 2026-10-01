import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  sqliteManagerClearsOnDomainSwitch,
  sqliteManagerWriteConfirmOk,
} from "./SqliteManagerPanel";

const panelSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "SqliteManagerPanel.tsx"),
  "utf8",
);
const clientSrc = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../../api/client.ts"),
  "utf8",
);
const settingsCategorySrc = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "../../components/settings/SettingsCategoryContent.tsx",
  ),
  "utf8",
);

describe("SqliteManagerPanel contracts", () => {
  it("lives under Settings → Opslag only", () => {
    expect(settingsCategorySrc).toContain('activeId === "opslag"');
    expect(settingsCategorySrc).toContain("SqliteManagerPanel");
  });

  it("requires explicit CONTROL/KNOWLEDGE/MARKET domain selection", () => {
    expect(panelSrc).toContain('const DOMAINS = ["CONTROL", "KNOWLEDGE", "MARKET"]');
    expect(panelSrc).toContain("switchDomain");
    expect(panelSrc).toContain("clearDomainLocalState");
  });

  it("clears stale domain state when switching", () => {
    expect(sqliteManagerClearsOnDomainSwitch("CONTROL", "KNOWLEDGE")).toBe(true);
    expect(sqliteManagerClearsOnDomainSwitch("CONTROL", "CONTROL")).toBe(false);
    expect(panelSrc).toContain("setSelectedTable(null)");
    expect(panelSrc).toContain("setRowsPage(null)");
    expect(panelSrc).toContain("setQueryResult(\"\")");
  });

  it("separates read console from controlled write", () => {
    expect(panelSrc).toContain("Read query");
    expect(panelSrc).toContain("Controlled write");
    expect(panelSrc).toContain("sqliteMutate");
    expect(panelSrc).toContain("confirmDomain");
  });

  it("enforces write confirm matching selected domain", () => {
    expect(sqliteManagerWriteConfirmOk("KNOWLEDGE", "knowledge")).toBe(true);
    expect(sqliteManagerWriteConfirmOk("KNOWLEDGE", "CONTROL")).toBe(false);
  });

  it("covers explorer pagination, integrity, runtime sections", () => {
    expect(panelSrc).toContain("Explorer");
    expect(panelSrc).toContain("sqliteQueryRows");
    expect(panelSrc).toContain("Integrity");
    expect(panelSrc).toContain("sqliteOwnershipAudit");
    expect(panelSrc).toContain("Runtime");
    expect(panelSrc).toContain("sqliteRuntime");
  });

  it("wires typed client methods for the extended /api/sqlite family", () => {
    expect(clientSrc).toContain("sqliteTableDetail");
    expect(clientSrc).toContain("sqliteQueryRows");
    expect(clientSrc).toContain("sqliteInsertRow");
    expect(clientSrc).toContain("sqliteUpdateRow");
    expect(clientSrc).toContain("sqliteDeleteRow");
    expect(clientSrc).toContain("sqliteIntegrity");
    expect(clientSrc).toContain("sqliteWalCheckpoint");
    expect(clientSrc).toContain("sqliteOwnershipAudit");
    expect(clientSrc).toContain("sqliteRuntime");
  });
});
