/**
 * Dataset detail projection: versions, preview, recovery, learning, tags.
 * Independent of inventory page — fetches by activeId.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  DatasetPreviewRow,
  DatasetRecord,
  DatasetRecoveryAssessment,
  DatasetVersion,
} from "../../types/api";
import { initTagsFromDataset, normalizeTagList } from "./tagEdit";
import { pickUsableVersion } from "./viewModels";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export type DetailTab =
  | "overview"
  | "quality"
  | "preview"
  | "versions"
  | "processing"
  | "semantics"
  | "learning"
  | "provenance"
  | "activity"
  | "advanced"
  // Legacy aliases kept for transitional UI
  | "analyse"
  | "metadata";

export type PreviewSampleTab = "JSON" | "Tekst" | "Tabel";

export function useDatasetDetail(opts: {
  activeId: string | null;
  onSelectedRecord?: (ds: DatasetRecord | null) => void;
}) {
  const { activeId, onSelectedRecord } = opts;
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [detailVersions, setDetailVersions] = useState<DatasetVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [detailPreview, setDetailPreview] = useState<DatasetPreviewRow[]>([]);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [recovery, setRecovery] = useState<DatasetRecoveryAssessment | null>(null);
  const [detailRecord, setDetailRecord] = useState<DatasetRecord | null>(null);
  const [sampleTab, setSampleTab] = useState<PreviewSampleTab>("JSON");
  const [tagChips, setTagChips] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [semanticEditing, setSemanticEditing] = useState(false);
  const [detailEpoch, setDetailEpoch] = useState(0);

  const detailGenRef = useRef(0);
  const previewGenRef = useRef(0);
  const onSelectedRecordRef = useRef(onSelectedRecord);
  onSelectedRecordRef.current = onSelectedRecord;

  const bumpDetail = useCallback(() => setDetailEpoch((n) => n + 1), []);

  useEffect(() => {
    if (!activeId) {
      setDetailVersions([]);
      setSelectedVersionId(null);
      setDetailPreview([]);
      setDetailError(null);
      setPreviewError(null);
      setRecovery(null);
      setDetailRecord(null);
      setTagChips([]);
      setTagInput("");
      setSemanticEditing(false);
      onSelectedRecordRef.current?.(null);
      return;
    }
    const gen = ++detailGenRef.current;
    setDetailLoading(true);
    setDetailError(null);
    setDetailTab((prev) => prev); // keep tab across refresh; reset only on id change below
    void (async () => {
      try {
        const [detail, recoveryRes] = await Promise.all([
          api.getDataset(activeId),
          api.getDatasetRecovery(activeId).catch(() => null),
        ]);
        if (gen !== detailGenRef.current) return;
        setDetailRecord(detail.dataset);
        setDetailVersions(detail.versions);
        setSelectedVersionId((prev) => {
          if (prev && detail.versions.some((v) => v.versionId === prev)) return prev;
          return pickUsableVersion(detail.versions)?.versionId ?? null;
        });
        setRecovery(recoveryRes?.recovery ?? null);
        setTagChips(initTagsFromDataset(detail.dataset));
        setTagInput("");
        setEditDisplayName(
          String(
            detail.dataset.displayName ||
              detail.dataset.semanticProfile?.displayName ||
              detail.dataset.name ||
              "",
          ),
        );
        setEditCategory(
          String(
            detail.dataset.primaryCategory ??
              detail.dataset.semanticProfile?.primaryCategory ??
              "",
          ),
        );
        setSemanticEditing(false);
        onSelectedRecordRef.current?.(detail.dataset);
      } catch (err) {
        if (gen !== detailGenRef.current) return;
        setDetailVersions([]);
        setSelectedVersionId(null);
        setDetailPreview([]);
        setRecovery(null);
        setDetailRecord(null);
        setDetailError(errMsg(err, "Dataset detail niet beschikbaar"));
        onSelectedRecordRef.current?.(null);
      } finally {
        if (gen === detailGenRef.current) setDetailLoading(false);
      }
    })();
  }, [activeId, detailEpoch]);

  // Reset tab when selection identity changes.
  const prevActiveRef = useRef<string | null>(null);
  useEffect(() => {
    if (activeId !== prevActiveRef.current) {
      prevActiveRef.current = activeId;
      setDetailTab("overview");
    }
  }, [activeId]);

  useEffect(() => {
    if (!selectedVersionId) {
      setDetailPreview([]);
      setPreviewError(null);
      return;
    }
    const gen = ++previewGenRef.current;
    setPreviewError(null);
    void (async () => {
      try {
        const prev = await api.previewDatasetVersion(selectedVersionId, 20);
        if (gen !== previewGenRef.current) return;
        setDetailPreview(prev.rows ?? []);
      } catch (err) {
        if (gen !== previewGenRef.current) return;
        setDetailPreview([]);
        setPreviewError(errMsg(err, "Voorbeeld niet beschikbaar"));
      }
    })();
  }, [selectedVersionId]);

  const selectedVersion =
    detailVersions.find((v) => v.versionId === selectedVersionId) ??
    pickUsableVersion(detailVersions);

  return {
    detailTab,
    setDetailTab,
    detailVersions,
    selectedVersionId,
    setSelectedVersionId,
    selectedVersion,
    detailPreview,
    detailError,
    previewError,
    detailLoading,
    recovery,
    detailRecord,
    sampleTab,
    setSampleTab,
    tagChips,
    setTagChips,
    tagInput,
    setTagInput,
    editDisplayName,
    setEditDisplayName,
    editCategory,
    setEditCategory,
    semanticEditing,
    setSemanticEditing,
    bumpDetail,
    normalizeTagList,
  };
}

export type DatasetDetail = ReturnType<typeof useDatasetDetail>;
