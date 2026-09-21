"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** Expandable turn transparency: what was kept / dropped and why. */
export function ContextTurnPanel({
  retrieval,
}: {
  retrieval?: Record<string, unknown> | null;
}) {
  const [open, setOpen] = useState(false);
  if (!retrieval) return null;

  const compiler = asRecord(retrieval.context_compiler);
  const budget = asRecord(retrieval.context_budget);
  const pins = asRecord(retrieval.pins);
  const hierarchical = asRecord(retrieval.hierarchical_history);
  const capabilityIntel = asRecord(retrieval.capability_intel) || asRecord(compiler?.capability_intel);
  const dropReasons = [
    ...((Array.isArray(compiler?.drop_reasons) ? compiler?.drop_reasons : []) as unknown[]),
    ...((Array.isArray(budget?.drop_events)
      ? (budget?.drop_events as Array<Record<string, unknown>>).map((row) => row.drop_reason)
      : []) as unknown[]),
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const uniqueDrops = Array.from(new Set(dropReasons));
  const kept = Array.isArray(compiler?.kept)
    ? (compiler?.kept as Array<Record<string, unknown>>)
    : Array.isArray(budget?.kept)
      ? (budget?.kept as Array<Record<string, unknown>>)
      : [];
  const dropped = Array.isArray(compiler?.dropped)
    ? (compiler?.dropped as Array<Record<string, unknown>>)
    : Array.isArray(budget?.drop_events)
      ? (budget?.drop_events as Array<Record<string, unknown>>)
      : [];
  const tokenUsed = typeof budget?.used_tokens === "number"
    ? budget.used_tokens
    : typeof compiler?.used_tokens === "number"
      ? compiler.used_tokens
      : null;
  const tokenMax = typeof budget?.max_tokens === "number"
    ? budget.max_tokens
    : typeof compiler?.budget === "number"
      ? compiler.budget
      : null;
  const evidenceStatus = String(compiler?.evidence_status || budget?.evidence_status || "");
  const packRef = String(compiler?.pack_id || compiler?.id || "");

  return (
    <div className="context-turn-panel">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronUp /> : <ChevronDown />}
        Wat zat in deze beurt?
      </Button>
      {open ? (
        <div className="context-turn-body" role="region" aria-label="Context van deze beurt">
          <p>
            Tokens: {tokenUsed != null ? `~${tokenUsed}` : "—"}
            {tokenMax != null ? ` / ${tokenMax}` : ""}
            {tokenUsed != null && tokenMax == null ? " (approx)" : ""}
          </p>
          {pins ? (
            <p>
              Pins: {String(pins.indexed ?? 0)} indexed · {String(pins.stale ?? 0)} stale ·{" "}
              {String(pins.skipped ?? 0)} skipped
            </p>
          ) : null}
          {evidenceStatus ? <p>Evidence: {evidenceStatus}</p> : null}
          {hierarchical ? (
            <p>
              History: {String(hierarchical.mode || "—")}
              {Array.isArray(hierarchical.summary_quality_set)
                ? ` · ${hierarchical.summary_quality_set.join(", ")}`
                : ""}
            </p>
          ) : null}
          {packRef ? <p>Compiler pack: {packRef}</p> : null}
          {capabilityIntel ? (
            <details>
              <summary>Capability intelligence</summary>
              <p>
                Skills: {String(asRecord(compiler?.capability_intel)?.skills ?? "—")}
                {" · "}model calls: {String(capabilityIntel.model_called ? "yes" : "no")}
                {capabilityIntel.composed ? " · composed" : ""}
                {capabilityIntel.mutation_owner ? ` · owner ${String(capabilityIntel.mutation_owner)}` : ""}
              </p>
              {Array.isArray(asRecord(capabilityIntel.routing)?.selected) ? (
                <ul>
                  {(asRecord(capabilityIntel.routing)?.selected as Array<Record<string, unknown>>).slice(0, 6).map((row, index) => (
                    <li key={String(row.canonical_id || index)}>
                      {String(row.kind || "")} — {String(row.name || row.canonical_id || "item")}
                      {Array.isArray(row.reasons) ? ` (${(row.reasons as unknown[]).slice(0, 3).join(", ")})` : ""}
                    </li>
                  ))}
                </ul>
              ) : null}
            </details>
          ) : null}
          {uniqueDrops.length ? (
            <p>Drop reasons: {uniqueDrops.join(", ")}</p>
          ) : (
            <p>Geen drops gerapporteerd.</p>
          )}
          {kept.length ? (
            <details>
              <summary>Kept ({kept.length})</summary>
              <ul>
                {kept.slice(0, 12).map((row, index) => (
                  <li key={String(row.item_id || index)}>
                    {String(row.item_id || row.provenance || "item")}
                    {row.pinned ? " · pin" : ""}
                    {row.why ? ` · ${String(row.why)}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {dropped.length ? (
            <details>
              <summary>Dropped ({dropped.length})</summary>
              <ul>
                {dropped.slice(0, 12).map((row, index) => (
                  <li key={String(row.item_id || index)}>
                    {String(row.item_id || "item")}: {String(row.drop_reason || row.why || "—")}
                    {row.pinned ? " · was pin" : ""}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
