"""Reconcile dynamic catalog projections across API / worker processes."""

from __future__ import annotations

from typing import Any

from .catalog import CapabilityCatalog
from .catalog_generation import (
    SCOPE_CUSTOM,
    SCOPE_PLUGINS,
    CatalogGenerationStore,
    CatalogProjectionTracker,
)
from .custom_store import CustomCapabilityStore


def reconcile_dynamic_catalog(
    catalog: CapabilityCatalog,
    *,
    custom_store: CustomCapabilityStore | None = None,
    plugin_registry: Any | None = None,
    generation_store: CatalogGenerationStore | None = None,
    tracker: CatalogProjectionTracker | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Hydrate custom wrappers / plugins when durable generation advanced."""
    actions: list[str] = []
    generations: dict[str, int] = {}
    projected = tracker or CatalogProjectionTracker()

    if custom_store is not None:
        gen_store = generation_store or custom_store.generation_store
        durable = custom_store.get_catalog_generation()
        generations[SCOPE_CUSTOM] = durable
        if force or projected.is_stale(gen_store, SCOPE_CUSTOM):
            count = custom_store.hydrate_into_catalog(catalog)
            projected.mark(SCOPE_CUSTOM, durable)
            actions.append(f"custom_hydrated:{count}")

    if plugin_registry is not None and hasattr(plugin_registry, "hydrate_from_store"):
        gen = 0
        if hasattr(plugin_registry, "get_catalog_generation"):
            gen = int(plugin_registry.get_catalog_generation() or 0)
        generations[SCOPE_PLUGINS] = gen
        plugin_gen_store = getattr(plugin_registry, "_generation", None)
        stale = force
        if plugin_gen_store is not None and not force:
            stale = projected.is_stale(plugin_gen_store, SCOPE_PLUGINS)
        elif not force:
            stale = projected.projected(SCOPE_PLUGINS) != gen
        if stale:
            count = int(plugin_registry.hydrate_from_store() or 0)
            projected.mark(SCOPE_PLUGINS, gen)
            actions.append(f"plugins_hydrated:{count}")

    return {
        "actions": actions,
        "catalog_generations": generations,
        "truth": {
            "process_local_catalog_is_not_source_of_truth": True,
            "generation_is_not_authorization": True,
        },
    }
