"""LM Studio provider adapter — discovery, inference, and native lifecycle control.

LM Studio remains externally owned (managed_by_leviathan=False). Leviathan may
load/unload models via the official native REST API and optionally the lms CLI
for GPU ratio / resource estimation. Leviathan must not kill LM Studio.exe.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from Data.modules.models.contracts import (
    CapabilityState,
    LoadOptions,
    ModelCapabilities,
    ModelDescriptor,
    ModelHealthState,
    ModelLifecycleState,
    ModelSource,
    ProviderHealth,
    RuntimeCapabilities,
)
from Data.modules.models.errors import (
    CAPABILITY_NOT_SUPPORTED,
    MODEL_NOT_FOUND,
    PROVIDER_AUTH_FAILED,
    PROVIDER_OFFLINE,
    REQUEST_TIMEOUT,
    ModelControlError,
)
from Data.modules.models.lm_studio_control import (
    LMStudioControlCapabilities,
    LMStudioLoadReceipt,
    capabilities_from_probe,
    classify_lm_studio_error,
    compile_lm_studio_load,
    discover_lms_executable,
    native_api_base,
    normalize_lm_studio_host,
    openai_api_base,
    parse_lms_estimate_output,
    run_lms_cli,
)
from Data.modules.models.providers.openai_compatible import OpenAICompatibleAdapter
from Data.modules.models.store import utc_now

# Load options advertised when native REST is available.
_REST_LOAD_OPTIONS = (
    "contextLength",
    "batchSize",
    "flashAttention",
    "offloadKvCacheToGpu",
    "numExperts",
    "gpuOffloadRatio",
    "gpuSplitMode",
    "tensorSplit",
    "mainGpuOrdinal",
    "excludedDeviceIds",
    "gpuStrictVramCap",
    "kvCacheDtype",
    "continuousBatching",
    "prefixCache",
    "speculativeDecoding",
    "draftModelId",
    "speculativeTokens",
    "allowMultiGpu",
    "shardingMode",
    "seed",
    "cpuThreads",
    "keepDisplayHeadroom",
)


class LMStudioAdapter(OpenAICompatibleAdapter):
    provider_type = "lm_studio"
    # Operator/external process ownership — LEVIATHAN must not kill/restart.
    managed_by_leviathan: bool = False
    # Lifecycle via API is allowed even though process is external.
    lifecycle_controllable: bool = True

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        load_timeout_seconds: float = 600.0,
    ) -> None:
        host = normalize_lm_studio_host(endpoint)
        super().__init__(
            provider_id=provider_id,
            endpoint=openai_api_base(host),
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            source=ModelSource.REMOTE,
            capabilities=RuntimeCapabilities(
                discover_models=True,
                import_model=False,
                download_model=False,
                load_model=True,
                unload_model=True,
                delete_model=False,
                list_loaded_models=True,
                inference=True,
                streaming=True,
                embeddings=False,
                tool_calling=False,
                structured_output=False,
                vision=False,
                runtime_metrics=False,
                load_options=_REST_LOAD_OPTIONS,
            ),
        )
        self.host = host
        self.native_base = native_api_base(host)
        self.load_timeout_seconds = float(load_timeout_seconds)
        self._control_caps: LMStudioControlCapabilities | None = None
        self._provider_version: str | None = None
        self._last_load_receipt: LMStudioLoadReceipt | None = None

    def control_capabilities(self) -> LMStudioControlCapabilities:
        if self._control_caps is None:
            self._control_caps = capabilities_from_probe(
                native_rest_ok=False,
                version=None,
                cli_available=discover_lms_executable() is not None,
                rest_base=self.native_base,
            )
        return self._control_caps

    def last_load_receipt(self) -> LMStudioLoadReceipt | None:
        return self._last_load_receipt

    def _native_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def probe_control_capabilities(self) -> LMStudioControlCapabilities:
        """Probe connected LM Studio for native REST + CLI surfaces."""
        cli_ok = discover_lms_executable() is not None
        version: str | None = None
        native_ok = False
        notes_extra: list[str] = []
        try:
            async with httpx.AsyncClient(
                timeout=min(self.timeout_seconds, 10.0),
                headers=self._native_headers(),
            ) as client:
                # Prefer native models list
                resp = await client.get(f"{self.native_base}/models")
                if resp.status_code == 401:
                    raise ModelControlError(
                        code=PROVIDER_AUTH_FAILED,
                        message="LM Studio authentication failed",
                        provider_id=self.provider_id,
                        http_status=401,
                    )
                if resp.status_code < 400:
                    native_ok = True
                    data = resp.json() if resp.content else {}
                    version = _extract_version(data, resp.headers)
                else:
                    # Fallback: OpenAI /v1/models proves server up but not native control
                    oai = await client.get(f"{self.endpoint}/models")
                    if oai.status_code < 400:
                        notes_extra.append(
                            f"OpenAI-compatible /v1 reachable; native REST returned HTTP {resp.status_code}"
                        )
                    else:
                        notes_extra.append(f"Native REST HTTP {resp.status_code}")
        except httpx.TimeoutException as exc:
            raise ModelControlError(
                code=REQUEST_TIMEOUT,
                message="LM Studio capability probe timed out",
                provider_id=self.provider_id,
                http_status=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"LM Studio unreachable: {exc}",
                provider_id=self.provider_id,
                http_status=503,
            ) from exc

        from dataclasses import replace

        caps = capabilities_from_probe(
            native_rest_ok=native_ok,
            version=version,
            cli_available=cli_ok,
            rest_base=self.native_base,
            load_probe_ok=True if native_ok else False,
        )
        if notes_extra:
            caps = replace(caps, notes=tuple([*caps.notes, *notes_extra]))

        self._control_caps = caps
        self._provider_version = version
        # Refresh RuntimeCapabilities flags from probe
        self._capabilities = RuntimeCapabilities(
            discover_models=True,
            import_model=False,
            download_model=False,
            load_model=caps.load.value == "SUPPORTED",
            unload_model=caps.unload.value == "SUPPORTED",
            delete_model=False,
            list_loaded_models=caps.loaded_instances.value == "SUPPORTED",
            inference=True,
            streaming=True,
            embeddings=False,
            tool_calling=False,
            structured_output=False,
            vision=False,
            runtime_metrics=False,
            load_options=_REST_LOAD_OPTIONS if native_ok else (),
        )
        return caps

    async def health(self) -> tuple[ProviderHealth, float | None, str | None]:
        """Return (health, latency_ms, error_message) per `ModelProviderAdapter`.

        Also probes LM Studio control-plane capabilities (native REST vs. CLI
        fallback) as a side effect so `control_capabilities()` / `provider_version`
        stay fresh; that richer detail isn't part of the base contract's tuple.
        """
        started = time.perf_counter()
        try:
            caps = await self.probe_control_capabilities()
            latency = (time.perf_counter() - started) * 1000.0
            # Also verify openai surface for inference readiness
            async with httpx.AsyncClient(
                timeout=min(self.timeout_seconds, 10.0),
                headers=self._headers(),
            ) as client:
                oai = await client.get(f"{self.endpoint}/models")
                oai_ok = oai.status_code < 400
            if caps.native_rest.value == "SUPPORTED" or oai_ok:
                return ProviderHealth.HEALTHY, latency, None
            return ProviderHealth.DEGRADED, latency, "LM Studio native and OpenAI-compatible surfaces both unavailable"
        except ModelControlError as exc:
            latency = (time.perf_counter() - started) * 1000.0
            return ProviderHealth.OFFLINE, latency, str(exc)
        except httpx.TimeoutException as exc:
            return ProviderHealth.TIMEOUT, None, str(exc)
        except httpx.HTTPError as exc:
            return ProviderHealth.OFFLINE, None, str(exc)

    async def list_loaded(self) -> list[dict[str, Any]]:
        caps = self.control_capabilities()
        if caps.loaded_instances.value != "SUPPORTED" and caps.native_rest.value != "SUPPORTED":
            # Attempt anyway if we haven't probed
            await self.probe_control_capabilities()
            caps = self.control_capabilities()
        if caps.native_rest.value != "SUPPORTED":
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="LM Studio native loaded-instance listing unavailable",
                provider_id=self.provider_id,
                http_status=409,
            )
        data = await self._native_get("/models")
        models = _extract_model_list(data)
        loaded: list[dict[str, Any]] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            # Native API marks loaded instances with instance_id / loaded flags
            instance_id = item.get("instance_id") or item.get("instanceId")
            loaded_flag = item.get("loaded")
            state = str(item.get("state") or item.get("status") or "").lower()
            if instance_id or loaded_flag is True or state in {"loaded", "active"}:
                loaded.append(item)
            # Some builds nest instances under "instances"
            for inst in item.get("instances") or []:
                if isinstance(inst, dict):
                    loaded.append(inst)
        return loaded

    async def load(self, model_id: str, options: LoadOptions | None = None) -> dict[str, Any]:
        caps = self.control_capabilities()
        if caps.native_rest.value != "SUPPORTED":
            try:
                await self.probe_control_capabilities()
                caps = self.control_capabilities()
            except ModelControlError:
                pass
        if caps.load.value != "SUPPORTED" and caps.native_rest.value != "SUPPORTED":
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="LM Studio native load API not available on this instance",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )

        model_key = _resolve_model_key(model_id)
        compiled = compile_lm_studio_load(model_key, options, caps, echo_load_config=True)
        started = time.perf_counter()
        timestamp = utc_now()

        # Prefer REST for documented fields; use CLI when GPU ratio must apply.
        if compiled.transport == "cli" and caps.cli_available:
            result = await self._load_via_cli(model_key, compiled)
        else:
            result = await self._load_via_rest(compiled)

        load_time = result.get("load_time_seconds")
        if load_time is None:
            load_time = time.perf_counter() - started
        instance_id = (
            result.get("instance_id")
            or result.get("instanceId")
            or result.get("model_instance_id")
        )
        applied = result.get("load_config") or result.get("loadConfig")
        if isinstance(applied, dict):
            applied_norm = applied
        else:
            applied_norm = None

        # Reconcile loaded instances
        reconciled = False
        reconcile_warnings: list[str] = []
        try:
            loaded = await self.list_loaded()
            reconciled = _instance_matches(loaded, model_key, instance_id)
            if not reconciled:
                reconcile_warnings.append(
                    "Load HTTP succeeded but instance reconciliation did not find expected instance"
                )
        except ModelControlError as exc:
            reconcile_warnings.append(f"Reconciliation failed: {exc.message}")

        if not reconciled and result.get("status") == "loaded":
            # Do not claim LOADED without reconciliation when list is available
            if caps.loaded_instances.value == "SUPPORTED":
                raise ModelControlError(
                    code="LOAD_FAILED",
                    message="LM Studio load response could not be reconciled with loaded instances",
                    provider_id=self.provider_id,
                    model_id=model_id,
                    http_status=502,
                    details={"result": result, "warnings": reconcile_warnings},
                )

        receipt = LMStudioLoadReceipt(
            requested_model=model_id,
            resolved_model_key=model_key,
            instance_id=str(instance_id) if instance_id else None,
            requested_config=compiled.requested,
            applied_config=applied_norm,
            load_time_seconds=float(load_time) if load_time is not None else None,
            timestamp=timestamp,
            provider_version=caps.provider_version,
            warnings=[*compiled.warnings, *reconcile_warnings, *list(compiled.deferred_unsupported.values())],
            reconciled=reconciled,
            status="loaded" if reconciled or result.get("status") == "loaded" else "unknown",
        )
        self._last_load_receipt = receipt
        return {
            "status": receipt.status,
            "provider": "lm_studio",
            "modelId": model_id,
            "instanceId": receipt.instance_id,
            "loadTimeSeconds": receipt.load_time_seconds,
            "requestedConfig": receipt.requested_config,
            "appliedConfig": receipt.applied_config,
            "compiled": compiled.public_dict(),
            "receipt": receipt.public_dict(),
            "reconciled": reconciled,
            "deferredUnsupported": compiled.deferred_unsupported,
            "managed_by_leviathan": False,
            "lifecycle_controllable": True,
        }

    async def unload(self, model_id: str) -> dict[str, Any]:
        caps = self.control_capabilities()
        if caps.native_rest.value != "SUPPORTED":
            try:
                await self.probe_control_capabilities()
                caps = self.control_capabilities()
            except ModelControlError:
                pass
        if caps.unload.value != "SUPPORTED" and caps.native_rest.value != "SUPPORTED":
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="LM Studio native unload API not available",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
            )

        # Prefer instance id from last receipt / loaded list
        instance_id = None
        if self._last_load_receipt and (
            self._last_load_receipt.requested_model == model_id
            or self._last_load_receipt.resolved_model_key in model_id
        ):
            instance_id = self._last_load_receipt.instance_id
        if not instance_id:
            try:
                loaded = await self.list_loaded()
                key = _resolve_model_key(model_id)
                for item in loaded:
                    mid = str(item.get("model") or item.get("id") or item.get("modelKey") or "")
                    iid = item.get("instance_id") or item.get("instanceId")
                    if key in mid or mid in key or mid.endswith(key):
                        instance_id = str(iid) if iid else mid
                        break
            except ModelControlError:
                instance_id = _resolve_model_key(model_id)

        body = {"instance_id": instance_id} if instance_id else {"model": _resolve_model_key(model_id)}
        try:
            result = await self._native_post(
                "/models/unload",
                body,
                timeout=min(self.load_timeout_seconds, 120.0),
            )
        except ModelControlError:
            # Fallback: some builds accept identifier as model key
            result = await self._native_post(
                "/models/unload",
                {"identifier": instance_id or _resolve_model_key(model_id)},
                timeout=min(self.load_timeout_seconds, 120.0),
            )

        # Reconcile
        still_loaded = False
        try:
            loaded = await self.list_loaded()
            still_loaded = _instance_matches(loaded, _resolve_model_key(model_id), instance_id)
        except ModelControlError:
            still_loaded = False

        if still_loaded:
            raise ModelControlError(
                code="UNLOAD_FAILED",
                message="Unload requested but instance still present after reconciliation",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=502,
                details={"instanceId": instance_id, "result": result},
            )

        if self._last_load_receipt and self._last_load_receipt.instance_id == instance_id:
            self._last_load_receipt = None

        return {
            "status": "unloaded",
            "provider": "lm_studio",
            "modelId": model_id,
            "instanceId": instance_id,
            "reconciled": not still_loaded,
            "result": result,
            "managed_by_leviathan": False,
            "lifecycle_controllable": True,
        }

    async def estimate_load(
        self,
        model_id: str,
        options: LoadOptions | None = None,
    ) -> dict[str, Any]:
        caps = self.control_capabilities()
        if caps.resource_estimate.value != "SUPPORTED":
            raise ModelControlError(
                code=CAPABILITY_NOT_SUPPORTED,
                message="LM Studio resource estimate requires lms CLI (--estimate-only)",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=409,
                details={"capabilities": caps.public_dict()},
            )
        model_key = _resolve_model_key(model_id)
        argv = ["load", "--estimate-only", model_key]
        if options and options.context_length is not None:
            argv.extend(["--context-length", str(int(options.context_length))])
        if options and options.gpu_offload_ratio is not None:
            ratio = float(options.gpu_offload_ratio)
            if ratio <= 0:
                argv.extend(["--gpu", "off"])
            elif ratio >= 1:
                argv.extend(["--gpu", "max"])
            else:
                argv.extend(["--gpu", f"{ratio:.4g}"])
        host = urlparse(self.host).netloc or None
        completed = run_lms_cli(argv, timeout_seconds=120.0, host=host)
        if completed.returncode != 0:
            raise ModelControlError(
                code="LOAD_FAILED",
                message=completed.stderr.strip() or "lms estimate failed",
                provider_id=self.provider_id,
                model_id=model_id,
                http_status=502,
                details={"stdout": completed.stdout, "stderr": completed.stderr},
            )
        parsed = parse_lms_estimate_output(completed.stdout)
        return {
            "modelId": model_id,
            "modelKey": model_key,
            "estimate": parsed,
            "timestamp": utc_now(),
            "provenance": "PROVIDER_ESTIMATE",
            "providerVersion": caps.provider_version,
        }

    async def _load_via_rest(self, compiled) -> dict[str, Any]:
        try:
            return await self._native_post(
                "/models/load",
                compiled.rest_body,
                timeout=self.load_timeout_seconds,
            )
        except ModelControlError as exc:
            code = classify_lm_studio_error(exc.message, status_code=exc.http_status)
            raise ModelControlError(
                code=code,
                message=exc.message,
                provider_id=self.provider_id,
                http_status=exc.http_status,
                details=exc.details,
            ) from exc

    async def _load_via_cli(self, model_key: str, compiled) -> dict[str, Any]:
        argv = ["load", model_key, *compiled.cli_args]
        host = urlparse(self.host).netloc or None
        completed = run_lms_cli(argv, timeout_seconds=self.load_timeout_seconds, host=host)
        if completed.returncode != 0:
            msg = completed.stderr.strip() or completed.stdout.strip() or "lms load failed"
            code = classify_lm_studio_error(msg)
            raise ModelControlError(
                code=code,
                message=msg,
                provider_id=self.provider_id,
                http_status=502,
                details={"stdout": completed.stdout, "stderr": completed.stderr, "argv": argv},
            )
        # CLI does not echo structured load_config — mark applied as unknown
        return {
            "status": "loaded",
            "instance_id": model_key,
            "load_time_seconds": None,
            "load_config": None,
            "transport": "cli",
            "stdout": completed.stdout,
        }

    async def _native_get(self, path: str) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers=self._native_headers(),
            ) as client:
                resp = await client.get(f"{self.native_base}{path}")
        except httpx.TimeoutException as exc:
            raise ModelControlError(
                code=REQUEST_TIMEOUT,
                message="LM Studio native GET timed out",
                provider_id=self.provider_id,
                http_status=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"LM Studio offline: {exc}",
                provider_id=self.provider_id,
                http_status=503,
            ) from exc
        return self._parse_native_response(resp)

    async def _native_post(self, path: str, body: dict[str, Any], *, timeout: float) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers=self._native_headers(),
            ) as client:
                resp = await client.post(f"{self.native_base}{path}", json=body)
        except httpx.TimeoutException as exc:
            raise ModelControlError(
                code="LOAD_TIMEOUT",
                message=f"LM Studio native POST {path} timed out after {timeout}s",
                provider_id=self.provider_id,
                http_status=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelControlError(
                code=PROVIDER_OFFLINE,
                message=f"LM Studio offline: {exc}",
                provider_id=self.provider_id,
                http_status=503,
            ) from exc
        return self._parse_native_response(resp)

    def _parse_native_response(self, resp: httpx.Response) -> Any:
        if resp.status_code == 401:
            raise ModelControlError(
                code=PROVIDER_AUTH_FAILED,
                message="LM Studio authentication failed",
                provider_id=self.provider_id,
                http_status=401,
            )
        if resp.status_code == 404:
            raise ModelControlError(
                code=MODEL_NOT_FOUND,
                message=resp.text[:500] or "LM Studio resource not found",
                provider_id=self.provider_id,
                http_status=404,
            )
        if resp.status_code >= 400:
            msg = resp.text[:1000] or f"LM Studio HTTP {resp.status_code}"
            code = classify_lm_studio_error(msg, status_code=resp.status_code)
            raise ModelControlError(
                code=code,
                message=msg,
                provider_id=self.provider_id,
                http_status=min(resp.status_code, 599) if resp.status_code >= 400 else 502,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {"raw": resp.text}


def _extract_version(data: Any, headers: httpx.Headers | None = None) -> str | None:
    if headers:
        for key in ("x-lmstudio-version", "x-lm-studio-version", "server"):
            val = headers.get(key)
            if val and any(ch.isdigit() for ch in val):
                # Prefer explicit version headers
                if "lmstudio" in key.lower() or "lm-studio" in key.lower():
                    return val.strip()
    if isinstance(data, dict):
        for key in ("version", "lmStudioVersion", "server_version", "appVersion"):
            if data.get(key):
                return str(data[key])
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("version"):
            return str(meta["version"])
    return None


def _extract_model_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("models", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _resolve_model_key(model_id: str) -> str:
    """Strip Leviathan provider prefixes to get LM Studio model key."""
    text = (model_id or "").strip()
    for prefix in ("lm_studio:", "lmstudio:", "provider:lm_studio:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    # Common registry form: provider_id/model
    if "/" in text and text.count("/") >= 1:
        # Keep publisher/model form which LM Studio uses
        return text
    return text


def _instance_matches(
    loaded: list[dict[str, Any]],
    model_key: str,
    instance_id: str | None,
) -> bool:
    key = (model_key or "").lower()
    iid = (instance_id or "").lower()
    for item in loaded:
        item_iid = str(item.get("instance_id") or item.get("instanceId") or "").lower()
        item_model = str(
            item.get("model") or item.get("id") or item.get("modelKey") or item.get("path") or ""
        ).lower()
        if iid and item_iid and iid == item_iid:
            return True
        if key and (key in item_model or item_model in key or key == item_iid):
            return True
        if iid and iid in item_model:
            return True
    return False
