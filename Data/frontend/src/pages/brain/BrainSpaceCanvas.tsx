import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";

import type { LiveBrainEdge, LiveBrainNode } from "./brain-live";
import {
  buildBrainSpaceProjection,
  createBrainSpaceAnimationLoop,
  nodeVisibleAtKnowledgeAge,
  type BrainSpaceDomain,
  type BrainSpaceMode,
  type BrainSpaceNode,
  type BrainSpaceSystem,
} from "./brain-space";

type Point3 = { x: number; y: number; z: number };
type ScreenPoint = { x: number; y: number; z: number; scale: number };
type CameraState = { yaw: number; pitch: number; zoom: number; panX: number; panY: number };

type BrainSpaceCanvasProps = {
  nodes: LiveBrainNode[];
  edges: LiveBrainEdge[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  mode: BrainSpaceMode;
  knowledgeAge: number;
  paused: boolean;
  showLabels: boolean;
  showClusters: boolean;
  showDepth: boolean;
  showRelations: boolean;
  isolatedDomain: BrainSpaceDomain | null;
  onIsolatedDomainChange: (domain: BrainSpaceDomain | null) => void;
  className?: string;
};

const TAU = Math.PI * 2;
const CORE_COLOR = "#E8FBFF";
const DEFAULT_CAMERA: CameraState = { yaw: -0.34, pitch: 0.28, zoom: 0.9, panX: 0, panY: 0 };

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function bodyRadius(node: BrainSpaceNode): number {
  return 3.2 + (node.importance / 100) * 5.2;
}

function drawNebula(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  rgb: readonly [number, number, number],
): void {
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
  gradient.addColorStop(0, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.09)`);
  gradient.addColorStop(0.4, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.03)`);
  gradient.addColorStop(1, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0)`);
  ctx.fillStyle = gradient;
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
}

function projectPoint(
  point: Point3,
  width: number,
  height: number,
  state: CameraState,
): ScreenPoint {
  const cy = Math.cos(state.yaw);
  const sy = Math.sin(state.yaw);
  const x1 = point.x * cy - point.z * sy;
  const z1 = point.x * sy + point.z * cy;
  const cp = Math.cos(state.pitch);
  const sp = Math.sin(state.pitch);
  const y1 = point.y * cp - z1 * sp;
  const z2 = point.y * sp + z1 * cp;
  const depth = Math.max(280, 1060 + z2);
  const scale = (780 / depth) * state.zoom;
  return {
    x: width / 2 + state.panX + x1 * scale,
    y: height / 2 + state.panY + y1 * scale,
    z: z2,
    scale,
  };
}

function systemWorld(
  system: BrainSpaceSystem,
  systemIndex: number,
  simTime: number,
  mode: BrainSpaceMode,
  systemCount: number,
): Point3 {
  if (mode === "systems") {
    const column = systemIndex % 4;
    const rows = Math.ceil(systemCount / 4);
    const row = Math.floor(systemIndex / 4);
    return {
      x: (column - 1.5) * 240,
      y: (row - (rows - 1) / 2) * 265,
      z: (column - 1.5) * 16,
    };
  }
  if (mode === "orbits") {
    const angle = (systemIndex / Math.max(1, systemCount)) * TAU;
    return {
      x: Math.cos(angle) * 385,
      y: Math.sin(angle) * 226,
      z: (systemIndex - (systemCount - 1) / 2) * 30,
    };
  }
  const angle = system.angle + simTime * system.orbitSpeed;
  return {
    x: Math.cos(angle) * system.galRadius,
    y: Math.sin(angle) * system.galRadius * 0.56,
    z: Math.sin(angle * 2) * 72,
  };
}

function nodeWorld(
  node: BrainSpaceNode,
  system: BrainSpaceSystem,
  systemIndex: number,
  simTime: number,
  mode: BrainSpaceMode,
  systemCount: number,
): Point3 {
  const center = systemWorld(system, systemIndex, simTime, mode, systemCount);
  if (node.archived) {
    const pull = 0.62;
    const angle = node.phase + simTime * node.speed * 0.35;
    return {
      x: center.x * (1 - pull) + Math.cos(angle) * 34,
      y: center.y * (1 - pull) + Math.sin(angle) * 20 - 168,
      z: center.z * (1 - pull) - 118 + Math.sin(angle) * 16,
    };
  }
  const angle = node.phase + simTime * node.speed;
  return {
    x: center.x + Math.cos(angle) * node.orbit,
    y: center.y + Math.sin(angle) * node.orbit * 0.52,
    z: center.z + Math.sin(angle + node.tilt) * node.orbit * 0.18,
  };
}

function fitZoom(
  mode: BrainSpaceMode,
  systems: BrainSpaceSystem[],
  width: number,
  height: number,
): number {
  if (!systems.length || width <= 0 || height <= 0) return DEFAULT_CAMERA.zoom;
  const maxNodeOrbit = Math.max(1, ...systems.flatMap((system) => system.nodes.map((node) => node.orbit)));
  let halfWidth = 500;
  let halfHeight = 330;
  if (mode === "galaxy") {
    const maxSystem = Math.max(...systems.map((system) => system.galRadius));
    halfWidth = maxSystem + maxNodeOrbit + 35;
    halfHeight = maxSystem * 0.56 + maxNodeOrbit * 0.56 + 60;
  } else if (mode === "orbits") {
    halfWidth = 385 + maxNodeOrbit + 30;
    halfHeight = 226 + maxNodeOrbit * 0.56 + 50;
  } else {
    const rows = Math.ceil(systems.length / 4);
    halfWidth = 360 + maxNodeOrbit + 35;
    halfHeight = Math.max(140, ((rows - 1) / 2) * 265) + maxNodeOrbit * 0.56 + 55;
  }
  const basePerspective = 780 / 1060;
  const xZoom = (width * 0.82) / (halfWidth * 2 * basePerspective);
  const yZoom = (height * 0.72) / (halfHeight * 2 * basePerspective);
  return clamp(Math.min(xZoom, yZoom), 0.42, 1.25);
}

export function BrainSpaceCanvas({
  nodes,
  edges,
  selectedId,
  onSelect,
  mode,
  knowledgeAge,
  paused,
  showLabels,
  showClusters,
  showDepth,
  showRelations,
  isolatedDomain,
  onIsolatedDomainChange,
  className,
}: BrainSpaceCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const loopRef = useRef<ReturnType<typeof createBrainSpaceAnimationLoop> | null>(null);
  const draggingRef = useRef<{ pointerId: number; x: number; y: number; moved: boolean } | null>(null);
  const suppressClickRef = useRef(false);
  const mouseRef = useRef({ x: -10_000, y: -10_000 });
  const hoverIdRef = useRef<string | null>(null);
  const screenByIdRef = useRef(new Map<string, ScreenPoint>());
  const [camera, setCamera] = useState<CameraState>(DEFAULT_CAMERA);
  const cameraRef = useRef(camera);

  const projection = useMemo(() => buildBrainSpaceProjection(nodes, edges), [nodes, edges]);
  const projectionRef = useRef(projection);
  const propsRef = useRef({
    edges,
    isolatedDomain,
    knowledgeAge,
    mode,
    paused,
    selectedId,
    showLabels,
    showClusters,
    showDepth,
    showRelations,
  });

  useEffect(() => {
    cameraRef.current = camera;
  }, [camera]);
  useEffect(() => {
    projectionRef.current = projection;
  }, [projection]);
  useEffect(() => {
    propsRef.current = {
      edges,
      isolatedDomain,
      knowledgeAge,
      mode,
      paused,
      selectedId,
      showLabels,
      showClusters,
      showDepth,
      showRelations,
    };
    loopRef.current?.setPaused(paused);
  }, [edges, isolatedDomain, knowledgeAge, mode, paused, selectedId, showLabels, showClusters, showDepth, showRelations]);

  const starfield = useMemo(
    () =>
      Array.from({ length: 300 }, (_, index) => ({
        x: (hashString(`brain-space-star-x:${index}`) % 10_000) / 10_000,
        y: (hashString(`brain-space-star-y:${index}`) % 10_000) / 10_000,
        size: index % 23 === 0 ? 1.7 : index % 7 === 0 ? 1.05 : 0.55,
        alpha: 0.08 + (hashString(`brain-space-star-a:${index}`) % 4_000) / 10_000,
        phase: (hashString(`brain-space-star-p:${index}`) % 6_283) / 1_000,
        depth: 0.25 + (hashString(`brain-space-star-d:${index}`) % 7_500) / 10_000,
      })),
    [],
  );

  const fit = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;
    const rect = host.getBoundingClientRect();
    const zoom = fitZoom(mode, projection.systems, rect.width, rect.height);
    setCamera({ ...DEFAULT_CAMERA, zoom });
  }, [mode, projection]);

  const focusSelected = useCallback(() => {
    if (!selectedId) return;
    const point = screenByIdRef.current.get(selectedId);
    const host = hostRef.current;
    if (!point || !host) return;
    const rect = host.getBoundingClientRect();
    setCamera((previous) => ({
      ...previous,
      panX: previous.panX + rect.width / 2 - point.x,
      panY: previous.panY + rect.height / 2 - point.y,
    }));
  }, [selectedId]);

  useEffect(() => {
    const frame = requestAnimationFrame(fit);
    return () => cancelAnimationFrame(frame);
  }, [fit]);

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return;
    const resize = () => {
      const rect = host.getBoundingClientRect();
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
    };
    resize();
    const observer = new ResizeObserver(() => {
      resize();
      fit();
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, [fit]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return;

    const updateTooltip = (next: { id: string; x: number; y: number; label: string; detail: string } | null) => {
      const tip = tooltipRef.current;
      if (!tip) return;
      if (!next) {
        tip.hidden = true;
        hoverIdRef.current = null;
        return;
      }
      tip.hidden = false;
      tip.style.left = `${next.x + 14}px`;
      tip.style.top = `${next.y + 14}px`;
      const strong = tip.querySelector("strong");
      const span = tip.querySelector("span");
      if (strong) strong.textContent = next.label;
      if (span) span.textContent = next.detail;
      hoverIdRef.current = next.id;
    };

    const loop = createBrainSpaceAnimationLoop({
      paused: propsRef.current.paused,
      onFrame: (simTime, _delta, wallNow) => {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        const rect = host.getBoundingClientRect();
        const width = rect.width;
        const height = rect.height;
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

        const live = propsRef.current;
        const activeProjection = projectionRef.current;
        const activeCamera = cameraRef.current;
        ctx.fillStyle = "#02040A";
        ctx.fillRect(0, 0, width, height);

        const background = ctx.createRadialGradient(width * 0.5, height * 0.47, 0, width * 0.5, height * 0.47, Math.max(width, height) * 0.82);
        background.addColorStop(0, "rgba(17,26,44,0.96)");
        background.addColorStop(0.42, "rgba(8,11,20,0.98)");
        background.addColorStop(1, "rgba(2,3,7,1)");
        ctx.fillStyle = background;
        ctx.fillRect(0, 0, width, height);
        drawNebula(ctx, width * 0.72, height * 0.25, 300, [95, 78, 184]);
        drawNebula(ctx, width * 0.33, height * 0.73, 350, [30, 101, 168]);
        drawNebula(ctx, width * 0.79, height * 0.71, 255, [64, 124, 88]);

        for (const star of starfield) {
          const x = star.x * width + Math.sin(wallNow * 0.00004 * (1 + star.depth) + star.phase) * 3 * star.depth;
          const y = star.y * height + Math.cos(wallNow * 0.00003 * (1 + star.depth) + star.phase) * 2 * star.depth;
          const twinkle = 0.76 + Math.sin(wallNow * 0.0014 + star.phase) * 0.24;
          ctx.globalAlpha = star.alpha * twinkle;
          ctx.fillStyle = "#E9F2FF";
          ctx.fillRect(x, y, star.size, star.size);
        }
        ctx.globalAlpha = 1;

        const screenById = new Map<string, { node: BrainSpaceNode; point: ScreenPoint }>();
        const simpleScreenMap = new Map<string, ScreenPoint>();
        const systemScreens: Array<{ system: BrainSpaceSystem; index: number; world: Point3; screen: ScreenPoint }> = [];
        activeProjection.systems.forEach((system, systemIndex) => {
          if (live.isolatedDomain && system.domain !== live.isolatedDomain) return;
          const world = systemWorld(system, systemIndex, simTime, live.mode, activeProjection.systems.length);
          const screen = projectPoint(world, width, height, activeCamera);
          systemScreens.push({ system, index: systemIndex, world, screen });
          for (const node of system.nodes) {
            if (!nodeVisibleAtKnowledgeAge(node, live.knowledgeAge)) continue;
            const point = projectPoint(
              nodeWorld(node, system, systemIndex, simTime, live.mode, activeProjection.systems.length),
              width,
              height,
              activeCamera,
            );
            screenById.set(node.source.id, { node, point });
            simpleScreenMap.set(node.source.id, point);
          }
        });
        screenByIdRef.current = simpleScreenMap;

        if (live.showRelations) {
          for (const edge of live.edges) {
            const source = screenById.get(edge.source);
            const target = screenById.get(edge.target);
            if (!source || !target) continue;
            const emphasized = live.selectedId !== null && (live.selectedId === edge.source || live.selectedId === edge.target);
            const distance = Math.hypot(target.point.x - source.point.x, target.point.y - source.point.y);
            const distant = distance > Math.max(width, height) * 0.58;
            ctx.strokeStyle = emphasized
              ? "rgba(146,229,255,0.34)"
              : distant
                ? "rgba(132,178,220,0.022)"
                : "rgba(132,178,220,0.055)";
            ctx.lineWidth = emphasized ? 1.2 : 0.55;
            ctx.beginPath();
            ctx.moveTo(source.point.x, source.point.y);
            ctx.lineTo(target.point.x, target.point.y);
            ctx.stroke();
          }
        }

        for (const { system, world, screen: sun } of systemScreens) {
          if (!live.showClusters) continue;
          const radii = [...new Set(system.nodes.filter((node) => !node.archived).map((node) => Math.round(node.orbit / 24) * 24))]
            .sort((a, b) => a - b)
            .slice(0, 7);
          ctx.strokeStyle = "rgba(182,206,233,0.045)";
          ctx.lineWidth = 0.65;
          for (const orbit of radii) {
            ctx.beginPath();
            for (let sample = 0; sample <= 36; sample += 1) {
              const angle = (sample / 36) * TAU;
              const orbitPoint = projectPoint(
                {
                  x: world.x + Math.cos(angle) * orbit,
                  y: world.y + Math.sin(angle) * orbit * 0.52,
                  z: world.z + Math.sin(angle) * orbit * 0.16,
                },
                width,
                height,
                activeCamera,
              );
              if (sample === 0) ctx.moveTo(orbitPoint.x, orbitPoint.y);
              else ctx.lineTo(orbitPoint.x, orbitPoint.y);
            }
            ctx.stroke();
          }

          const sunRadius = clamp((10 + Math.sqrt(system.nodes.length) * 0.55) * sun.scale * 1.55, 5, 18);
          const glow = ctx.createRadialGradient(sun.x, sun.y, 0, sun.x, sun.y, sunRadius * 4.2);
          glow.addColorStop(0, "rgba(255,255,255,0.97)");
          glow.addColorStop(0.15, system.palette.sun);
          glow.addColorStop(0.45, `${system.palette.sun}55`);
          glow.addColorStop(1, `${system.palette.sun}00`);
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(sun.x, sun.y, sunRadius * 4.2, 0, TAU);
          ctx.fill();
          ctx.shadowBlur = 20;
          ctx.shadowColor = system.palette.sun;
          ctx.fillStyle = system.palette.sun;
          ctx.beginPath();
          ctx.arc(sun.x, sun.y, sunRadius, 0, TAU);
          ctx.fill();
          ctx.shadowBlur = 0;
          if (live.showLabels) {
            ctx.font = "700 9px 'IBM Plex Sans', 'Segoe UI', sans-serif";
            ctx.fillStyle = "rgba(226,235,246,0.82)";
            ctx.fillText(`${system.domain} · ${system.nodes.length}`, sun.x + sunRadius + 6, sun.y + 3);
          }
        }

        const connected = new Set<string>();
        if (live.showDepth && live.selectedId) {
          connected.add(live.selectedId);
          for (const edge of live.edges) {
            if (edge.source === live.selectedId) connected.add(edge.target);
            if (edge.target === live.selectedId) connected.add(edge.source);
          }
        }

        let nextHover: { id: string; x: number; y: number; label: string; detail: string } | null = null;
        let nearest = 18;
        const sorted = [...screenById.values()].sort((a, b) => a.point.z - b.point.z);
        for (const { node, point } of sorted) {
          if (point.x < -60 || point.x > width + 60 || point.y < -60 || point.y > height + 60) continue;
          const depthDimmed = live.showDepth && live.selectedId != null && !connected.has(node.source.id);
          const depthFactor = live.showDepth ? clamp(0.58 + (1 - (point.z + 400) / 900) * 0.5, 0.38, 1.14) : 1;
          const alpha = depthDimmed ? 0.2 : 1;
          ctx.globalAlpha = alpha;
          const radius = clamp(bodyRadius(node) * point.scale * 1.55 * depthFactor, 2.2, 17);
          const gradient = ctx.createRadialGradient(point.x - radius * 0.42, point.y - radius * 0.42, 0, point.x, point.y, radius * 1.12);
          gradient.addColorStop(0, "#F4FBFF");
          gradient.addColorStop(0.18, node.accent);
          gradient.addColorStop(0.66, node.color);
          gradient.addColorStop(1, "#121722");
          ctx.fillStyle = gradient;
          ctx.shadowBlur = node.recent ? 10 : 4;
          ctx.shadowColor = node.color;
          ctx.beginPath();
          ctx.arc(point.x, point.y, radius, 0, TAU);
          ctx.fill();
          ctx.shadowBlur = 0;

          if (node.style === "ring") {
            ctx.strokeStyle = "rgba(228,238,255,0.34)";
            ctx.beginPath();
            ctx.ellipse(point.x, point.y, radius * 1.75, radius * 0.56, 0.18, 0, TAU);
            ctx.stroke();
          } else if (node.style === "banded") {
            ctx.strokeStyle = "rgba(255,255,255,0.15)";
            ctx.beginPath();
            ctx.ellipse(point.x, point.y, radius * 0.78, radius * 0.15, 0, 0, TAU);
            ctx.stroke();
          }
          if (node.status === "degraded" || node.status === "unavailable") {
            ctx.strokeStyle = node.status === "unavailable" ? "#FF8D9A" : "#FFD978";
            ctx.lineWidth = 1.15;
            ctx.beginPath();
            ctx.arc(point.x, point.y, radius + 2.2, 0, TAU);
            ctx.stroke();
          }
          if (live.selectedId === node.source.id) {
            ctx.strokeStyle = "rgba(255,255,255,0.78)";
            ctx.lineWidth = 1.4;
            ctx.beginPath();
            ctx.arc(point.x, point.y, radius + 5.2, 0, TAU);
            ctx.stroke();
          }
          if (node.recent) {
            const pulse = 1 + Math.sin(simTime * 0.002 + node.radius) * 0.12;
            ctx.strokeStyle = `${node.color}3d`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(point.x, point.y, radius * 2.05 * pulse, 0, TAU);
            ctx.stroke();
          }

          const distance = Math.hypot(mouseRef.current.x - point.x, mouseRef.current.y - point.y);
          const hitRadius = Math.max(10, radius + 5);
          if (distance < hitRadius && distance < nearest) {
            nearest = distance;
            nextHover = {
              id: node.source.id,
              x: point.x,
              y: point.y,
              label: node.source.label,
              detail: `${node.domain} · ${node.source.type}`,
            };
          }
          if (live.showLabels && (live.selectedId === node.source.id || nextHover?.id === node.source.id || activeCamera.zoom > 1.35)) {
            ctx.font = "9px 'IBM Plex Sans', 'Segoe UI', sans-serif";
            ctx.fillStyle = "rgba(214,224,236,0.82)";
            ctx.fillText(node.source.label, point.x + radius + 5, point.y + 3);
          }
        }
        ctx.globalAlpha = 1;

        const core = projectPoint({ x: 0, y: 0, z: 0 }, width, height, activeCamera);
        const coreRadius = clamp(22 * core.scale * 1.55, 10, 28);
        const coreGlow = ctx.createRadialGradient(core.x, core.y, 0, core.x, core.y, coreRadius * 5);
        coreGlow.addColorStop(0, "rgba(255,255,255,0.98)");
        coreGlow.addColorStop(0.15, CORE_COLOR);
        coreGlow.addColorStop(0.46, "rgba(139,236,255,0.18)");
        coreGlow.addColorStop(1, "rgba(139,236,255,0)");
        ctx.fillStyle = coreGlow;
        ctx.beginPath();
        ctx.arc(core.x, core.y, coreRadius * 5, 0, TAU);
        ctx.fill();
        ctx.fillStyle = CORE_COLOR;
        ctx.shadowBlur = 26;
        ctx.shadowColor = CORE_COLOR;
        ctx.beginPath();
        ctx.arc(core.x, core.y, coreRadius, 0, TAU);
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = "rgba(232,251,255,0.08)";
        for (const ring of [coreRadius + 22, coreRadius + 38, coreRadius + 56]) {
          ctx.beginPath();
          ctx.arc(core.x, core.y, ring, 0, TAU);
          ctx.stroke();
        }
        if (live.showLabels) {
          ctx.font = "700 10px 'IBM Plex Sans', 'Segoe UI', sans-serif";
          ctx.fillStyle = "rgba(245,252,255,0.94)";
          ctx.fillText("LEVIATHAN · projection anchor", core.x + coreRadius + 7, core.y + 3);
        }
        updateTooltip(nextHover);
      },
    });

    loopRef.current = loop;
    loop.start();
    return () => {
      loop.stop();
      if (loopRef.current === loop) loopRef.current = null;
    };
  }, [starfield]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    draggingRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    event.currentTarget.classList.add("is-dragging");
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    mouseRef.current = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    const drag = draggingRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    const moved = drag.moved || Math.abs(dx) > 2 || Math.abs(dy) > 2;
    draggingRef.current = { pointerId: drag.pointerId, x: event.clientX, y: event.clientY, moved };
    setCamera((previous) => ({
      ...previous,
      yaw: previous.yaw + dx * 0.0036,
      pitch: clamp(previous.pitch + dy * 0.003, -1.02, 1.02),
    }));
  };

  const stopDragging = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (draggingRef.current?.pointerId !== event.pointerId) return;
    suppressClickRef.current = draggingRef.current.moved;
    draggingRef.current = null;
    event.currentTarget.classList.remove("is-dragging");
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Browser may already have released capture.
    }
  };

  const handleWheel = (event: ReactWheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    setCamera((previous) => ({
      ...previous,
      zoom: clamp(previous.zoom * (event.deltaY > 0 ? 0.91 : 1.09), 0.35, 2.6),
    }));
  };

  const handleClick = () => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    if (hoverIdRef.current) onSelect(hoverIdRef.current);
  };

  const handleDoubleClick = () => {
    const id = hoverIdRef.current;
    if (!id) return;
    const node = projection.byId.get(id);
    if (node) onIsolatedDomainChange(isolatedDomain === node.domain ? null : node.domain);
  };

  const empty = nodes.length === 0;
  return (
    <div ref={hostRef} className={`lv-brain-space-canvas${className ? ` ${className}` : ""}${empty ? " is-empty" : ""}`}>
      <canvas
        ref={canvasRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={stopDragging}
        onPointerCancel={stopDragging}
        onPointerLeave={(event) => {
          mouseRef.current = { x: -10_000, y: -10_000 };
          stopDragging(event);
        }}
        onWheel={handleWheel}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        aria-label="LEVIATHAN Brain celestial graph projection"
      />

      <div className="lv-brain-space-viewport" aria-label="Celestial viewport controls">
        <button type="button" onClick={() => setCamera((previous) => ({ ...previous, zoom: clamp(previous.zoom * 0.86, 0.35, 2.6) }))} aria-label="Zoom out">−</button>
        <span>{Math.round(camera.zoom * 100)}%</span>
        <button type="button" onClick={() => setCamera((previous) => ({ ...previous, zoom: clamp(previous.zoom * 1.16, 0.35, 2.6) }))} aria-label="Zoom in">+</button>
        <button type="button" onClick={fit}>Fit</button>
        {selectedId ? <button type="button" onClick={focusSelected}>Focus</button> : null}
      </div>

      {empty ? <div className="lv-brain-space-empty-state" role="status">No nodes in current Brain projection / filter</div> : null}
      <div ref={tooltipRef} className="lv-brain-space-tooltip" hidden><strong /><span /></div>
      <div className="lv-brain-space-truth" aria-hidden="true">
        <span>Domain suns are projection clusters</span>
        <span>Planets are live Brain nodes</span>
        <span>Double-click isolates a domain</span>
      </div>
    </div>
  );
}
