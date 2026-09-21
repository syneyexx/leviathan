import { API_BASE, HadesApiError } from "@/lib/hades-api";

export type DatasetBrainStatus = {
  dataset_id: string;
  dataset_name?: string;
  source_type?: string;
  status: string;
  phase?: string;
  progress?: number;
  materialized_rows: number;
  materialized_complete: boolean;
  indexed_rows: number;
  chunks_indexed: number;
  source_id: string | null;
  snapshot_path: string;
  snapshot_exists?: boolean;
  snapshot_size_bytes?: number;
  active_job_id?: string | null;
  latest_job_id?: string | null;
  error?: string | null;
};

export type DatasetBrainJob = {
  id: string;
  dataset_id: string;
  dataset_name?: string | null;
  source_type?: string;
  status: string;
  phase: string;
  progress: number;
  materialized_rows: number;
  indexed_rows: number;
  chunks_indexed: number;
  snapshot_path: string;
  log_path: string;
  source_id?: string | null;
  error?: string | null;
  pid?: number | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

type IndexInput = {
  hf_token?: string;
  approved_network: boolean;
  approved_file_read: boolean;
  approved_subprocess: boolean;
  rebuild_index?: boolean;
  rematerialize?: boolean;
};

async function brainRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new HadesApiError("De lokale FastAPI-backend is niet bereikbaar. Start eerst START_HADES.bat.");
  }
  if (!response.ok) {
    let message = `API-fout ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
        message = String((body.detail as { message: unknown }).message);
      }
    } catch {
      // Keep HTTP fallback.
    }
    throw new HadesApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const hadesDatasetBrainApi = {
  statuses: () => brainRequest<DatasetBrainStatus[]>("/training/brain/status"),
  status: (datasetId: string) =>
    brainRequest<DatasetBrainStatus>(`/training/brain/datasets/${encodeURIComponent(datasetId)}`),
  jobs: () => brainRequest<DatasetBrainJob[]>("/training/brain/jobs"),
  job: (jobId: string) => brainRequest<DatasetBrainJob>(`/training/brain/jobs/${encodeURIComponent(jobId)}`),
  jobLog: (jobId: string) =>
    brainRequest<{ content: string }>(`/training/brain/jobs/${encodeURIComponent(jobId)}/log`),
  index: (datasetId: string, values: IndexInput) =>
    brainRequest<DatasetBrainJob>(`/training/brain/datasets/${encodeURIComponent(datasetId)}/index`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  cancel: (jobId: string) =>
    brainRequest<DatasetBrainJob>(`/training/brain/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  remove: (datasetId: string) =>
    brainRequest<{ dataset_id: string; removed: boolean; knowledge_source_removed: boolean }>(
      `/training/brain/datasets/${encodeURIComponent(datasetId)}`,
      { method: "DELETE" },
    ),
};