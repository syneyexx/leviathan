"use client";

import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/hades/ui";
import { hadesApi } from "@/lib/hades-api";

const KIND_LABEL: Record<string, string> = {
  skill: "Skills",
  knowledge: "Knowledge",
  tool: "Tools",
  tool_provider: "Tool providers",
  mcp_provider: "MCP",
  agent: "Agents",
  service: "Services",
  workflow: "Workflows",
  resource: "Resources",
};

type GroupItem = {
  canonical_id?: string;
  name?: string;
  health?: string;
  cost_class?: string;
  domains?: string[];
  intents?: string[];
};

export function PluginCapabilityGroups({ pluginId }: { pluginId: string }) {
  const [groups, setGroups] = useState<Record<string, GroupItem[]>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    void hadesApi.capabilityIntelPluginGroups(pluginId).then((result) => {
      if (cancelled) return;
      setGroups((result.groups || {}) as Record<string, GroupItem[]>);
    }).catch((reason: Error) => {
      if (cancelled) return;
      setError(reason.message || "Capability-groepen laden mislukt.");
    });
    return () => { cancelled = true; };
  }, [pluginId]);

  const kinds = Object.keys(groups).filter((kind) => (groups[kind] || []).length > 0);
  if (error) {
    return <p className="empty-copy">{error}</p>;
  }
  if (!kinds.length) {
    return <p className="empty-copy">Nog geen genormaliseerde capabilities. Importeer of vernieuw de plugin.</p>;
  }
  return (
    <div className="capability-groups" aria-label="Plugin capabilities">
      {kinds.map((kind) => (
        <div key={kind} className="capability-group">
          <strong>{KIND_LABEL[kind] || kind}</strong>
          <ul>
            {(groups[kind] || []).slice(0, 8).map((item) => (
              <li key={String(item.canonical_id || item.name)}>
                <span>{item.name}</span>
                <StatusBadge tone={item.health === "available" ? "success" : item.health === "blocked" ? "danger" : "neutral"}>
                  {String(item.health || "unknown")}
                </StatusBadge>
                {item.cost_class ? <em>{item.cost_class}</em> : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
