"""Provider adapters. Adding a source must never touch the corpus code."""
from .base import (PERMITTED_KEYS, ProviderAdapter, ProviderError,
                   ProviderResult, SourceMeta, ensure_research_allowed)
from .csv_mapped import CsvMappedProvider
from .synthetic import SyntheticProvider

__all__ = ["PERMITTED_KEYS", "ProviderAdapter", "ProviderError",
           "ProviderResult", "SourceMeta", "ensure_research_allowed",
           "CsvMappedProvider", "SyntheticProvider"]
