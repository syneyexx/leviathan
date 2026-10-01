/**
 * Legacy `/dataset-management` — redirects to canonical `/datasets?mode=manage`.
 * Implementation lives in DatasetsPage / useDatasetsWorkspace.
 */

import { Navigate } from "react-router-dom";

export function DatasetManagementPage() {
  return <Navigate to="/datasets?mode=manage" replace />;
}
