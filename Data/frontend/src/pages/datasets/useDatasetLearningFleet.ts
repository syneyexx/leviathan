/**
 * Learning fleet for `/datasets?mode=learning` — uses listLearningFleet (no N+1).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { DatasetLearningFleetResponse, DatasetLearningFleetRow } from "../../types/api";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function useDatasetLearningFleet(opts: { enabled: boolean; limit?: number }) {
  const { enabled, limit = 200 } = opts;
  const [fleet, setFleet] = useState<DatasetLearningFleetRow[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [truth, setTruth] = useState<Record<string, unknown> | null>(null);
  const genRef = useRef(0);

  const loadFleet = useCallback(async () => {
    if (!enabled) return;
    const gen = ++genRef.current;
    setLoading(true);
    try {
      const res: DatasetLearningFleetResponse = await api.listLearningFleet(limit);
      if (gen !== genRef.current) return;
      setFleet(res.datasets ?? []);
      setTotal(res.total ?? res.datasets?.length ?? 0);
      setTruth(res.truth ?? null);
      setError(null);
    } catch (err) {
      if (gen !== genRef.current) return;
      setError(errMsg(err, "Learning fleet laden mislukt"));
    } finally {
      if (gen === genRef.current) setLoading(false);
    }
  }, [enabled, limit]);

  useEffect(() => {
    void loadFleet();
  }, [loadFleet]);

  return {
    fleet,
    fleetTotal: total,
    fleetLoading: loading,
    fleetError: error,
    fleetTruth: truth,
    loadFleet,
  };
}
