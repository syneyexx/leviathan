"use client";

import { FileDiff, FilePlus2, FileX2 } from "lucide-react";
import { StatusBadge } from "@/components/hades/ui";

export type FileChange = {
  path: string;
  status: "added" | "modified" | "deleted";
  additions?: number;
  deletions?: number;
};

export function FileChangesCard({ changes }: { changes: FileChange[] }) {
  if (!changes.length) return null;
  return (
    <section className="file-changes-card tool-card" aria-labelledby="file-changes-title">
      <header>
        <FileDiff aria-hidden="true" />
        <strong id="file-changes-title">Bestandswijzigingen</strong>
        <StatusBadge tone="info">{changes.length}</StatusBadge>
      </header>
      <ul>
        {changes.map((change) => {
          const Icon = change.status === "added" ? FilePlus2 : change.status === "deleted" ? FileX2 : FileDiff;
          return (
            <li key={`${change.status}:${change.path}`}>
              <Icon aria-hidden="true" />
              <code>{change.path}</code>
              <small>
                {change.status}
                {change.additions != null ? ` · +${change.additions}` : ""}
                {change.deletions != null ? ` / -${change.deletions}` : ""}
              </small>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
