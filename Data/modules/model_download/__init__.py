"""Model download execution plane — bulk model acquisition off the Control Plane.

Owned by the ``model_download`` worker pool under the generic WorkerSupervisor.
The Control Plane validates requests and submits durable jobs; workers own
HTTP transfer, resume, verification, progress, and cancellation.

Local model residency/serving remains owned by the Model Control Plane.
Bulk dataset downloads remain owned by the dataset worker.
"""

from .errors import ModelDownloadError, ModelDownloadErrorCode
from .facade import ModelDownloadClient, get_model_download_client

__all__ = [
    "ModelDownloadClient",
    "ModelDownloadError",
    "ModelDownloadErrorCode",
    "get_model_download_client",
]
