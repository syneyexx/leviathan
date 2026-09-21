export const RESEARCH_ROBOTS_OFF_SOURCE = "hades-internal://research-policy/respect-robots-txt=off";
export const RESEARCH_ROBOTS_OFF_FRAGMENT = "hades-respect-robots-txt=off";

export function applyResearchRobotsPolicy(sources: string[], respectRobotsTxt: boolean): string[] {
  const cleanSources = sources.filter((source) => source !== RESEARCH_ROBOTS_OFF_SOURCE);
  return respectRobotsTxt ? cleanSources : [...cleanSources, RESEARCH_ROBOTS_OFF_SOURCE];
}

export function applyHarvestRobotsPolicy(url: string, respectRobotsTxt: boolean): string {
  const hashIndex = url.indexOf("#");
  const baseUrl = hashIndex >= 0 ? url.slice(0, hashIndex) : url;
  const rawFragment = hashIndex >= 0 ? url.slice(hashIndex + 1) : "";
  const fragmentParts = rawFragment
    .split("&")
    .filter(Boolean)
    .filter((part) => part !== RESEARCH_ROBOTS_OFF_FRAGMENT);

  if (!respectRobotsTxt) fragmentParts.push(RESEARCH_ROBOTS_OFF_FRAGMENT);
  return fragmentParts.length ? `${baseUrl}#${fragmentParts.join("&")}` : baseUrl;
}
