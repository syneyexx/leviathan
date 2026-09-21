"use client";

/**
 * FINALBETA coding live hook — thin re-export of the shared HADES coding runtime.
 */
export {
  useHadesCodingRuntime as useCodingLive,
  type HadesCodingRuntime as CodingLiveState,
  type HadesCodingRuntime,
  type SessionRun,
  type SymbolHit,
  type TerminalResult,
  type OmnirouteStatus,
  type ReleaseReport,
} from "@/components/hades/features/coding/hooks/useHadesCodingRuntime";
