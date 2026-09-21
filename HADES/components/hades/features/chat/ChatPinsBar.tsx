"use client";

import { useState } from "react";
import { Folder, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type PinSummary = {
  indexed: number;
  stale: number;
  skipped: number;
  total: number;
  label: string;
};

export type PinBundle = {
  accepted: Array<Record<string, unknown>>;
  skipped: Array<Record<string, unknown>>;
  summary: PinSummary;
};

export function ChatPinsBar({
  bundle,
  busy,
  onAddPath,
  onPickFolder,
  onRemovePath,
}: {
  bundle: PinBundle | null;
  busy?: boolean;
  onAddPath: (path: string) => void;
  onPickFolder: () => void;
  onRemovePath: (path: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const accepted = bundle?.accepted || [];
  const skipped = bundle?.skipped || [];
  const summary = bundle?.summary;

  return (
    <div className="chat-pins-bar" aria-label="Gesprekspins">
      <div className="chat-pins-actions">
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onPickFolder}>
          <Folder />Map pinnen
        </Button>
        <Input
          value={draft}
          placeholder="Pad plakken…"
          aria-label="Pad om te pinnen"
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && draft.trim()) {
              event.preventDefault();
              onAddPath(draft.trim());
              setDraft("");
            }
          }}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy || !draft.trim()}
          onClick={() => {
            if (!draft.trim()) return;
            onAddPath(draft.trim());
            setDraft("");
          }}
        >
          <Plus />Toevoegen
        </Button>
      </div>
      {summary ? (
        <small className="chat-pins-summary">
          {summary.indexed} indexed · {summary.stale} stale · {summary.skipped} skipped
        </small>
      ) : (
        <small className="chat-pins-summary">Geen pins — pin betekent altijd meewegen, niet alles plakken.</small>
      )}
      {accepted.length ? (
        <div className="chat-pins-chips">
          {accepted.map((item) => {
            const path = String(item.path || "");
            const status = String(item.status || "indexed");
            return (
              <span key={path} className={`chat-pin-chip status-${status}`}>
                <span title={path}>{path.split(/[/\\]/).slice(-2).join("/") || path}</span>
                <small>{status}</small>
                <button type="button" aria-label={`Pin ${path} verwijderen`} onClick={() => onRemovePath(path)}>
                  <X />
                </button>
              </span>
            );
          })}
        </div>
      ) : null}
      {skipped.length ? (
        <div className="chat-pins-skipped" role="status">
          {skipped.slice(0, 4).map((item) => (
            <small key={String(item.path)}>
              overgeslagen: {String(item.path)} ({String(item.reason)})
            </small>
          ))}
        </div>
      ) : null}
    </div>
  );
}
