"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, Check, Download, FileText, Loader2, MessageSquareText, Mic } from "lucide-react";
import { hadesApi } from "@/lib/hades-api";

export const MENTION_KINDS = [
  "memory",
  "file",
  "agent",
  "plugin",
  "research",
  "codebase",
  "knowledge",
  "task",
] as const;

export type MentionKind = (typeof MENTION_KINDS)[number];

export type MentionSuggestion = {
  id: string;
  kind: MentionKind | "kind" | "command";
  label: string;
  detail?: string;
  insert: string;
};

type ActiveMention = {
  atIndex: number;
  kind: string;
  ref: string;
  hasColon: boolean;
};

type ActiveSlash = {
  query: string;
};

const SLASH_COMMANDS: MentionSuggestion[] = [
  {
    id: "command:help",
    kind: "command",
    label: "/help",
    detail: "Toon alle beschikbare HADES-commando's",
    insert: "/help ",
  },
  {
    id: "command:harvest",
    kind: "command",
    label: "/harvest",
    detail: "Download documenten van een URL · aliases: /download, /crawl",
    insert: "/harvest ",
  },
  {
    id: "command:remember",
    kind: "command",
    label: "/remember",
    detail: "Maak een geheugenvoorstel van tekst die je wilt bewaren",
    insert: "/remember ",
  },
  {
    id: "command:voice",
    kind: "command",
    label: "/voice",
    detail: "Maak een taak uit een lokale transcriptie of geplakte tekst",
    insert: "/voice ",
  },
  {
    id: "command:plan",
    kind: "command",
    label: "/plan",
    detail: "Forceer diepe planning voor deze beurt",
    insert: "/plan ",
  },
  {
    id: "command:verify",
    kind: "command",
    label: "/verify",
    detail: "Forceer maximale verificatie voor deze beurt",
    insert: "/verify ",
  },
];

function parseActiveSlash(text: string, cursor: number): ActiveSlash | null {
  const before = text.slice(0, cursor);
  const match = before.match(/^\/(?<query>[a-z-]*)$/i);
  if (!match) return null;
  return { query: (match.groups?.query || "").toLowerCase() };
}

function filterSlashCommands(query: string): MentionSuggestion[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter((item) => {
    const haystack = `${item.label.slice(1)} ${item.detail || ""}`.toLowerCase();
    return haystack.includes(needle);
  });
}

function parseActiveMention(text: string, cursor: number): ActiveMention | null {
  const before = text.slice(0, cursor);
  const atIndex = before.lastIndexOf("@");
  if (atIndex < 0) return null;
  const segment = before.slice(atIndex);
  if (/\s/.test(segment.slice(1)) && !segment.includes(":")) return null;
  const match = segment.match(/^@(?<kind>[a-z]*)?(?::(?<ref>[^\s]*))?$/i);
  if (!match) return null;
  const between = before.slice(0, atIndex);
  if (between.length && !/[\s([{]$/.test(between.slice(-1))) return null;
  return {
    atIndex,
    kind: (match.groups?.kind || "").toLowerCase(),
    ref: match.groups?.ref || "",
    hasColon: segment.includes(":"),
  };
}

function filterKinds(partial: string): MentionSuggestion[] {
  const needle = partial.toLowerCase();
  return MENTION_KINDS
    .filter((kind) => !needle || kind.startsWith(needle))
    .map((kind) => ({
      id: `kind:${kind}`,
      kind: "kind",
      label: `@${kind}`,
      detail: "Context-hint voor chat",
      insert: `@${kind}:`,
    }));
}

async function fetchSuggestions(kind: MentionKind, ref: string): Promise<MentionSuggestion[]> {
  const query = ref.trim();
  switch (kind) {
    case "memory": {
      const result = await hadesApi.memories(query, "");
      return result.items.slice(0, 8).map((item) => ({
        id: `memory:${item.id}`,
        kind,
        label: item.title,
        detail: item.summary || item.content.slice(0, 80),
        insert: `@memory:${item.title.replace(/\s+/g, "_")}`,
      }));
    }
    case "file": {
      const result = await hadesApi.files();
      const files = result.files
        .filter((file) => !query || file.name.toLowerCase().includes(query.toLowerCase()) || file.path.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 8);
      return files.map((file) => ({
        id: `file:${file.id}`,
        kind,
        label: file.name,
        detail: file.path,
        insert: `@file:${file.name}`,
      }));
    }
    case "agent": {
      const result = await hadesApi.agents();
      const agents = result.items
        .filter((agent: { id: string; name: string }) => !query || `${agent.id} ${agent.name}`.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 8);
      return agents.map((agent: { id: string; name: string }) => ({
        id: `agent:${agent.id}`,
        kind,
        label: agent.name,
        detail: agent.id,
        insert: `@agent:${agent.id}`,
      }));
    }
    case "plugin": {
      const result = await hadesApi.plugins();
      return result.plugins
        .filter((plugin) => !query || `${plugin.id} ${plugin.name}`.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 8)
        .map((plugin) => ({
          id: `plugin:${plugin.id}`,
          kind,
          label: plugin.name,
          detail: plugin.id,
          insert: `@plugin:${plugin.id}`,
        }));
    }
    case "research": {
      const result = await hadesApi.research();
      return result.projects
        .filter((project) => !query || `${project.id} ${project.title} ${project.topic}`.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 8)
        .map((project) => ({
          id: `research:${project.id}`,
          kind,
          label: project.title || project.topic,
          detail: project.status,
          insert: `@research:${project.id}`,
        }));
    }
    case "codebase": {
      const result = await hadesApi.searchSymbols({ query, limit: 8 });
      return (result.symbols || []).map((symbol, index) => ({
        id: `codebase:${symbol.path}:${symbol.line}:${index}`,
        kind,
        label: symbol.name,
        detail: `${symbol.kind} · ${symbol.path}:${symbol.line}`,
        insert: `@codebase:${symbol.name}`,
      }));
    }
    case "knowledge": {
      if (!query) {
        const lib = await hadesApi.knowledge();
        return lib.sources.slice(0, 8).map((source) => ({
          id: `knowledge:${source.id}`,
          kind,
          label: source.title,
          detail: source.source_type,
          insert: `@knowledge:${source.title.replace(/\s+/g, "_")}`,
        }));
      }
      const result = await hadesApi.searchKnowledge(query, 8);
      return result.matches.map((match) => ({
        id: `knowledge:${match.chunk_id}`,
        kind,
        label: match.title,
        detail: match.heading || match.source_type,
        insert: `@knowledge:${match.title.replace(/\s+/g, "_")}`,
      }));
    }
    case "task": {
      const tasks = await hadesApi.tasks();
      return tasks
        .filter((task) => !query || `${task.id} ${task.title}`.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 8)
        .map((task) => ({
          id: `task:${task.id}`,
          kind,
          label: task.title,
          detail: task.status,
          insert: `@task:${task.id}`,
        }));
    }
    default:
      return [];
  }
}

export function useMentionAutocomplete(draft: string, cursor: number) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<MentionSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [error, setError] = useState("");
  const seq = useRef(0);

  const activeSlash = parseActiveSlash(draft, cursor);
  const activeMention = parseActiveMention(draft, cursor);

  useEffect(() => {
    if (activeSlash) {
      const suggestions = filterSlashCommands(activeSlash.query);
      setOpen(true);
      setLoading(false);
      setItems(suggestions);
      setError(suggestions.length ? "" : "Geen HADES-commando gevonden.");
      setActiveIndex(0);
      return;
    }

    if (!activeMention) {
      setOpen(false);
      setItems([]);
      setLoading(false);
      setError("");
      return;
    }

    const currentSeq = ++seq.current;
    const kindValid = MENTION_KINDS.includes(activeMention.kind as MentionKind);
    if (!kindValid) {
      setOpen(true);
      setLoading(false);
      setError("");
      setItems(filterKinds(activeMention.kind));
      setActiveIndex(0);
      return;
    }
    if (!activeMention.hasColon && !activeMention.ref) {
      setOpen(true);
      setLoading(false);
      setError("");
      setItems([{
        id: `kind-only:${activeMention.kind}`,
        kind: activeMention.kind as MentionKind,
        label: `@${activeMention.kind}`,
        detail: "Typ : om te zoeken",
        insert: `@${activeMention.kind}:`,
      }]);
      setActiveIndex(0);
      return;
    }
    setOpen(true);
    setLoading(true);
    setError("");
    const timer = window.setTimeout(() => {
      void fetchSuggestions(activeMention.kind as MentionKind, activeMention.ref)
        .then((suggestions) => {
          if (seq.current !== currentSeq) return;
          setItems(suggestions);
          setActiveIndex(0);
          if (!suggestions.length) setError("Geen lokale treffers voor deze @-mention.");
        })
        .catch((reason: unknown) => {
          if (seq.current !== currentSeq) return;
          setItems([]);
          setError(reason instanceof Error ? reason.message : "Suggesties laden mislukt.");
        })
        .finally(() => {
          if (seq.current === currentSeq) setLoading(false);
        });
    }, 180);
    return () => window.clearTimeout(timer);
  }, [activeSlash?.query, activeMention?.atIndex, activeMention?.kind, activeMention?.ref, activeMention?.hasColon, draft, cursor]);

  const applySuggestion = useCallback((suggestion: MentionSuggestion, value: string, caret: number) => {
    if (suggestion.kind === "command") {
      const slash = parseActiveSlash(value, caret);
      if (!slash) return { next: value, nextCursor: caret };
      const after = value.slice(caret);
      const next = `${suggestion.insert}${after}`;
      const nextCursor = suggestion.insert.length;
      setOpen(false);
      return { next, nextCursor };
    }

    const mention = parseActiveMention(value, caret);
    if (!mention) return { next: value, nextCursor: caret };
    const before = value.slice(0, mention.atIndex);
    const after = value.slice(caret);
    const spacer = after.startsWith(" ") || !after ? "" : " ";
    const next = `${before}${suggestion.insert}${spacer}${after}`;
    const nextCursor = before.length + suggestion.insert.length + spacer.length;
    setOpen(false);
    return { next, nextCursor };
  }, []);

  return {
    open,
    items,
    loading,
    error,
    activeIndex,
    setActiveIndex,
    applySuggestion,
    active: activeSlash ?? activeMention,
  };
}

type MentionAutocompleteListProps = {
  open: boolean;
  items: MentionSuggestion[];
  loading: boolean;
  error: string;
  activeIndex: number;
  onPick: (item: MentionSuggestion) => void;
  onHover: (index: number) => void;
};

function SlashCommandIcon({ id }: { id: string }) {
  const className = "h-4 w-4";
  if (id === "command:harvest") return <Download className={className} />;
  if (id === "command:remember") return <FileText className={className} />;
  if (id === "command:voice") return <Mic className={className} />;
  if (id === "command:plan") return <BrainCircuit className={className} />;
  if (id === "command:verify") return <Check className={className} />;
  return <MessageSquareText className={className} />;
}

export function MentionAutocompleteList({
  open,
  items,
  loading,
  error,
  activeIndex,
  onPick,
  onHover,
}: MentionAutocompleteListProps) {
  if (!open) return null;

  const commandMode = items.some((item) => item.kind === "command") || error.startsWith("Geen HADES-commando");
  if (commandMode) {
    return (
      <div
        className="absolute bottom-[calc(100%+0.45rem)] left-0 z-40 w-[min(25rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-[#ded8cc] bg-[#fffefa]/[.98] p-1.5 shadow-[0_18px_50px_#2d241817] backdrop-blur-xl"
        role="listbox"
        aria-label="HADES slash-commando's"
      >
        <div className="px-2.5 pb-1.5 pt-1 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-[#91897d]">Commando&apos;s</div>
        {!loading && items.length ? items.map((item, index) => (
          <button
            key={item.id}
            type="button"
            role="option"
            aria-selected={index === activeIndex}
            className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition ${index === activeIndex ? "bg-[#efe9de]" : "hover:bg-[#f5f1e9]"}`}
            onMouseEnter={() => onHover(index)}
            onMouseDown={(event) => {
              event.preventDefault();
              onPick(item);
            }}
          >
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-[#e1dbcf] bg-[#fbf8f2] text-[#675c4b] shadow-sm">
              <SlashCommandIcon id={item.id} />
            </span>
            <span className="min-w-0 flex-1">
              <strong className="block text-[0.76rem] font-semibold text-[#2f2b25]">{item.label}</strong>
              <small className="block truncate text-[0.64rem] leading-5 text-[#81796d]">{item.detail}</small>
            </span>
          </button>
        )) : null}
        {!loading && !items.length ? (
          <div className="px-3 py-3 text-[0.68rem] text-[#81796d]">{error || "Geen HADES-commando gevonden."}</div>
        ) : null}
        <div className="mt-1 border-t border-[#ebe5da] px-2.5 pb-1 pt-2 text-[0.58rem] text-[#9a9287]">↑↓ navigeren · Enter/Tab kiezen · Esc sluiten</div>
      </div>
    );
  }

  return (
    <div className="mention-autocomplete" role="listbox" aria-label="@-mention suggesties">
      {loading ? (
        <div className="mention-autocomplete-empty"><Loader2 className="spin" />Lokale suggesties laden…</div>
      ) : null}
      {!loading && items.length ? items.map((item, index) => (
        <button
          key={item.id}
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          className={index === activeIndex ? "active" : ""}
          onMouseEnter={() => onHover(index)}
          onMouseDown={(event) => {
            event.preventDefault();
            onPick(item);
          }}
        >
          <strong>{item.label}</strong>
          <small>{item.kind === "kind" ? item.detail : `${item.kind} · ${item.detail || ""}`}</small>
        </button>
      )) : null}
      {!loading && !items.length ? (
        <div className="mention-autocomplete-empty">{error || "Geen suggesties — typ @memory:, @file:, @agent:, …"}</div>
      ) : null}
    </div>
  );
}
