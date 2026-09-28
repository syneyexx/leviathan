import { extractStageResults, type CandidateRecord } from "../viewModels";

/** Compact SVG lineage from real parent_refs — no invented edges. */
export function LineageMiniGraph({
  candidates,
  bestId,
}: {
  candidates: CandidateRecord[];
  bestId: string | null;
}) {
  if (candidates.length === 0) {
    return (
      <div className="lv-rl-empty" style={{ padding: 14 }}>
        <strong>No lineage available yet</strong>
        Parent links appear when candidates carry parent_refs.
      </div>
    );
  }

  const byGen = new Map<number, CandidateRecord[]>();
  for (const c of candidates) {
    const g = Number(c.generation || 0);
    if (!byGen.has(g)) byGen.set(g, []);
    byGen.get(g)!.push(c);
  }
  const gens = [...byGen.keys()].sort((a, b) => a - b).slice(-4);
  const width = 280;
  const height = 150;
  const colW = width / Math.max(gens.length, 1);
  const positions = new Map<string, { x: number; y: number; label: string }>();

  gens.forEach((g, gi) => {
    const rows = byGen.get(g) || [];
    const shown = rows.slice(0, 5);
    shown.forEach((c, ri) => {
      const id = String(c.candidate_id);
      const x = colW * gi + colW / 2;
      const y = 24 + ri * 24;
      positions.set(id, {
        x,
        y,
        label: `v${g}-${id.slice(-2)}`,
      });
    });
  });

  const edges: Array<{ x1: number; y1: number; x2: number; y2: number }> = [];
  for (const c of candidates) {
    const id = String(c.candidate_id);
    const to = positions.get(id);
    if (!to) continue;
    const parents = (Array.isArray(c.parent_refs) ? c.parent_refs : []) as Record<string, unknown>[];
    for (const p of parents) {
      const pid = String(p.candidate_id || "");
      const from = positions.get(pid);
      if (from) edges.push({ x1: from.x, y1: from.y, x2: to.x, y2: to.y });
    }
  }

  // If no parent edges in view, still show nodes by generation columns
  return (
    <svg className="lv-rl-lineage-mini" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Candidate lineage">
      {edges.map((e, i) => (
        <path
          key={i}
          className="edge"
          d={`M${e.x1},${e.y1} C${(e.x1 + e.x2) / 2},${e.y1} ${(e.x1 + e.x2) / 2},${e.y2} ${e.x2},${e.y2}`}
        />
      ))}
      {[...positions.entries()].map(([id, p]) => {
        const best = bestId != null && id === bestId;
        const c = candidates.find((x) => String(x.candidate_id) === id);
        const train = c ? extractStageResults(c).TRAIN : undefined;
        return (
          <g key={id}>
            <rect
              className={best ? "node-best" : "node"}
              x={p.x - 28}
              y={p.y - 9}
              width={56}
              height={18}
              rx={4}
            />
            <text x={p.x} y={p.y + 3} textAnchor="middle">
              {p.label}
              {train?.accepted === false ? " !" : ""}
            </text>
          </g>
        );
      })}
      {edges.length === 0 ? (
        <text x={width / 2} y={height - 8} textAnchor="middle" style={{ fill: "rgba(232,228,220,0.35)" }}>
          Generations shown · parent edges when present
        </text>
      ) : null}
    </svg>
  );
}
