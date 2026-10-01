/**
 * useChatBootstrap — health, models, capabilities, agents/coding flags, memory count.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../api/client";
import type {
  CapabilityListItem,
  HealthResponse,
  ModelDescriptor,
} from "../../../types/api";

export type ChatBootstrapState = {
  bootstrapped: boolean;
  health: HealthResponse | null;
  models: ModelDescriptor[];
  capabilities: CapabilityListItem[];
  agentsEnabled: boolean | null;
  codingEnabled: boolean | null;
  memoryCount: number | null;
  refreshing: boolean;
  refresh: () => Promise<void>;
};

export function useChatBootstrap(): ChatBootstrapState {
  const [bootstrapped, setBootstrapped] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityListItem[]>([]);
  const [agentsEnabled, setAgentsEnabled] = useState<boolean | null>(null);
  const [codingEnabled, setCodingEnabled] = useState<boolean | null>(null);
  const [memoryCount, setMemoryCount] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadMemoryCount = useCallback(async () => {
    try {
      const data = await api.listMemory({ status: "ACTIVE", limit: 100 });
      setMemoryCount(Array.isArray(data.memory) ? data.memory.length : null);
    } catch {
      setMemoryCount(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [healthData, coding, modelData, caps] = await Promise.all([
        api.health().catch(() => null),
        api.codingStatus().catch(() => null),
        api.listModels().catch(() => null),
        api.listCapabilities({ limit: 50 }).catch(() => null),
      ]);
      if (healthData) {
        setHealth(healthData);
        setAgentsEnabled(Boolean(healthData.agents?.enabled));
      } else {
        setHealth(null);
        setAgentsEnabled(null);
      }
      if (coding) {
        setCodingEnabled(Boolean(coding.enabled));
      } else {
        setCodingEnabled(null);
      }
      if (modelData) {
        setModels(modelData.models ?? []);
      }
      if (caps) {
        setCapabilities(caps.capabilities ?? []);
      }
      await loadMemoryCount();
    } finally {
      setRefreshing(false);
      setBootstrapped(true);
    }
  }, [loadMemoryCount]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        await refresh();
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Bootstrap once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    bootstrapped,
    health,
    models,
    capabilities,
    agentsEnabled,
    codingEnabled,
    memoryCount,
    refreshing,
    refresh,
  };
}
