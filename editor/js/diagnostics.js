/**
 * Leviathan Visual Builder — diagnostics / performance collector.
 * Feeds the Diagnostics panel with live samples + JSON schema.
 */

export function createDiagnostics(ctx) {
  const samples = [];
  const MAX = 180;
  let lastHeap = 0;

  function recordPaint(paintStats) {
    const heap = readHeap();
    const entry = {
      t: Date.now(),
      fps: paintStats.fps || 0,
      frameMs: paintStats.frameMs || 0,
      sceneNodes: paintStats.sceneNodes || 0,
      backend: paintStats.backend || ctx.renderer?.getMode?.() || "dom",
      heapMb: heap,
      selected: ctx.session.selected?.length || 0,
      guides: countGuides(ctx),
      nodes: ctx.content?.ensure?.()?.nodes?.length || 0,
      history: ctx.commands?._debug?.()?.length ?? null,
      dirty: !!(ctx.store.getState().contentDirty || Object.values(ctx.store.getState().dirtyFiles || {}).some(Boolean)),
      page: location.pathname || "/",
      phase: ctx.session.phase || "idle",
    };
    samples.push(entry);
    if (samples.length > MAX) samples.shift();
    lastHeap = heap;
    return entry;
  }

  function snapshot() {
    const paint = ctx.renderer?.getStats?.() || {};
    const gpu = paint.gpu || null;
    const s = ctx.store.getState();
    return {
      schemaVersion: 1,
      timestamp: new Date().toISOString(),
      renderer: {
        backend: ctx.renderer?.getMode?.() || "dom",
        /** Editor paint call frequency — not application FPS */
        editorPaintHz: paint.fps || 0,
        /** CPU duration of last editor paint function — not GPU time */
        editorPaintCpuMs: paint.frameMs || 0,
        sceneNodes: paint.sceneNodes || 0,
        paintCount: paint.paintCount || 0,
        appFps: "niet beschikbaar",
        gpuFrameMs: paint.gpu?.lastFrameMs ?? "niet beschikbaar",
        // legacy aliases
        fps: paint.fps || 0,
        frameMs: paint.frameMs || 0,
      },
      gpu: gpu
        ? {
            adapter: gpu.adapter || {},
            features: gpu.features || [],
            limits: gpu.limits || {},
            vramEstimateMb: gpu.vramEstimateMb ?? null,
            canvas: gpu.canvas || null,
            lastFrameMs: gpu.lastFrameMs,
            drawCount: gpu.drawCount,
          }
        : { available: !!globalThis.navigator?.gpu, active: false },
      memory: {
        jsHeapMb: lastHeap || readHeap(),
        performanceMemory: !!performance.memory,
      },
      editor: {
        selected: ctx.session.selected?.length || 0,
        guides: countGuides(ctx),
        contentNodes: ctx.content?.ensure?.()?.nodes?.length || 0,
        contentEntries: Object.keys(ctx.content?.ensure?.()?.entries || {}).length,
        components: ctx.content?.ensure?.()?.components?.length || 0,
        historyDepth: ctx.commands?._debug?.()?.length ?? 0,
        historyIndex: ctx.commands?._debug?.()?.index ?? -1,
        dirty: !!(s.contentDirty || Object.values(s.dirtyFiles || {}).some(Boolean)),
        autoSave: !!s.autoSave,
        tool: s.tool,
        zoom: s.zoom,
        breakpoint: s.breakpoint,
        page: location.pathname || "/",
        phase: ctx.session.phase,
      },
      samples: samples.slice(-60),
    };
  }

  function sparkline(key = "fps", width = 120, height = 28) {
    const vals = samples.map((s) => Number(s[key]) || 0);
    if (!vals.length) return `<svg width="${width}" height="${height}"></svg>`;
    const max = Math.max(...vals, key === "fps" ? 60 : 1);
    const min = Math.min(...vals, 0);
    const span = Math.max(max - min, 0.001);
    const step = width / Math.max(vals.length - 1, 1);
    const pts = vals
      .map((v, i) => {
        const x = i * step;
        const y = height - ((v - min) / span) * (height - 4) - 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
    return `<svg class="lvb-spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <polyline fill="none" stroke="#d6a957" stroke-width="1.5" points="${pts}" />
    </svg>`;
  }

  return {
    recordPaint,
    snapshot,
    sparkline,
    samples: () => samples.slice(),
  };
}

function readHeap() {
  try {
    if (performance.memory?.usedJSHeapSize) {
      return Math.round((performance.memory.usedJSHeapSize / (1024 * 1024)) * 10) / 10;
    }
  } catch {
    /* unsupported */
  }
  return 0;
}

function countGuides(ctx) {
  const snap = ctx.session._snapGuides;
  if (!snap) return 0;
  return (snap.lineX != null ? 1 : 0) + (snap.lineY != null ? 1 : 0);
}
