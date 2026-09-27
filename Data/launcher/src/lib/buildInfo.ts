export interface BuildInfo {
  version: string;
  sha: string;
  time: string;
}

declare const __LEVIATHAN_BUILD__: BuildInfo;

export const buildInfo: BuildInfo = typeof __LEVIATHAN_BUILD__ === "undefined"
  ? { version: "0.1.0", sha: "unknown", time: "" }
  : __LEVIATHAN_BUILD__;
