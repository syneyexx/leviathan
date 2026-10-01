/**
 * Isolated form state factories for Datasets create / upload / local / HF modals.
 * HF token must never enter localStorage, metadata, toast, or query strings.
 */

export type CreateDatasetForm = {
  name: string;
  description: string;
  license: string;
};

export type UploadDatasetForm = {
  file: File | null;
  name: string;
  description: string;
};

export type LocalImportForm = {
  path: string;
  name: string;
  description: string;
};

export type HfImportForm = {
  repositoryId: string;
  revision: string;
  filename: string;
  name: string;
  description: string;
  /** Ephemeral only — never persist. */
  token: string;
};

export function emptyCreateForm(): CreateDatasetForm {
  return { name: "", description: "", license: "" };
}

export function emptyUploadForm(): UploadDatasetForm {
  return { file: null, name: "", description: "" };
}

export function emptyLocalImportForm(): LocalImportForm {
  return { path: "", name: "", description: "" };
}

export function emptyHfImportForm(): HfImportForm {
  return {
    repositoryId: "",
    revision: "main",
    filename: "",
    name: "",
    description: "",
    token: "",
  };
}

/** Strip token before any logging / telemetry / error enrichment. */
export function redactHfFormForLog(form: HfImportForm): Omit<HfImportForm, "token"> & { tokenPresent: boolean } {
  const { token, ...rest } = form;
  return { ...rest, tokenPresent: Boolean(token.trim()) };
}
