import type { NativeModel } from "../types/backend";

export function mapNative(payload: Record<string, unknown> | null): NativeModel {
  const probe = (payload?.probe || payload || {}) as Record<string, unknown>;
  const status = String(probe.status || "UNMEASURED");
  const recentRaw = Array.isArray(payload?.recentOperations) ? payload.recentOperations : [];
  return {
    status,
    version: probe.protocolVersion == null ? "UNMEASURED" : `protocol ${probe.protocolVersion}`,
    binaryPath: typeof probe.binaryPath === "string" ? probe.binaryPath : null,
    operations: Array.isArray(probe.operations) ? probe.operations.map((item) => String(item)) : [],
    detail: String(probe.detail || ""),
    recent: recentRaw.slice(0, 40).map((item) => {
      const row = item as Record<string, unknown>;
      return {
        at: String(row.at || ""),
        message: String(row.message || row.operation || ""),
        operation: String(row.operation || "—"),
      };
    }),
    daemon: false,
  };
}

export function nativeIsHealthy(model: NativeModel): boolean {
  return model.status === "AVAILABLE";
}
