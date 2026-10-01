/**
 * Legacy `/offline-datasets` — redirects to canonical `/datasets?mode=learning`.
 * Learning fleet uses listLearningFleet (no N+1 getDataset).
 */

import { Navigate } from "react-router-dom";

export function OfflineDatasetsPixelPage() {
  return <Navigate to="/datasets?mode=learning" replace />;
}
