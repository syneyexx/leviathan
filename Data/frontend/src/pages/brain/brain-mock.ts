/** Brain view constants — live data comes from /api/brain/graph. */

export const BRAIN_VIEWS = ["Graph", "Tree", "Timeline", "Clusters", "Analytics"] as const;
export type BrainView = (typeof BRAIN_VIEWS)[number];

/** Placeholder stats only used when BrainHeader is rendered without live stats. */
export const BRAIN_STATS = [
  { label: "Nodes", value: "—", icon: "nodes" },
  { label: "Connections", value: "—", icon: "links" },
  { label: "Knowledge Domains", value: "—", icon: "domains" },
  { label: "Last Updated", value: "—", icon: "clock" },
] as const;
