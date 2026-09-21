/**
 * Coding Agent helpers — re-export shared coding-runtime-core for compatibility.
 */
export {
  dash,
  buildStatusLabel,
  buildStatusTone,
  parseArgv,
  parseEdits,
  collectBuildLogs,
  collectReviewDiffText,
  formatConflictRows,
  loopPhaseLabel,
  parseContextFiles,
  type CodingStatusTone,
} from "@/components/hades/features/coding/coding-runtime-core";
