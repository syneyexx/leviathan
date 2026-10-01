/**
 * Chat attachment helpers — ArtifactStore only; never invent local filesystem paths.
 */
import { api } from "../../api/client";

export type ChatAttachmentState =
  | "pending"
  | "uploading"
  | "ready"
  | "failed"
  | "unavailable";

export type ChatAttachment = {
  localId: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  artifactId: string | null;
  state: ChatAttachmentState;
  error: string | null;
  unavailableReason: string | null;
};

const MAX_BYTES = 8 * 1024 * 1024; // align with ArtifactStore MAX_INLINE_ARTIFACT_BYTES

/**
 * Honest feature gate: ArtifactStore HTTP (`POST /api/artifacts`) must be available.
 * Do not claim multimodal understanding from upload alone.
 */
export function canAttachFiles(featureEnabled: boolean | null | undefined): {
  ok: boolean;
  reason: string | null;
} {
  if (featureEnabled === false) {
    return { ok: false, reason: "ArtifactStore attachments are disabled in this runtime" };
  }
  if (featureEnabled == null) {
    return { ok: false, reason: "Attachment capability state UNKNOWN" };
  }
  return { ok: true, reason: null };
}

export function validateLocalFile(file: File): { ok: boolean; reason: string | null } {
  if (!file || file.size <= 0) {
    return { ok: false, reason: "Empty file" };
  }
  if (file.size > MAX_BYTES) {
    return { ok: false, reason: `File exceeds ${MAX_BYTES} byte client limit` };
  }
  // Browser MIME is untrusted — still record it; server re-validates.
  return { ok: true, reason: null };
}

export async function uploadChatAttachment(
  file: File,
  opts?: { conversationId?: string | null; runId?: string | null },
): Promise<ChatAttachment> {
  const localId = `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const base: ChatAttachment = {
    localId,
    fileName: file.name.replace(/[\\/]/g, "_").slice(0, 200),
    mimeType: file.type || "application/octet-stream",
    sizeBytes: file.size,
    artifactId: null,
    state: "uploading",
    error: null,
    unavailableReason: null,
  };
  const local = validateLocalFile(file);
  if (!local.ok) {
    return { ...base, state: "failed", error: local.reason };
  }
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const created = await api.createArtifactFromBytes({
      filename: base.fileName,
      content_type: base.mimeType,
      bytes,
      conversation_id: opts?.conversationId ?? undefined,
      run_id: opts?.runId ?? undefined,
    });
    const artifactId =
      created.artifact?.artifact_id ||
      created.artifact?.id ||
      null;
    if (!artifactId) {
      return { ...base, state: "failed", error: "Artifact create returned no id" };
    }
    return { ...base, artifactId, state: "ready" };
  } catch (err) {
    return {
      ...base,
      state: "failed",
      error: err instanceof Error ? err.message : "Upload failed",
    };
  }
}

export function readyArtifactIds(attachments: ChatAttachment[]): string[] {
  return attachments
    .filter((a) => a.state === "ready" && a.artifactId)
    .map((a) => a.artifactId as string);
}

export function visionClaimAllowed(opts: {
  hasImageAttachment: boolean;
  modelSupportsVision: boolean | null | undefined;
  visionCapabilityActive: boolean;
}): { claim: boolean; reason: string | null } {
  if (!opts.hasImageAttachment) return { claim: false, reason: null };
  if (opts.modelSupportsVision === true || opts.visionCapabilityActive) {
    return { claim: true, reason: null };
  }
  if (opts.modelSupportsVision === false) {
    return {
      claim: false,
      reason: "Selected model has no vision path — attachment stored as artifact only",
    };
  }
  return {
    claim: false,
    reason: "Vision understanding unavailable — capability/model path not confirmed",
  };
}
