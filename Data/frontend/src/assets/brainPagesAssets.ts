/** Pixel-exact Brain view content crops (chrome excluded). */

import contentAnalytics from "./brain-pages/crops/content-analytics.jpg";
import contentClusters from "./brain-pages/crops/content-clusters.jpg";
import contentTimeline from "./brain-pages/crops/content-timeline.jpg";
import contentTree from "./brain-pages/crops/content-tree.jpg";

export const BRAIN_PIXEL_VIEWS = ["Tree", "Timeline", "Clusters", "Analytics"] as const;

export type BrainPixelView = (typeof BRAIN_PIXEL_VIEWS)[number];

export const brainViewContent: Record<BrainPixelView, string> = {
  Tree: contentTree,
  Timeline: contentTimeline,
  Clusters: contentClusters,
  Analytics: contentAnalytics,
};

/** Hit targets as % of the 1450×863 content crop. */
export type BrainHotspot = {
  view: "Graph" | BrainPixelView;
  left: number;
  top: number;
  width: number;
  height: number;
};

/** Timeline + Clusters mocks include a Graph View tab. */
const WITH_GRAPH: BrainHotspot[] = [
  { view: "Graph", left: 0.28, top: 13.3, width: 8.0, height: 4.2 },
  { view: "Tree", left: 8.83, top: 13.3, width: 5.52, height: 4.2 },
  { view: "Timeline", left: 15.17, top: 13.3, width: 7.93, height: 4.2 },
  { view: "Clusters", left: 23.93, top: 13.3, width: 7.45, height: 4.2 },
  { view: "Analytics", left: 32.21, top: 13.3, width: 8.14, height: 4.2 },
];

/** Tree + Analytics mocks start at Tree (no Graph View tab in the crop). */
const WITHOUT_GRAPH: BrainHotspot[] = [
  { view: "Tree", left: 0.28, top: 13.3, width: 6.62, height: 4.2 },
  { view: "Timeline", left: 7.72, top: 13.3, width: 8.0, height: 4.2 },
  { view: "Clusters", left: 16.55, top: 13.3, width: 7.72, height: 4.2 },
  { view: "Analytics", left: 25.1, top: 13.3, width: 8.0, height: 4.2 },
];

export const brainViewHotspots: Record<BrainPixelView, BrainHotspot[]> = {
  Tree: WITHOUT_GRAPH,
  Timeline: WITH_GRAPH,
  Clusters: WITH_GRAPH,
  Analytics: WITHOUT_GRAPH,
};

export const brainViewHasGraphTab: Record<BrainPixelView, boolean> = {
  Tree: false,
  Timeline: true,
  Clusters: true,
  Analytics: false,
};
