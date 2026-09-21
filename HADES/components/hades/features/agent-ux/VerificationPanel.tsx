"use client";

import { AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react";
import { StatusBadge } from "@/components/hades/ui";
import type { AcceptanceCheck } from "@/components/hades/features/chat/types";

export function VerificationPanel({
  called,
  expected,
  notes = [],
  checks = [],
}: {
  called?: boolean;
  expected?: boolean;
  notes?: string[];
  checks?: AcceptanceCheck[];
}) {
  if (!called && !expected && !notes.length && !checks.length) return null;
  const failed = checks.some((check) => !check.met);
  const tone = failed ? "danger" : called ? "success" : "warning";
  const Icon = failed || !called ? AlertTriangle : CheckCircle2;
  const statusLabel = failed ? "Niet bevestigd" : called ? "Bevestigd" : "Nog niet uitgevoerd";

  return (
    <section className="verification-panel working-state-box" aria-labelledby="verification-title">
      <header>
        <ShieldCheck aria-hidden="true" />
        <strong id="verification-title">Verificatie</strong>
        <StatusBadge tone={tone}>{statusLabel}</StatusBadge>
      </header>
      {checks.length ? (
        <ul className="acceptance-checklist">
          {checks.map((check) => (
            <li key={check.criterion} className={check.met ? "criterion-met" : "criterion-unmet"}>
              <Icon aria-hidden="true" />
              <span>{check.criterion}{check.note ? <small>{check.note}</small> : null}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {notes.length ? <ul>{notes.map((note) => <li key={note}>{note}</li>)}</ul> : null}
    </section>
  );
}
