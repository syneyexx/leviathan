"""Hugging Face metadata listing — NOT bulk dataset download."""

from __future__ import annotations

from typing import Any, Callable

from Data.modules.provider_io.clients import ProviderClientPool
from Data.modules.provider_io.credentials import ResolvedCredential
from Data.modules.provider_io.errors import ProviderError, ProviderErrorCode
from Data.modules.provider_io.policy import DeadlineBudget, ProviderPolicyRegistry
from Data.modules.provider_io.stream_store import ProviderStreamStore
from Data.modules.provider_io.types import ProviderExecutionResult, ProviderRequest


CancelCheck = Callable[[], bool]


class HuggingFaceMetaAdapter:
    """Bounded HF Hub tree listing for Control Plane offload.

    Bulk repository downloads stay in the dataset worker.
    """

    name = "huggingface_meta"

    def execute(
        self,
        request: ProviderRequest,
        *,
        clients: ProviderClientPool,
        credential: ResolvedCredential,
        policy: ProviderPolicyRegistry,
        budget: DeadlineBudget,
        stream_store: ProviderStreamStore | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> ProviderExecutionResult:
        del clients, policy, stream_store
        payload = dict(request.payload or {})
        repository_id = str(payload.get("repository_id") or "").strip()
        revision = str(payload.get("revision") or "main").strip() or "main"
        if not repository_id:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INVALID_REQUEST,
                "hf.list requires repository_id",
                provider="huggingface",
            )
        budget.raise_if_exhausted()
        if cancel_check and cancel_check():
            raise ProviderError(
                ProviderErrorCode.EXECUTION_CANCELLED,
                "Cancelled before HF list",
                provider="huggingface",
            )

        token = credential.api_key
        from Data.modules.datasets.huggingface import list_hf_dataset_files

        files = list_hf_dataset_files(repository_id, revision=revision, token=token)
        # Never echo tokens; files metadata only.
        safe_files: list[dict[str, Any]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            safe_files.append({k: v for k, v in item.items() if "token" not in k.lower()})

        return ProviderExecutionResult(
            status="succeeded",
            structured={"files": safe_files, "repository_id": repository_id, "revision": revision},
            provider="huggingface",
            finish_reason="stop",
            metadata={"file_count": len(safe_files)},
        )
