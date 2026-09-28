export type Point2 = { x: number; y: number };
export type RectLike = { left: number; top: number; width: number; height: number };
export type ViewBox2 = { x: number; y: number; width: number; height: number };
export type ViewTransform = { x: number; y: number; scale: number };

export function clampNumber(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

/**
 * Map a client-space point into an SVG viewBox using preserveAspectRatio="xMidYMid meet".
 * This deliberately accounts for letterboxing; raw rect ratios do not.
 */
export function clientPointToMeetViewBox(
  clientX: number,
  clientY: number,
  rect: RectLike,
  viewBox: ViewBox2,
): Point2 | null {
  if (rect.width <= 0 || rect.height <= 0 || viewBox.width <= 0 || viewBox.height <= 0) {
    return null;
  }
  const factor = Math.min(rect.width / viewBox.width, rect.height / viewBox.height);
  if (!Number.isFinite(factor) || factor <= 0) return null;
  const usedWidth = viewBox.width * factor;
  const usedHeight = viewBox.height * factor;
  const padX = (rect.width - usedWidth) / 2;
  const padY = (rect.height - usedHeight) / 2;
  return {
    x: viewBox.x + (clientX - rect.left - padX) / factor,
    y: viewBox.y + (clientY - rect.top - padY) / factor,
  };
}

/** Fit finite graph points inside a fixed SVG viewport using an inner transform. */
export function fitPointsTransform(
  points: Array<Point2 & { radius?: number }>,
  viewportWidth: number,
  viewportHeight: number,
  options: { padding?: number; minScale?: number; maxScale?: number } = {},
): ViewTransform {
  const padding = Math.max(0, options.padding ?? 56);
  const minScale = options.minScale ?? 0.3;
  const maxScale = options.maxScale ?? 1.15;
  const finite = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!finite.length || viewportWidth <= 0 || viewportHeight <= 0) {
    return { x: 0, y: 0, scale: 1 };
  }

  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const point of finite) {
    const radius = Math.max(0, Number.isFinite(point.radius) ? Number(point.radius) : 0);
    minX = Math.min(minX, point.x - radius);
    maxX = Math.max(maxX, point.x + radius);
    minY = Math.min(minY, point.y - radius);
    maxY = Math.max(maxY, point.y + radius);
  }

  const contentWidth = Math.max(1, maxX - minX);
  const contentHeight = Math.max(1, maxY - minY);
  const usableWidth = Math.max(1, viewportWidth - padding * 2);
  const usableHeight = Math.max(1, viewportHeight - padding * 2);
  const scale = clampNumber(
    Math.min(usableWidth / contentWidth, usableHeight / contentHeight),
    minScale,
    maxScale,
  );
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  return {
    x: viewportWidth / 2 - centerX * scale,
    y: viewportHeight / 2 - centerY * scale,
    scale,
  };
}

export function centeredViewBox(
  baseWidth: number,
  baseHeight: number,
  scale: number,
  offset: Point2 = { x: 0, y: 0 },
): ViewBox2 {
  const safeScale = Math.max(0.001, scale);
  const width = baseWidth / safeScale;
  const height = baseHeight / safeScale;
  return {
    x: (baseWidth - width) / 2 + offset.x,
    y: (baseHeight - height) / 2 + offset.y,
    width,
    height,
  };
}

/**
 * Keep the same world coordinate under the same pointer ratio while changing
 * a centered viewBox scale. Returns the offset representation used by Clusters.
 */
export function zoomCenteredViewBoxAt(
  baseWidth: number,
  baseHeight: number,
  oldScale: number,
  newScale: number,
  oldOffset: Point2,
  worldPoint: Point2,
): Point2 {
  const oldBox = centeredViewBox(baseWidth, baseHeight, oldScale, oldOffset);
  const nextBox = centeredViewBox(baseWidth, baseHeight, newScale, { x: 0, y: 0 });
  const ratioX = clampNumber((worldPoint.x - oldBox.x) / oldBox.width, 0, 1);
  const ratioY = clampNumber((worldPoint.y - oldBox.y) / oldBox.height, 0, 1);
  const wantedX = worldPoint.x - ratioX * nextBox.width;
  const wantedY = worldPoint.y - ratioY * nextBox.height;
  return {
    x: wantedX - nextBox.x,
    y: wantedY - nextBox.y,
  };
}
