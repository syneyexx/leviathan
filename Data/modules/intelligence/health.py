"""IntelligenceHealthService — truthful stack health for Settings banner & diagnostics."""

from __future__ import annotations

from typing import Any

from .consumer_truth import (
    ConsumerTruthReport,
    build_consumer_truth,
    feature_section_from_report,
)
from .policy import ReasoningPolicy


def _flag(obj: Any, *names: str, default: Any = None) -> Any:
    cur = obj
    for name in names:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(name, default if name == names[-1] else None)
        else:
            cur = getattr(cur, name, default if name == names[-1] else None)
    return cur if cur is not None else default


def _banner_state(*, desired: bool, effective: bool, capability: bool) -> str:
    if not desired:
        return "OFF"
    if effective and capability:
        return "ON"
    if desired and not effective:
        return "DEGRADED"
    return "OFF"


class IntelligenceHealthService:
    """Build a truthful intelligence-stack health payload from live objects."""

    def __init__(
        self,
        *,
        settings: Any | None = None,
        settings_plane: Any | None = None,
        cognition_runtime: Any | None = None,
        neuro_advisor: Any | None = None,
        residual_port: Any | None = None,
        knowledge: Any | None = None,
        retriever: Any | None = None,
        memory_store: Any | None = None,
        deep_recall: Any | None = None,
        atlas: Any | None = None,
        verification_engine: Any | None = None,
        assimilation_service: Any | None = None,
        embedding_provider: Any | None = None,
        reranker: Any | None = None,
        cortex: Any | None = None,
        experience_store: Any | None = None,
        reasoning_policy: ReasoningPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.settings_plane = settings_plane
        self.cognition_runtime = cognition_runtime
        self.neuro_advisor = neuro_advisor
        self.residual_port = residual_port
        self.knowledge = knowledge
        self.retriever = retriever
        self.memory_store = memory_store
        self.deep_recall = deep_recall
        self.atlas = atlas
        self.verification_engine = verification_engine
        self.assimilation_service = assimilation_service
        self.embedding_provider = embedding_provider
        self.reranker = reranker
        self.cortex = cortex
        self.experience_store = experience_store
        self.reasoning_policy = reasoning_policy

    def _settings_obj(self) -> Any | None:
        if self.settings is not None:
            return self.settings
        if self.settings_plane is not None:
            return getattr(self.settings_plane, "effective", None) or getattr(
                self.settings_plane, "_effective", None
            )
        return None

    def _policy(self) -> ReasoningPolicy:
        if self.reasoning_policy is not None:
            return self.reasoning_policy
        settings = self._settings_obj()
        if settings is not None:
            return ReasoningPolicy.from_settings(settings)
        return ReasoningPolicy()

    def _embeddings_live(self) -> Any | None:
        if self.embedding_provider is not None:
            return self.embedding_provider
        if self.retriever is not None:
            return getattr(self.retriever, "embeddings", None)
        if self.knowledge is not None:
            return getattr(self.knowledge, "embeddings", None)
        return None

    def _residual_supported(self) -> bool:
        port = self.residual_port
        if port is None and self.neuro_advisor is not None:
            port = getattr(self.neuro_advisor, "residual_port", None)
        if port is None:
            return False
        if hasattr(port, "supports_residuals"):
            try:
                return bool(port.supports_residuals())
            except Exception:  # noqa: BLE001
                return False
        return False

    def _residual_kind(self) -> str:
        settings = self._settings_obj()
        kind = _flag(settings, "neuro_runtime", "residual_kind", default="unsupported")
        return str(kind or "unsupported").strip().lower()

    def build_feature_report(
        self,
        *,
        feature_key: str,
        desired: Any,
        effective: Any,
        consumer: str,
        consumer_active: bool,
        capability_available: bool,
        degraded_reason: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> ConsumerTruthReport:
        return build_consumer_truth(
            feature_key=feature_key,
            desired=desired,
            effective=effective,
            consumer=consumer,
            consumer_active=consumer_active,
            capability_available=capability_available,
            degraded_reason=degraded_reason,
            detail=detail,
        )

    def _section_reasoning(self) -> dict[str, Any]:
        settings = self._settings_obj()
        policy = self._policy()
        desired = bool(_flag(settings, "reasoning", "enabled", default=policy.enabled))
        cognition_on = bool(_flag(settings, "features", "cognition_enabled", default=False))
        consumer_active = self.cognition_runtime is not None or cognition_on
        effective = desired and policy.enabled
        report = self.build_feature_report(
            feature_key="reasoning.enabled",
            desired=desired,
            effective=effective,
            consumer="ReasoningPolicy / MetaController",
            consumer_active=bool(consumer_active),
            capability_available=True,
            detail={
                "default_mode": policy.default_mode,
                "allow_fast_path": policy.allow_fast_path,
                "policy": policy.public_dict(),
            },
        )
        section = feature_section_from_report(report)
        section["mode"] = policy.default_mode
        return section

    def _section_cognition(self) -> dict[str, Any]:
        settings = self._settings_obj()
        desired = bool(_flag(settings, "features", "cognition_enabled", default=False))
        runtime = self.cognition_runtime
        runtime_health = runtime.health() if runtime is not None and hasattr(runtime, "health") else {}
        runtime_enabled = bool(runtime_health.get("enabled", runtime is not None and desired))
        effective = desired and runtime_enabled
        degraded = None
        if desired and runtime is None:
            degraded = "cognition_runtime_not_wired"
            effective = False
        elif desired and not runtime_enabled:
            degraded = "cognition_runtime_disabled"
        report = self.build_feature_report(
            feature_key="features.cognition_enabled",
            desired=desired,
            effective=effective,
            consumer="CognitiveRuntime",
            consumer_active=runtime is not None,
            capability_available=runtime is not None,
            degraded_reason=degraded,
            detail={
                "shadow_default": runtime_health.get("shadow_default"),
                "iterative": runtime_health.get("iterative")
                or _flag(settings, "features", "cognition_iterative_loop", default=False),
                "belief_state": _flag(settings, "features", "cognition_belief_state", default=False),
                "experience_learning": _flag(
                    settings, "features", "cognition_experience_learning", default=False
                ),
                "runtime_health": runtime_health,
            },
        )
        return feature_section_from_report(report)

    def _section_rag(self) -> dict[str, Any]:
        settings = self._settings_obj()
        desired = bool(_flag(settings, "features", "rag_v3", default=False))
        retriever_live = self.retriever is not None
        effective = desired and retriever_live
        degraded = None
        if desired and not retriever_live:
            degraded = "retriever_not_wired"
        report = self.build_feature_report(
            feature_key="features.rag_v3",
            desired=desired,
            effective=effective,
            consumer="HybridRetriever",
            consumer_active=retriever_live,
            capability_available=retriever_live or self.knowledge is not None,
            degraded_reason=degraded,
            detail={
                "deep_recall": bool(_flag(settings, "features", "deep_recall", default=False)),
                "why_library": bool(_flag(settings, "features", "why_library", default=False)),
                "knowledge_wired": self.knowledge is not None,
            },
        )
        return feature_section_from_report(report)

    def _section_embeddings(self) -> dict[str, Any]:
        settings = self._settings_obj()
        configured = str(
            _flag(settings, "knowledge", "embedding_provider", default="null") or "null"
        ).strip().lower()
        live = self._embeddings_live()
        status: dict[str, Any] = {}
        if live is not None and hasattr(live, "status"):
            try:
                status = dict(live.status() or {})
            except Exception as exc:  # noqa: BLE001
                status = {"error": str(exc)}
        effective_id = (
            status.get("provider_id")
            or getattr(live, "provider_id", None)
            or "unwired"
        )
        available = bool(status.get("available", getattr(live, "available", lambda: False)()))
        semantic = bool(
            status.get("is_semantic", getattr(live, "is_semantic", False))
        ) and available
        degraded = None
        if configured in {"sentence_transformers", "st", "sbert", "auto"} and not semantic:
            if configured == "auto" and effective_id in {"local_hash", "hash"}:
                degraded = "auto_resolved_to_nonsemantic_hash"
            elif not available:
                degraded = "embedding_provider_unavailable"
        report = self.build_feature_report(
            feature_key="knowledge.embedding_provider",
            desired=configured,
            effective=effective_id,
            consumer="EmbeddingProvider",
            consumer_active=live is not None,
            capability_available=available,
            degraded_reason=degraded,
            detail={
                "configured": configured,
                "effective": effective_id,
                "semantic": semantic,
                "available": available,
                "status": status,
                "model": _flag(settings, "knowledge", "embedding_model", default=None),
            },
        )
        section = feature_section_from_report(report)
        section["configured"] = configured
        section["semantic"] = semantic
        section["available"] = available
        return section

    def _section_reranker(self) -> dict[str, Any]:
        settings = self._settings_obj()
        model = _flag(settings, "knowledge", "reranker_model", default=None)
        desired = bool(model)
        reranker = self.reranker
        if reranker is None and self.retriever is not None:
            reranker = getattr(self.retriever, "reranker", None)
        available = False
        status: dict[str, Any] = {}
        if reranker is not None:
            if hasattr(reranker, "available"):
                try:
                    available = bool(reranker.available())
                except Exception:  # noqa: BLE001
                    available = False
            if hasattr(reranker, "status"):
                try:
                    status = dict(reranker.status() or {})
                except Exception as exc:  # noqa: BLE001
                    status = {"error": str(exc)}
        effective = desired and available
        degraded = None
        if desired and not available:
            degraded = str(status.get("error") or "reranker_unavailable")
        report = self.build_feature_report(
            feature_key="knowledge.reranker_model",
            desired=desired,
            effective=effective,
            consumer="RerankerProvider",
            consumer_active=reranker is not None,
            capability_available=available,
            degraded_reason=degraded,
            detail={"model": model, "status": status},
        )
        return feature_section_from_report(report)

    def _section_memory(self) -> dict[str, Any]:
        settings = self._settings_obj()
        desired = bool(_flag(settings, "features", "memory_semantic", default=False))
        store_live = self.memory_store is not None
        effective = desired and store_live
        degraded = None
        if desired and not store_live:
            degraded = "memory_store_not_wired"
        report = self.build_feature_report(
            feature_key="features.memory_semantic",
            desired=desired,
            effective=effective,
            consumer="MemoryStore",
            consumer_active=store_live,
            capability_available=store_live,
            degraded_reason=degraded,
        )
        return feature_section_from_report(report)

    def _section_atlas(self) -> dict[str, Any]:
        desired = self.atlas is not None or bool(
            _flag(self._settings_obj(), "features", "rag_v3", default=False)
        )
        live = self.atlas is not None
        report = self.build_feature_report(
            feature_key="knowledge.atlas",
            desired=desired,
            effective=live,
            consumer="AtlasStore",
            consumer_active=live,
            capability_available=live,
            degraded_reason=None if live else "atlas_not_wired",
        )
        return feature_section_from_report(report)

    def _section_neuro(self) -> dict[str, Any]:
        settings = self._settings_obj()
        desired = bool(_flag(settings, "features", "neuro_enabled", default=False))
        advisor = self.neuro_advisor
        advisor_on = bool(getattr(advisor, "enabled", False)) if advisor is not None else False
        effective = desired and (advisor_on or advisor is not None)
        if desired and advisor is None:
            effective = False
            degraded = "neuro_advisor_not_wired"
        elif desired and not advisor_on:
            degraded = "neuro_advisor_disabled"
            effective = False
        else:
            degraded = None
        report = self.build_feature_report(
            feature_key="features.neuro_enabled",
            desired=desired,
            effective=effective,
            consumer="NeuroAdvisor",
            consumer_active=advisor is not None,
            capability_available=advisor is not None,
            degraded_reason=degraded,
            detail={
                "associative_memory": _flag(
                    settings, "features", "neuro_associative_memory", default=False
                ),
                "process_critic": _flag(
                    settings, "features", "neuro_process_critic", default=False
                ),
            },
        )
        return feature_section_from_report(report)

    def _section_cortex(self) -> dict[str, Any]:
        settings = self._settings_obj()
        desired = bool(_flag(settings, "features", "neuro_cortex", default=False))
        neuro_on = bool(_flag(settings, "features", "neuro_enabled", default=False))
        cortex_obj = self.cortex
        if cortex_obj is None and self.neuro_advisor is not None:
            cortex_obj = getattr(self.neuro_advisor, "cortex_planner", None)
        live = cortex_obj is not None
        capability = live and neuro_on
        effective = desired and neuro_on and live
        degraded = None
        if desired and not neuro_on:
            degraded = "requires_neuro_enabled"
            effective = False
        elif desired and not live:
            degraded = "cortex_not_wired"
            effective = False
        report = self.build_feature_report(
            feature_key="features.neuro_cortex",
            desired=desired,
            effective=effective,
            consumer="CortexPlanner",
            consumer_active=live,
            capability_available=capability,
            degraded_reason=degraded,
            detail={
                "cortex_blocks": _flag(
                    settings, "features", "neuro_cortex_blocks", default=False
                ),
            },
        )
        return feature_section_from_report(report)

    def _section_residual(self) -> dict[str, Any]:
        settings = self._settings_obj()
        desired = bool(
            _flag(settings, "features", "neuro_residual_injection", default=False)
        )
        kind = self._residual_kind()
        supported = self._residual_supported()
        # Unsupported kind can never be effective even when the flag is ON.
        if kind in {"unsupported", "none", "off", ""}:
            supported = False
            capability = False
            effective = False
            degraded = (
                f"residual_kind_unsupported:{kind or 'unsupported'}"
                if desired
                else None
            )
        else:
            capability = supported
            effective = desired and supported
            degraded = None
            if desired and not supported:
                degraded = f"residual_runtime_unsupported_kind={kind}"
        report = self.build_feature_report(
            feature_key="features.neuro_residual_injection",
            desired=desired,
            effective=effective,
            consumer="ResidualPort",
            consumer_active=self.residual_port is not None
            or (
                self.neuro_advisor is not None
                and getattr(self.neuro_advisor, "residual_port", None) is not None
            ),
            capability_available=capability,
            degraded_reason=degraded,
            detail={
                "residual_kind": kind,
                "supports_residuals": supported,
                "residual_production": _flag(
                    settings, "features", "residual_production", default=False
                ),
                "orchestrator": _flag(
                    settings, "features", "neuro_residual_orchestrator", default=False
                ),
            },
        )
        return feature_section_from_report(report)

    def _section_verification(self) -> dict[str, Any]:
        policy = self._policy()
        desired = bool(policy.require_verification_for_high_risk)
        live = self.verification_engine is not None
        effective = desired and live
        degraded = None
        if desired and not live:
            degraded = "verification_engine_not_wired"
        report = self.build_feature_report(
            feature_key="reasoning.require_verification_for_high_risk",
            desired=desired,
            effective=effective,
            consumer="VerificationEngine",
            consumer_active=live,
            capability_available=live,
            degraded_reason=degraded,
        )
        return feature_section_from_report(report)

    def _section_assimilation(self) -> dict[str, Any]:
        svc = self.assimilation_service
        live = svc is not None
        health = svc.health() if live and hasattr(svc, "health") else {}
        report = self.build_feature_report(
            feature_key="intelligence.assimilation",
            desired=True,
            effective=live,
            consumer="KnowledgeAssimilationService",
            consumer_active=live,
            capability_available=live,
            degraded_reason=None if live else "assimilation_service_not_wired",
            detail=health,
        )
        return feature_section_from_report(report)

    def _section_training_feedback(self) -> dict[str, Any]:
        settings = self._settings_obj()
        desired = bool(
            _flag(settings, "features", "cognition_experience_learning", default=False)
        )
        runtime = self.cognition_runtime
        learning_on = False
        if runtime is not None:
            learning_on = bool(getattr(runtime, "experience_learning", False))
            if hasattr(runtime, "health"):
                try:
                    learning_on = bool(runtime.health().get("experience_learning", learning_on))
                except Exception:  # noqa: BLE001
                    pass
        store_live = self.experience_store is not None or (
            runtime is not None and getattr(runtime, "store", None) is not None
        )
        effective = desired and learning_on
        degraded = None
        if desired and not learning_on:
            degraded = "experience_learning_inactive"
        report = self.build_feature_report(
            feature_key="features.cognition_experience_learning",
            desired=desired,
            effective=effective,
            consumer="VerifiedExperience",
            consumer_active=learning_on or store_live,
            capability_available=store_live or runtime is not None,
            degraded_reason=degraded,
            detail={"experience_store_wired": store_live},
        )
        return feature_section_from_report(report)

    def _stack_summary(self, sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
        policy = self._policy()
        degraded_keys = [
            key
            for key, section in sections.items()
            if section.get("degraded") or section.get("degraded_reason")
        ]
        # Critical path degradation flips the banner to DEGRADED.
        critical = {
            "reasoning",
            "cognition",
            "rag",
            "embeddings",
            "memory",
            "neuro",
            "residual",
            "verification",
        }
        critical_degraded = [k for k in degraded_keys if k in critical]
        status = "DEGRADED" if critical_degraded else "ACTIVE"

        emb = sections.get("embeddings") or {}
        residual = sections.get("residual") or {}
        neuro = sections.get("neuro") or {}
        cortex = sections.get("cortex") or {}
        cognition = sections.get("cognition") or {}
        rag = sections.get("rag") or {}
        memory = sections.get("memory") or {}
        verification = sections.get("verification") or {}
        learning = sections.get("training_feedback") or {}

        return {
            "status": status,
            "label": f"Intelligence Stack {status}",
            "reasoning_mode": policy.default_mode,
            "rag": _banner_state(
                desired=bool(rag.get("desired")),
                effective=bool(rag.get("effective")),
                capability=bool(rag.get("capability_available")),
            ),
            "semantic_retrieval": (
                "ON"
                if emb.get("semantic")
                else ("DEGRADED" if emb.get("desired") not in {None, "null", "none", "off", False} else "OFF")
            ),
            "memory": _banner_state(
                desired=bool(memory.get("desired")),
                effective=bool(memory.get("effective")),
                capability=bool(memory.get("capability_available")),
            ),
            "cognition": _banner_state(
                desired=bool(cognition.get("desired")),
                effective=bool(cognition.get("effective")),
                capability=bool(cognition.get("capability_available")),
            ),
            "neuro": _banner_state(
                desired=bool(neuro.get("desired")),
                effective=bool(neuro.get("effective")),
                capability=bool(neuro.get("capability_available")),
            ),
            "cortex": _banner_state(
                desired=bool(cortex.get("desired")),
                effective=bool(cortex.get("effective")),
                capability=bool(cortex.get("capability_available")),
            ),
            "residual": _banner_state(
                desired=bool(residual.get("desired")),
                effective=bool(residual.get("effective")),
                capability=bool(residual.get("capability_available")),
            ),
            "verification": _banner_state(
                desired=bool(verification.get("desired")),
                effective=bool(verification.get("effective")),
                capability=bool(verification.get("capability_available")),
            ),
            "learning": _banner_state(
                desired=bool(learning.get("desired")),
                effective=bool(learning.get("effective")),
                capability=bool(learning.get("capability_available")),
            ),
            "degraded_sections": degraded_keys,
            "critical_degraded": critical_degraded,
            "truth": {
                "banner_reflects_effective_not_desired": True,
                "unsupported_residual_is_degraded_not_active": True,
                "hash_embeddings_are_not_semantic": True,
            },
        }

    def build(self) -> dict[str, Any]:
        """Return the full intelligence health payload."""
        sections = {
            "reasoning": self._section_reasoning(),
            "cognition": self._section_cognition(),
            "rag": self._section_rag(),
            "embeddings": self._section_embeddings(),
            "reranker": self._section_reranker(),
            "memory": self._section_memory(),
            "atlas": self._section_atlas(),
            "neuro": self._section_neuro(),
            "cortex": self._section_cortex(),
            "residual": self._section_residual(),
            "verification": self._section_verification(),
            "assimilation": self._section_assimilation(),
            "training_feedback": self._section_training_feedback(),
        }
        payload = dict(sections)
        payload["stack_summary"] = self._stack_summary(sections)
        payload["truth"] = {
            "desired_is_not_effective": True,
            "flag_on_is_not_capability": True,
            "unavailable_is_not_success": True,
            "no_fake_active_when_degraded": True,
        }
        return payload

    def public_dict(self) -> dict[str, Any]:
        return self.build()
