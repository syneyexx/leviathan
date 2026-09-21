"""MCPMarket.com discovery connector. HADES remains authoritative."""

from .connector import MCPMarketConnector, get_connector, reset_connector
from .normalize import listing_to_capabilities
from .official import official_surface

__all__ = [
    "MCPMarketConnector",
    "get_connector",
    "listing_to_capabilities",
    "official_surface",
    "reset_connector",
]
