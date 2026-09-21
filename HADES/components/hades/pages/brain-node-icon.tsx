import { BrainCircuit, Boxes, Check, FileText, MessageSquare, Network, Search, Settings, Sparkles } from "lucide-react";
import type { IconKind } from "./brain-graph-adapter";

export function BrainNodeIcon({ kind }: { kind: IconKind }) {
  const props = { size: 20, strokeWidth: 1.9, "aria-hidden": true as const };
  if (kind === "core" || kind === "memory") return <BrainCircuit {...props} />;
  if (kind === "settings") return <Settings {...props} />;
  if (kind === "chat") return <MessageSquare {...props} />;
  if (kind === "task") return <Check {...props} />;
  if (kind === "doc") return <FileText {...props} />;
  if (kind === "model") return <Sparkles {...props} />;
  if (kind === "db") return <Boxes {...props} />;
  if (kind === "language") return <Search {...props} />;
  return <Network {...props} />;
}
