"""External data-source adapters.

The semantic layer never talks to a vendor SDK directly — it talks to a
`DataSourceAdapter`. Adding Shopify/CRM/GA4 means adding one file here; nothing
in the analytics engine changes. See docs/ADR/0004.
"""
from .base import DataSourceAdapter, SourceStatus, registry

__all__ = ["DataSourceAdapter", "SourceStatus", "registry"]
