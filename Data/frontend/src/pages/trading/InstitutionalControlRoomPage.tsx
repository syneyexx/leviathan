import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { ControlRoomView, type ControlRoomPhase } from "./controlRoom/ControlRoomView";
import { buildControlRoomModel } from "./controlRoom/viewModel";

export function InstitutionalControlRoomPage() {
  const [snap, setSnap] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const mounted = useRef(true);
  const generation = useRef(0);

  const pull = useCallback(async (ticket: number) => {
    try {
      const data = await api.marketSimInstitutionalControlRoom();
      if (!mounted.current || ticket !== generation.current) return;
      setSnap(data);
    } catch (err) {
      if (!mounted.current || ticket !== generation.current) return;
      setError(err instanceof Error ? err.message : "Control Room snapshot failed");
    } finally {
      if (mounted.current && ticket === generation.current) setLoading(false);
    }
  }, []);

  const load = useCallback(() => {
    const ticket = ++generation.current;
    setLoading(true);
    setError(null);
    void pull(ticket);
  }, [pull]);

  useEffect(() => {
    mounted.current = true;
    const ticket = ++generation.current;
    void pull(ticket);
    return () => {
      mounted.current = false;
      generation.current += 1;
    };
  }, [pull]);

  const model = useMemo(() => (snap ? buildControlRoomModel(snap) : null), [snap]);
  const phase: ControlRoomPhase = model ? "ready" : error ? "error" : loading ? "loading" : "empty";

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <main className="lv-main lv-tp-main">
        <ControlRoomView
          phase={phase}
          error={error}
          model={model}
          image={tradingHeroes.broker}
          refreshing={loading}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onRefresh={() => void load()}
        />
      </main>
    </AppShell>
  );
}
