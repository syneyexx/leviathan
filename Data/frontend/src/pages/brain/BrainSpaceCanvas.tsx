import {
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

export type BrainSpaceCanvasProps = {
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

type CameraState = {
  yaw: number;
  pitch: number;
  zoom: number;
  panX: number;
  panY: number;
};

const TAU = Math.PI * 2;
const CORE_COLOR = "#E8FBFF";

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

function bodyRadius(node: BrainSpaceNode): number {
  return 3.2 + (node.importance / 100) * 5.2;
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
  const [camera, setCamera] = useState<CameraState>({
    yaw: -0.34,
    pitch: 0.28,
    zoom: 1,
    panX: 0,
    panY: 0,
  });
  const cameraRef = useRef(camera);

  useEffect(() => {
    cameraRef.current = camera;
  }, [camera]);

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
  }, [
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
  ]);

  const projection = useMemo(
    () => buildBrainSpaceProjection(nodes, edges),
    [nodes, edges],
  );
  const projectionRef = useRef(projection);
  useEffect(() => {
    projectionRef.current = projection;
  }, [projection]);

  const starfield = useMemo(
    () =>
      Array.from({ length: 340 }, (_, index) => ({
        x: (hashString(`brain-space-star-x:${index}`) % 10_000) / 10_000,
        y: (hashString(`brain-space-star-y:${index}`) % 10_000) / 10_000,
        size: index % 23 === 0 ? 1.8 : index % 7 === 0 ? 1.1 : 0.55,
        alpha: 0.08 + ((hashString(`brain-space-star-a:${index}`) % 4_000) / 10_000),
        phase: ((hashString(`brain-space-star-p:${index}`) % 6_283) / 1_000),
        depth: 0.25 + ((hashString(`brain-space-star-d:${index}`) % 7_500) / 10_000),
      })),
    [],
  );

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
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return;

    const project = (
      point: Point3,
      width: number,
      height: number,
      state: CameraState,
    ): ScreenPoint => {
      const cy = Math.cos(state.yaw);
      const sy = Math.sin(state.yaw);
      const x1 = point.x * cy - point.z * sy;
      const z1 = point.x * sy + point.z * cy;

      const cp = Math.cos(state.pitch);
      const sp = Math.sin(state.pitch);
      const y1 = point.y * cp - z1 * sp;
      const z2 = point.y * sp + z1 * cp;

      const depth = 1060 + z2;
      const scale = (780 / depth) * state.zoom;
      return {
        x: width / 2 + state.panX + x1 * scale,
        y: height / 2 + state.panY + y1 * scale,
        z: z2,
        scale,
      };
    };

    const systemWorld = (
      system: BrainSpaceSystem,
      systemIndex: number,
      simTime: number,
      activeMode: BrainSpaceMode,
      systemCount: number,
    ): Point3 => {
      if (activeMode === "systems") {
        const column = systemIndex % 4;
        const row = Math.floor(systemIndex / 4);
        return {
          x: (column - 1.5) * 248,
          y: (row - 0.5) * 305,
          z: (column - 1.5) * 18,
        };
      }

      if (activeMode === "orbits") {
        const angle = (systemIndex / Math.max(1, systemCount)) * TAU;
        return {
          x: Math.cos(angle) * 420,
          y: Math.sin(angle) * 252,
          z: (systemIndex - 3.5) * 38,
        };
      }

      const angle = system.angle + simTime * system.orbitSpeed;
      return {
        x: Math.cos(angle) * system.galRadius,
        y: Math.sin(angle) * system.galRadius * 0.56,
        z: Math.sin(angle * 2) * 92,
      };
    };

    const nodeWorld = (
      node: BrainSpaceNode,
      system: BrainSpaceSystem,
      systemIndex: number,
      simTime: number,
      activeMode: BrainSpaceMode,
      systemCount: number,
    ): Point3 => {
      const center = systemWorld(system, systemIndex, simTime, activeMode, systemCount);
      // Archived nodes drift toward the archive singularity (visual projection only).
      if (node.archived) {
        const pull = 0.62;
        const angle = node.phase + simTime * node.speed * 0.35;
        return {
          x: center.x * (1 - pull) + Math.cos(angle) * 36,
          y: center.y * (1 - pull) + Math.sin(angle) * 22 - 180,
          z: center.z * (1 - pull) - 140 + Math.sin(angle) * 18,
        };
      }
      const angle = node.phase + simTime * node.speed;
      return {
        x: center.x + Math.cos(angle) * node.orbit,
        y: center.y + Math.sin(angle) * node.orbit * 0.52,
        z: center.z + Math.sin(angle + node.tilt) * node.orbit * 0.18,
      };
    };

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

        const background = ctx.createRadialGradient(
          width * 0.5,
          height * 0.47,
          0,
          width * 0.5,
          height * 0.47,
          Math.max(width, height) * 0.82,
        );
        background.addColorStop(0, "rgba(17,26,44,0.96)");
        background.addColorStop(0.42, "rgba(8,11,20,0.98)");
        background.addColorStop(1, "rgba(2,3,7,1)");
        ctx.fillStyle = background;
        ctx.fillRect(0, 0, width, height);

        drawNebula(ctx, width * 0.72, height * 0.25, 300, [95, 78, 184]);
        drawNebula(ctx, width * 0.33, height * 0.73, 350, [30, 101, 168]);
        drawNebula(ctx, width * 0.79, height * 0.71, 255, [64, 124, 88]);
        drawNebula(ctx, width * 0.21, height * 0.23, 245, [128, 70, 155]);

        for (const star of starfield) {
          const x =
            star.x * width +
            Math.sin(wallNow * 0.00004 * (1 + star.depth) + star.phase) *
              4 *
              star.depth;
          const y =
            star.y * height +
            Math.cos(wallNow * 0.00003 * (1 + star.depth) + star.phase) *
              3 *
              star.depth;
          const twinkle = 0.72 + Math.sin(wallNow * 0.0018 + star.phase) * 0.28;
          ctx.globalAlpha = star.alpha * twinkle;
          ctx.fillStyle = "#E9F2FF";
          ctx.fillRect(x, y, star.size, star.size);
        }
        ctx.globalAlpha = 1;

        // Archive singularity scenery — interactive only when archived nodes exist.
        const archiveY = -210;
        const archive = project({ x: 0, y: archiveY, z: -160 }, width, height, activeCamera);
        const archiveRadius = clamp(14 * archive.scale * 1.4, 6, 22);
        const archiveGlow = ctx.createRadialGradient(
          archive.x,
          archive.y,
          0,
          archive.x,
          archive.y,
          archiveRadius * 5,
        );
        archiveGlow.addColorStop(0, "rgba(8,10,16,0.95)");
        archiveGlow.addColorStop(0.35, "rgba(40,28,58,0.35)");
        archiveGlow.addColorStop(1, "rgba(40,28,58,0)");
        ctx.fillStyle = archiveGlow;
        ctx.beginPath();
        ctx.arc(archive.x, archive.y, archiveRadius * 5, 0, TAU);
        ctx.fill();
        ctx.fillStyle = "#05060C";
        ctx.beginPath();
        ctx.arc(archive.x, archive.y, archiveRadius, 0, TAU);
        ctx.fill();
        ctx.strokeStyle = "rgba(160,130,210,0.18)";
        ctx.beginPath();
        ctx.arc(archive.x, archive.y, archiveRadius + 4, 0, TAU);
        ctx.stroke();
        if (live.showLabels && activeProjection.archivedCount > 0) {
          ctx.font = "600 8px 'IBM Plex Sans', 'Segoe UI', sans-serif";
          ctx.fillStyle = "rgba(180,168,210,0.55)";
          ctx.fillText(
            `Archive Singularity · ${activeProjection.archivedCount}`,
            archive.x + archiveRadius + 6,
            archive.y + 3,
          );
        }

        const screenById = new Map<string, { node: BrainSpaceNode; point: ScreenPoint }>();
        const systemScreens: Array<{
          system: BrainSpaceSystem;
          index: number;
          world: Point3;
          screen: ScreenPoint;
        }> = [];

        activeProjection.systems.forEach((system, systemIndex) => {
          if (live.isolatedDomain && system.domain !== live.isolatedDomain) return;
          const world = systemWorld(
            system,
            systemIndex,
            simTime,
            live.mode,
            activeProjection.systems.length,
          );
          const screen = project(world, width, height, activeCamera);
          systemScreens.push({ system, index: systemIndex, world, screen });

          for (const node of system.nodes) {
            if (!nodeVisibleAtKnowledgeAge(node, live.knowledgeAge)) continue;
            const nodePoint = project(
              nodeWorld(
                node,
                system,
                systemIndex,
                simTime,
                live.mode,
                activeProjection.systems.length,
              ),
              width,
              height,
              activeCamera,
            );
            screenById.set(node.source.id, { node, point: nodePoint });
          }
        });

        if (live.showRelations) {
          for (const edge of live.edges) {
            const source = screenById.get(edge.source);
            const target = screenById.get(edge.target);
            if (!source || !target) continue;
            const emphasized =
              live.selectedId !== null &&
              (live.selectedId === edge.source || live.selectedId === edge.target);
            ctx.strokeStyle = emphasized
              ? "rgba(146,229,255,0.28)"
              : "rgba(132,178,220,0.045)";
            ctx.lineWidth = emphasized ? 1.15 : 0.55;
            ctx.beginPath();
            ctx.moveTo(source.point.x, source.point.y);
            ctx.lineTo(target.point.x, target.point.y);
            ctx.stroke();
          }
        }

        for (const { system, world, screen: sun } of systemScreens) {
          if (live.showClusters) {
            ctx.strokeStyle = "rgba(182,206,233,0.05)";
            ctx.lineWidth = 0.7;
            for (const node of system.nodes) {
              if (!nodeVisibleAtKnowledgeAge(node, live.knowledgeAge)) continue;
              if (node.archived) continue;
              ctx.beginPath();
              for (let sample = 0; sample <= 38; sample += 1) {
                const angle = node.phase + simTime * node.speed + (sample / 38) * TAU;
                const orbitPoint = project(
                  {
                    x: world.x + Math.cos(angle) * node.orbit,
                    y: world.y + Math.sin(angle) * node.orbit * 0.52,
                    z: world.z + Math.sin(angle + node.tilt) * node.orbit * 0.18,
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

            // Domain sun — projection cluster glyph, NOT a backend Brain node.
            const sunRadius = clamp(
              (10 + Math.sqrt(system.nodes.length) * 0.55) * sun.scale * 1.55,
              5,
              18,
            );
            const sunGlow = ctx.createRadialGradient(
              sun.x,
              sun.y,
              0,
              sun.x,
              sun.y,
              sunRadius * 4.2,
            );
            sunGlow.addColorStop(0, "rgba(255,255,255,0.97)");
            sunGlow.addColorStop(0.15, system.palette.sun);
            sunGlow.addColorStop(0.45, `${system.palette.sun}55`);
            sunGlow.addColorStop(1, `${system.palette.sun}00`);
            ctx.fillStyle = sunGlow;
            ctx.beginPath();
            ctx.arc(sun.x, sun.y, sunRadius * 4.2, 0, TAU);
            ctx.fill();

            ctx.shadowBlur = 24;
            ctx.shadowColor = system.palette.sun;
            ctx.fillStyle = system.palette.sun;
            ctx.beginPath();
            ctx.arc(sun.x, sun.y, sunRadius, 0, TAU);
            ctx.fill();
            ctx.shadowBlur = 0;

            if (live.showLabels) {
              ctx.font = "700 9px 'IBM Plex Sans', 'Segoe UI', sans-serif";
              ctx.fillStyle = "rgba(226,235,246,0.82)";
              ctx.fillText(
                `${system.domain} · ${system.nodes.length}`,
                sun.x + sunRadius + 6,
                sun.y + 3,
              );
            }
          }
        }

        let nextHover: { id: string; x: number; y: number; label: string; detail: string } | null = null;
        let nearest = 16;
        const sorted = [...screenById.values()].sort((a, b) => a.point.z - b.point.z);
        const selectedConnected = new Set<string>();
        if (live.showDepth && live.selectedId) {
          selectedConnected.add(live.selectedId);
          for (const edge of live.edges) {
            if (edge.source === live.selectedId) selectedConnected.add(edge.target);
            if (edge.target === live.selectedId) selectedConnected.add(edge.source);
          }
        }

        for (const { node, point } of sorted) {
          if (
            point.x < -60 ||
            point.x > width + 60 ||
            point.y < -60 ||
            point.y > height + 60
          ) continue;

          const depthDimmed =
            live.showDepth &&
            live.selectedId != null &&
            !selectedConnected.has(node.source.id);
          const depthFactor = live.showDepth
            ? clamp(0.55 + (1 - (point.z + 400) / 900) * 0.55, 0.35, 1.15)
            : 1;
          const alpha = depthDimmed ? 0.22 : 1;

          ctx.globalAlpha = alpha;
          const radius = clamp(
            bodyRadius(node) * point.scale * 1.55 * depthFactor,
            2,
            18,
          );
          const gradient = ctx.createRadialGradient(
            point.x - radius * 0.42,
            point.y - radius * 0.42,
            0,
            point.x,
            point.y,
            radius * 1.12,
          );
          gradient.addColorStop(0, "#F4FBFF");
          gradient.addColorStop(0.18, node.accent);
          gradient.addColorStop(0.66, node.color);
          gradient.addColorStop(1, "#121722");

          ctx.fillStyle = gradient;
          ctx.shadowBlur = node.recent ? 11 : 5;
          ctx.shadowColor = node.color;
          ctx.beginPath();
          ctx.arc(point.x, point.y, radius, 0, TAU);
          ctx.fill();
          ctx.shadowBlur = 0;

          if (node.style === "ring") {
            ctx.strokeStyle = "rgba(228,238,255,0.34)";
            ctx.beginPath();
            ctx.ellipse(point.x, point.y, radius * 1.78, radius * 0.56, 0.18, 0, TAU);
            ctx.stroke();
          } else if (node.style === "banded") {
            ctx.strokeStyle = "rgba(255,255,255,0.15)";
            for (const offset of [-0.18, 0, 0.18]) {
              ctx.beginPath();
              ctx.ellipse(
                point.x,
                point.y + radius * offset,
                radius * 0.78,
                radius * 0.15,
                offset * 0.25,
                0,
                TAU,
              );
              ctx.stroke();
            }
          }

          if (node.status === "degraded" || node.status === "unavailable") {
            ctx.strokeStyle = node.status === "unavailable" ? "#FF8D9A" : "#FFD978";
            ctx.lineWidth = 1.2;
            ctx.beginPath();
            ctx.arc(point.x, point.y, radius + 2.2, 0, TAU);
            ctx.stroke();
          }

          if (live.selectedId === node.source.id) {
            ctx.strokeStyle = "rgba(255,255,255,0.75)";
            ctx.lineWidth = 1.4;
            ctx.beginPath();
            ctx.arc(point.x, point.y, radius + 5.2, 0, TAU);
            ctx.stroke();
          }

          if (node.recent) {
            const pulse = 1 + Math.sin(simTime * 0.005 + node.radius) * 0.18;
            ctx.strokeStyle = `${node.color}44`;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(point.x, point.y, radius * 2.2 * pulse, 0, TAU);
            ctx.stroke();
          }

          const distance = Math.hypot(
            mouseRef.current.x - point.x,
            mouseRef.current.y - point.y,
          );
          const hitRadius = Math.max(9, radius + 4);
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

          if (
            live.showLabels &&
            (live.selectedId === node.source.id ||
              nextHover?.id === node.source.id ||
              activeCamera.zoom > 1.3)
          ) {
            ctx.font = "9px 'IBM Plex Sans', 'Segoe UI', sans-serif";
            ctx.fillStyle = "rgba(214,224,236,0.8)";
            ctx.fillText(node.source.label, point.x + radius + 5, point.y + 3);
          }
        }
        ctx.globalAlpha = 1;

        // Central projection anchor — visual-only unless a real node maps to it.
        const core = project({ x: 0, y: 0, z: 0 }, width, height, activeCamera);
        const coreRadius = clamp(22 * core.scale * 1.55, 10, 30);
        const coreGlow = ctx.createRadialGradient(
          core.x,
          core.y,
          0,
          core.x,
          core.y,
          coreRadius * 5,
        );
        coreGlow.addColorStop(0, "rgba(255,255,255,0.98)");
        coreGlow.addColorStop(0.15, CORE_COLOR);
        coreGlow.addColorStop(0.46, "rgba(139,236,255,0.18)");
        coreGlow.addColorStop(1, "rgba(139,236,255,0)");
        ctx.fillStyle = coreGlow;
        ctx.beginPath();
        ctx.arc(core.x, core.y, coreRadius * 5, 0, TAU);
        ctx.fill();

        ctx.fillStyle = CORE_COLOR;
        ctx.shadowBlur = 30;
        ctx.shadowColor = CORE_COLOR;
        ctx.beginPath();
        ctx.arc(core.x, core.y, coreRadius, 0, TAU);
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.strokeStyle = "rgba(255,255,255,0.14)";
        ctx.beginPath();
        ctx.arc(core.x, core.y, coreRadius + 8, 0, TAU);
        ctx.stroke();

        // Subtle occult / celestial geometry around the anchor.
        ctx.strokeStyle = "rgba(232,251,255,0.08)";
        ctx.lineWidth = 0.7;
        for (const ring of [coreRadius + 22, coreRadius + 38, coreRadius + 58]) {
          ctx.beginPath();
          ctx.arc(core.x, core.y, ring, 0, TAU);
          ctx.stroke();
        }
        ctx.beginPath();
        for (let i = 0; i < 6; i += 1) {
          const a = (i / 6) * TAU + simTime * 0.00008;
          const r = coreRadius + 58;
          const px = core.x + Math.cos(a) * r;
          const py = core.y + Math.sin(a) * r;
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.stroke();

        if (live.showLabels) {
          ctx.font = "700 10px 'IBM Plex Sans', 'Segoe UI', sans-serif";
          ctx.fillStyle = "rgba(245,252,255,0.94)";
          ctx.fillText(
            "LEVIATHAN · projection anchor",
            core.x + coreRadius + 7,
            core.y + 3,
          );
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
  }, [projection, starfield]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    draggingRef.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      moved: false,
    };
    event.currentTarget.classList.add("is-dragging");
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    mouseRef.current = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };

    const drag = draggingRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;

    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) drag.moved = true;
    draggingRef.current = {
      pointerId: drag.pointerId,
      x: event.clientX,
      y: event.clientY,
      moved: drag.moved,
    };

    setCamera((previous) => ({
      ...previous,
      yaw: previous.yaw + dx * 0.0044,
      pitch: clamp(previous.pitch + dy * 0.0035, -1.04, 1.04),
    }));
  };

  const stopDragging = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (draggingRef.current?.pointerId === event.pointerId) {
      suppressClickRef.current = draggingRef.current.moved;
      draggingRef.current = null;
      event.currentTarget.classList.remove("is-dragging");
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {
        // Pointer capture may already be released by the browser.
      }
    }
  };

  const handleWheel = (event: ReactWheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    setCamera((previous) => ({
      ...previous,
      zoom: clamp(previous.zoom * (event.deltaY > 0 ? 0.92 : 1.08), 0.36, 2.8),
    }));
  };

  const handleClick = () => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    const id = hoverIdRef.current;
    if (id) onSelect(id);
  };

  const handleDoubleClick = () => {
    const id = hoverIdRef.current;
    if (!id) return;
    const node = projection.byId.get(id);
    if (!node) return;
    onIsolatedDomainChange(isolatedDomain === node.domain ? null : node.domain);
  };

  const empty = nodes.length === 0;

  return (
    <div
      ref={hostRef}
      className={`lv-brain-space-canvas${className ? ` ${className}` : ""}${empty ? " is-empty" : ""}`}
    >
      <canvas
        ref={canvasRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={stopDragging}
        onPointerCancel={stopDragging}
        onPointerLeave={(event: ReactPointerEvent<HTMLCanvasElement>) => {
          mouseRef.current = { x: -10_000, y: -10_000 };
          stopDragging(event);
        }}
        onWheel={handleWheel}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        aria-label="LEVIATHAN Brain celestial graph projection"
      />

      {empty ? (
        <div className="lv-brain-space-empty-state" role="status">
          No nodes in current Brain projection / filter
        </div>
      ) : null}

      <div ref={tooltipRef} className="lv-brain-space-tooltip" hidden>
        <strong />
        <span />
      </div>

      <div className="lv-brain-space-truth" aria-hidden="true">
        <span>Domain suns are projection clusters</span>
        <span>Planets are live Brain nodes</span>
        <span>Unknown created_at stays UNMEASURED</span>
      </div>
    </div>
  );
}
