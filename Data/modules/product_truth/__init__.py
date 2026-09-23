"""Product Truth — evidence-based operator/product status (Round 9)."""

from .posture import (
    ComponentPosture,
    ProductStatus,
    ProductTruthReport,
    assess_product_truth,
    confidence_is_meaningless,
    normalize_status,
)

__all__ = [
    "ComponentPosture",
    "ProductStatus",
    "ProductTruthReport",
    "assess_product_truth",
    "confidence_is_meaningless",
    "normalize_status",
]
