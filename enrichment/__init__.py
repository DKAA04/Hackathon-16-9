"""DuckDuckGov contact enrichment: phone numbers, e-mail addresses and websites with evidence.

    from enrichment import Enricher, target_from_row
    enricher = Enricher()
    result = enricher.enrich(target_from_row(vkbo_row))
    result.to_dict()
"""
from .models import EnrichmentResult, EnrichTarget, Finding, Observation, SourceRun
from .pipeline import Enricher, Options
from .records import fetch_vkbo, load_file, target_from_row

__all__ = [
    "Enricher",
    "Options",
    "EnrichTarget",
    "EnrichmentResult",
    "Finding",
    "Observation",
    "SourceRun",
    "fetch_vkbo",
    "load_file",
    "target_from_row",
]
