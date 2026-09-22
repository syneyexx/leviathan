/**
 * LEVIATHAN STUDIO — design problems / issues scanner.
 */

import { parseEntryKey } from "../identity.js";
import { listChecks, registerCheck } from "./registry.js";

export function createIssues(ctx) {
  let findings = [];
  let lastScan = 0;
  let timer = 0;
  let gen = 0;

  function seedBuiltinChecks() {
    if (listChecks().length) return;
    registerCheck({
      id: "duplicate-node-ids",
      category: "Persistence",
      severity: "error",
      run(doc) {
        const seen = new Map();
        const out = [];
        for (const [key, entry] of Object.entries(doc.entries || {})) {
          const id = entry?.nodeId || (key.startsWith("node:") ? key.slice(5) : null);
          if (!id) continue;
          if (seen.has(id)) {
            out.push({
              id: `dup-${id}`,
              rule: "duplicate-node-ids",
              category: "Persistence",
              severity: "error",
              message: `Dubbele node-ID: ${id}`,
              nodeKey: key,
              evidence: `Ook in ${seen.get(id)}`,
            });
          } else seen.set(id, key);
        }
        return out;
      },
    });
    registerCheck({
      id: "ambiguous-legacy",
      category: "Persistence",
      severity: "warning",
      run(doc) {
        return (doc.meta?.ambiguous || []).map((a) => ({
          id: `amb-${a.key}`,
          rule: "ambiguous-legacy",
          category: "Persistence",
          severity: "warning",
          message: `Legacy selector niet betrouwbaar gekoppeld: ${a.key}`,
          nodeKey: a.key,
          evidence: a.hint || a.reason,
        }));
      },
    });
    registerCheck({
      id: "missing-alt",
      category: "Accessibility",
      severity: "warning",
      run(doc, { document: docEl }) {
        if (!docEl) return [];
        const out = [];
        docEl.querySelectorAll("img").forEach((img) => {
          if (img.closest?.("#lvb-root")) return;
          const alt = img.getAttribute("alt");
          if (alt == null || alt === "") {
            out.push({
              id: `alt-${img.dataset.lvbNode || img.src || Math.random()}`,
              rule: "missing-alt",
              category: "Accessibility",
              severity: "warning",
              message: "Afbeelding zonder alt-tekst",
              nodeKey: img.dataset.lvbNode ? `node:${img.dataset.lvbNode}` : null,
              evidence: img.getAttribute("src") || "",
            });
          }
        });
        return out;
      },
    });
    registerCheck({
      id: "invalid-token-ref",
      category: "Tokens",
      severity: "error",
      run(doc, { files }) {
        const tokens = files?.["tokens.css"] || "";
        const defined = new Set([...tokens.matchAll(/--([\w-]+)\s*:/g)].map((m) => `--${m[1]}`));
        const out = [];
        for (const [key, entry] of Object.entries(doc.entries || {})) {
          const styles = { ...(entry.styles || {}) };
          for (const bp of Object.values(entry.breakpoints || {})) Object.assign(styles, bp);
          for (const [prop, value] of Object.entries(styles)) {
            const refs = String(value || "").match(/var\((--[\w-]+)/g) || [];
            for (const ref of refs) {
              const name = ref.slice(4);
              if (!defined.has(name)) {
                out.push({
                  id: `tok-${key}-${prop}-${name}`,
                  rule: "invalid-token-ref",
                  category: "Tokens",
                  severity: "error",
                  message: `Ongeldige tokenreferentie ${name}`,
                  nodeKey: key,
                  evidence: `${prop}: ${value}`,
                });
              }
            }
          }
        }
        return out;
      },
    });
    registerCheck({
      id: "non-finite-geometry",
      category: "Layout",
      severity: "error",
      run(doc) {
        const out = [];
        for (const [key, entry] of Object.entries(doc.entries || {})) {
          for (const prop of ["left", "top", "width", "height"]) {
            const v = entry[prop] || entry.styles?.[prop];
            if (v == null) continue;
            if (/NaN|Infinity/i.test(String(v))) {
              out.push({
                id: `geom-${key}-${prop}`,
                rule: "non-finite-geometry",
                category: "Layout",
                severity: "error",
                message: `Niet-eindige geometrie: ${prop}`,
                nodeKey: key,
                evidence: String(v),
              });
            }
          }
        }
        return out;
      },
    });
  }

  function scanNow() {
    seedBuiltinChecks();
    const my = ++gen;
    const s = ctx.store.getState();
    const doc = s.content || {};
    const files = s.files || {};
    const collected = [];
    for (const check of listChecks()) {
      try {
        const items = check.run(doc, { files, document: typeof document !== "undefined" ? document : null }) || [];
        collected.push(...items);
      } catch (err) {
        collected.push({
          id: `check-fail-${check.id}`,
          rule: check.id,
          category: check.category || "Persistence",
          severity: "warning",
          message: `Check faalde: ${err.message || err}`,
          evidence: "manual-review",
        });
      }
    }
    if (my !== gen) return findings;
    findings = collected;
    lastScan = Date.now();
    ctx.store.setState({ issueCount: findings.length, issuesEpoch: lastScan });
    return findings;
  }

  function schedule(ms = 280) {
    clearTimeout(timer);
    timer = setTimeout(() => scanNow(), ms);
  }

  function list({ category, query } = {}) {
    let rows = findings;
    if (category) rows = rows.filter((r) => r.category === category);
    if (query) {
      const q = query.toLowerCase();
      rows = rows.filter((r) => `${r.message} ${r.rule} ${r.nodeKey || ""}`.toLowerCase().includes(q));
    }
    return rows;
  }

  function focusFinding(id) {
    const hit = findings.find((f) => f.id === id);
    if (!hit?.nodeKey) return;
    const parsed = parseEntryKey(hit.nodeKey);
    let el = null;
    if (parsed.kind === "node") el = document.querySelector(`[data-lvb-node="${CSS.escape(parsed.nodeId)}"]`);
    else {
      try {
        el = document.querySelector(hit.nodeKey);
      } catch {
        el = null;
      }
    }
    if (el) ctx.selection.set([el], el);
  }

  return {
    scanNow,
    schedule,
    list,
    focusFinding,
    get findings() {
      return findings;
    },
  };
}
