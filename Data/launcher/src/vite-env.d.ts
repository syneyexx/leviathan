/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LEVIATHAN_VISUAL_FIXTURE?: string;
  readonly VITE_LEVIATHAN_TRACE?: string;
}

interface BuildStamp {
  version: string;
  sha: string;
  time: string;
}

declare const __LEVIATHAN_BUILD__: BuildStamp;
