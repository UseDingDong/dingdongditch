"""Public, model-neutral contracts for deterministic page observation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from dingdongditch.contract.authority import ProvenanceClass, merge_provenance


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


class FrozenDict(dict):
    """JSON-compatible immutable mapping used by published evidence."""

    def __init__(self, value: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        dict.__init__(self)
        source = dict(value or {}, **kwargs)
        dict.update(self, {key: freeze(item) for key, item in source.items()})

    def _immutable(self, *_: Any, **__: Any) -> None:
        raise TypeError("published observation evidence is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable


class FrozenList(list):
    """JSON-compatible immutable sequence used by published evidence."""

    def __init__(self, values: Iterable[Any] = ()) -> None:
        list.__init__(self, (freeze(value) for value in values))

    def _immutable(self, *_: Any, **__: Any) -> None:
        raise TypeError("published observation evidence is immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable


def freeze(value: Any) -> Any:
    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, (list, tuple)):
        return FrozenList(value)
    return value


class ObservationTransactionState(str, Enum):
    REQUESTED = "requested"
    BINDING = "binding"
    CAPTURING = "capturing"
    VALIDATING = "validating"
    DERIVING = "deriving"
    SEALED = "sealed"
    COMMITTED = "committed"
    ABORTING = "aborting"
    ABORTED = "aborted"


class CandidateEvidenceLevel(str, Enum):
    DERIVED = "derived"
    SNAPSHOT_UNIQUE = "snapshot_unique"
    ATTESTED = "attested"
    DISPATCH_VERIFIED = "dispatch_verified"


class LocatorAttestationStatus(str, Enum):
    ATTESTED_UNIQUE = "attested_unique"
    ATTESTED_MISSING = "attested_missing"
    ATTESTED_AMBIGUOUS = "attested_ambiguous"
    ATTESTATION_FAILED = "attestation_failed"


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


@dataclass(frozen=True)
class SnapshotCore:
    snapshot_id: str
    transaction_id: str
    captured_at_ms: int
    browser_binding: FrozenDict
    signature: str
    payload_hash: str
    capture_evidence: FrozenDict

    def __post_init__(self) -> None:
        object.__setattr__(self, "browser_binding", freeze(self.browser_binding))
        object.__setattr__(self, "capture_evidence", freeze(self.capture_evidence))

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.__dict__)


@dataclass(frozen=True)
class ObservationCommit:
    commit_id: str
    transaction_id: str
    observation_id: str
    snapshot_id: str
    observation_hash: str
    committed_at_ms: int
    state: ObservationTransactionState
    browser_binding: FrozenDict
    evidence: FrozenDict

    def __post_init__(self) -> None:
        if self.state != ObservationTransactionState.COMMITTED:
            raise ValueError("ObservationCommit state must be committed")
        object.__setattr__(self, "browser_binding", freeze(self.browser_binding))
        object.__setattr__(self, "evidence", freeze(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.__dict__)


@dataclass(frozen=True)
class ObservationTransactionEvidence:
    transaction_id: str
    state: ObservationTransactionState
    states: FrozenList
    browser_binding: FrozenDict
    started_at_ms: int
    completed_at_ms: int | None
    failure_kind: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "states", freeze(self.states))
        object.__setattr__(self, "browser_binding", freeze(self.browser_binding))

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.__dict__)


@dataclass(frozen=True)
class LocatorAttestation:
    attestation_id: str
    query_id: str
    query_reused: bool
    observation_id: str
    commit_id: str
    candidate_id: str
    element_id: str
    locator_type: str
    locator_value: Any
    attested_at_ms: int
    browser_binding: FrozenDict
    match_count: int | None
    unique: bool
    status: LocatorAttestationStatus
    confidence: float
    known_ambiguity: str | None
    evidence_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "locator_value", freeze(self.locator_value))
        object.__setattr__(self, "browser_binding", freeze(self.browser_binding))

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.__dict__)


@dataclass(frozen=True)
class ObservationReference:
    observation_id: str
    element_id: str
    expected: dict[str, Any] = field(default_factory=dict)
    control_epoch: int | None = None
    mutation_epoch: int | None = None
    # Browser/page-derived observations are untrusted input by default.  A
    # reference retains this label when used by a governed session so a
    # planner cannot make it disappear merely by reformatting target data.
    provenance: tuple[ProvenanceClass, ...] = (ProvenanceClass.WEB_UNTRUSTED,)


@dataclass(frozen=True)
class ObservationFreshnessResult:
    fresh: bool
    reason: str
    element: dict[str, Any] | None = None
    commit_id: str | None = None
    observation_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PageObservation:
    observation_id: str
    timestamp: str
    captured_at_ms: int
    browser_profile: str
    url: str
    title: str
    viewport: FrozenDict
    document: FrozenDict
    focus: FrozenDict
    overlays: FrozenList
    regions: FrozenList
    visible_text: FrozenList
    interactive_elements: FrozenList
    spatial_relationships: FrozenList
    scroll_context: FrozenDict
    freshness: FrozenDict
    diagnostics: FrozenDict
    transaction_id: str = ""
    snapshot_id: str = ""
    commit_id: str = ""
    observation_hash: str = ""
    provenance: tuple[ProvenanceClass, ...] = (ProvenanceClass.WEB_UNTRUSTED,)

    def __post_init__(self) -> None:
        for name in (
            "viewport", "document", "focus", "overlays", "regions",
            "visible_text", "interactive_elements", "spatial_relationships",
            "scroll_context", "freshness", "diagnostics",
        ):
            object.__setattr__(self, name, freeze(getattr(self, name)))
        declared = self.provenance or (ProvenanceClass.WEB_UNTRUSTED,)
        try:
            normalized = tuple(
                value if isinstance(value, ProvenanceClass) else ProvenanceClass(value)
                for value in declared
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("observation provenance is invalid") from exc
        object.__setattr__(self, "provenance", merge_provenance(normalized))

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PageObservation":
        return cls(**dict(value))


@dataclass(frozen=True)
class ObservationEvidenceView:
    observation: PageObservation
    commit: ObservationCommit
    attestations: tuple[LocatorAttestation, ...] = ()
    freshness: ObservationFreshnessResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.to_dict(),
            "commit": self.commit.to_dict(),
            "attestations": [item.to_dict() for item in self.attestations],
            "freshness": self.freshness.to_dict() if self.freshness else None,
        }
