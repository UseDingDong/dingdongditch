"""Public, model-neutral contracts for deterministic page observation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PageObservationOptions:
    max_interactive_elements: int = 300
    max_text_blocks: int = 200
    max_regions: int = 100
    max_relationships_per_element: int = 6
    max_relationship_distance_px: float = 800.0
    max_scrollable_containers: int = 50
    max_payload_bytes: int = 2_000_000
    max_text_length: int = 500
    freshness_max_age_ms: int = 30_000
    observation_budget_ms: int = 5_000
    mutation_quiescence_ms: int = 125

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass
class ObservationReference:
    observation_id: str
    element_id: str
    expected: dict[str, Any] = field(default_factory=dict)


@dataclass
class ObservationFreshnessResult:
    fresh: bool
    reason: str
    element: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageObservation:
    observation_id: str
    timestamp: str
    captured_at_ms: int
    browser_profile: str
    url: str
    title: str
    viewport: dict[str, Any]
    document: dict[str, Any]
    focus: dict[str, Any]
    overlays: list[dict[str, Any]]
    regions: list[dict[str, Any]]
    visible_text: list[dict[str, Any]]
    interactive_elements: list[dict[str, Any]]
    spatial_relationships: list[dict[str, Any]]
    scroll_context: dict[str, Any]
    freshness: dict[str, Any]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
