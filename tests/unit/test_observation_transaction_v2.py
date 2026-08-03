from __future__ import annotations

from types import SimpleNamespace

import pytest

from dingdongditch.contract.observation import (
    LocatorAttestationStatus,
    ObservationTransactionState,
    PageObservationOptions,
)
from dingdongditch.page_observer import (
    PageObserver,
    _SNAPSHOT_JS,
    _WAIT_FOR_MUTATION_QUIESCENCE_JS,
)


def raw_snapshot():
    return {
        "url": "https://example.test", "title": "Example",
        "viewport": {"width": 100, "height": 100, "device_pixel_ratio": 1},
        "document": {"width": 100, "height": 100, "scroll_x": 0, "scroll_y": 0},
        "focus": {}, "overlays": [], "regions": [{
            "region_id": "reg_1", "semantic_role": "main",
            "accessible_name": "Main", "visible": True,
            "bounds_px": {}, "bounds_normalized": {},
            "parent_region_id": None, "child_region_ids": [],
            "interactive_element_ids": ["el_1"],
        }], "textBlocks": [],
        "scrollables": [], "totalElements": 1, "totalRegions": 1,
        "textLimitReached": False, "signature": "snapshot-signature",
        "elements": [{
            "element_id": "el_1", "node_continuity_token": "document:1",
            "dom_tag": "button", "semantic_role": "button",
            "accessible_name": "Go", "visible_text": "Go", "input_type": None,
            "href": None, "placeholder": None, "current_value": None,
            "value_redacted": False, "enabled": True, "visible": True,
            "editable": False, "focusable": True, "focused": False,
            "checked": None, "selected": None, "selected_state_source": None,
            "expanded": None, "pressed": None, "required": False, "readonly": False,
            "bounds_px": {"x": 0, "y": 0, "width": 10, "height": 10},
            "bounds_normalized": {"x": 0, "y": 0, "width": 10, "height": 10},
            "center_px": {"x": 5, "y": 5}, "center_normalized": {"x": 5, "y": 5},
            "viewport_inclusion": "fully", "occlusion_state": "not_occluded",
            "owning_region_id": "reg_1", "parent_interactive_element_id": None,
            "useful_attributes": {"data-testid": "go"},
        }],
    }


class CountLocator:
    def __init__(self, count): self._count = count
    def count(self):
        if isinstance(self._count, Exception):
            raise self._count
        return self._count
    def get_by_role(self, *args, **kwargs):
        return self


class FakePage:
    url = "https://example.test"
    def __init__(self, raw=None, count=1):
        self.raw, self.count_value, self.count_calls = raw, count, 0
    def evaluate(self, script, arguments=None):
        if script == _WAIT_FOR_MUTATION_QUIESCENCE_JS:
            return {"quiescent": True}
        assert script == _SNAPSHOT_JS
        return self.raw
    def _locator(self):
        self.count_calls += 1
        return CountLocator(self.count_value)
    def get_by_role(self, *args, **kwargs): return self._locator()
    def get_by_text(self, *args, **kwargs): return self._locator()
    def get_by_test_id(self, *args, **kwargs): return self._locator()
    def locator(self, *args, **kwargs): return self._locator()


class FakeBackend:
    is_started = True
    backend_identity = "test"
    browser_session_id = "session"
    context_id = "context"
    page_id = "page"
    _generation = 1
    browser_config = SimpleNamespace(profile=SimpleNamespace(value="benchmark"))
    browser_identity = "chromium"
    def __init__(self, raw=None, count=1, store=None):
        self.page = FakePage(raw, count)
        self.observation_store_root = store


def test_v2_lifecycle_commits_one_immutable_observation():
    observer = PageObserver(FakeBackend(raw_snapshot()))
    observation = observer.observe_page(PageObservationOptions())
    transaction = observer._transactions[observation.transaction_id]
    assert transaction.state == ObservationTransactionState.COMMITTED
    assert list(transaction.states) == [
        "requested", "binding", "capturing", "validating", "deriving", "sealed", "committed"
    ]
    assert observer._commits[observation.observation_id].observation_hash == observation.observation_hash
    assert observation.diagnostics["transaction"]["capture_mode"] == "atomic_snapshot_core"
    with pytest.raises((TypeError, AttributeError)):
        observation.interactive_elements.append({})
    with pytest.raises(TypeError):
        observation.interactive_elements[0]["enabled"] = False
    candidate = observation.interactive_elements[0]["locator_candidates"][0]
    assert candidate["snapshot_unique"] is True
    assert candidate["evidence_level"] == "snapshot_unique"
    assert candidate["attestation_status"] == "not_present"


def test_v2_abort_rolls_back_without_publication():
    observer = PageObserver(FakeBackend({"invalid": True}))
    with pytest.raises(ValueError, match="capture envelope"):
        observer.observe_page()
    assert observer._observations == {}
    assert observer._commits == {}
    transaction = next(iter(observer._transactions.values()))
    assert transaction.state == ObservationTransactionState.ABORTED
    assert list(transaction.states)[-2:] == ["aborting", "aborted"]


def test_attestation_is_independent_immutable_evidence_and_does_not_mutate_commit():
    observer = PageObserver(FakeBackend(raw_snapshot(), count=1))
    observation = observer.observe_page()
    before = observation.to_dict()
    records = observer.attest_observation_locators(observation.observation_id)
    assert records
    assert all(record.status == LocatorAttestationStatus.ATTESTED_UNIQUE for record in records)
    assert observer.backend.page.count_calls == 4
    assert len({record.query_id for record in records}) == 4
    reused = [record for record in records if record.query_reused]
    assert len(reused) == 0
    role_records = [record for record in records if record.locator_type in {"role_name", "within_region"}]
    assert len({record.query_id for record in role_records}) == 2
    assert observation.to_dict() == before
    with pytest.raises((TypeError, AttributeError)):
        records[0].browser_binding["page_id"] = "changed"
    view = observer.evidence_view(observation.observation_id)
    assert view.observation is observation
    assert view.commit.observation_hash == observation.observation_hash
    assert view.attestations == records


def test_ambiguous_attestation_fails_closed_without_invalidating_observation():
    observer = PageObserver(FakeBackend(raw_snapshot(), count=2))
    observation = observer.observe_page()
    records = observer.attest_observation_locators(observation.observation_id)
    assert records
    assert all(not record.unique for record in records)
    assert all(record.status == LocatorAttestationStatus.ATTESTED_AMBIGUOUS for record in records)
    assert observation.observation_id in observer._observations


def test_failed_duplicate_query_is_shared_but_every_candidate_fails_closed():
    observer = PageObserver(FakeBackend(raw_snapshot(), count=RuntimeError("query failed")))
    observation = observer.observe_page()
    records = observer.attest_observation_locators(observation.observation_id)
    assert observer.backend.page.count_calls == 4
    assert len(records) == 4
    assert all(record.status == LocatorAttestationStatus.ATTESTATION_FAILED for record in records)
    assert all(record.match_count is None and not record.unique for record in records)
    role_records = [record for record in records if record.locator_type in {"role_name", "within_region"}]
    assert len({record.query_id for record in role_records}) == 2
    assert not any(record.query_reused for record in role_records)


def test_attestation_rejects_browser_binding_mismatch(tmp_path):
    backend = FakeBackend(raw_snapshot(), store=tmp_path)
    observer = PageObserver(backend)
    observation = observer.observe_page()
    backend.page_id = "different-page"
    with pytest.raises(RuntimeError, match="binding_mismatch"):
        observer.attest_observation_locators(observation.observation_id)


def test_durable_commit_loads_after_observer_restart(tmp_path):
    backend = FakeBackend(raw_snapshot(), store=tmp_path)
    first = PageObserver(backend)
    observation = first.observe_page()
    restored = PageObserver(backend)
    view = restored.evidence_view(observation.observation_id)
    assert view.observation.to_dict() == observation.to_dict()
    assert view.commit.commit_id == observation.commit_id


def test_corrupt_durable_commit_is_not_loaded(tmp_path):
    backend = FakeBackend(raw_snapshot(), store=tmp_path)
    first = PageObserver(backend)
    observation = first.observe_page()
    path = next(tmp_path.glob("*.json"))
    path.write_text('{"schema_version":"1.0.0","observation":', encoding="utf-8")
    restored = PageObserver(backend)
    with pytest.raises(KeyError, match="unknown observation"):
        restored.evidence_view(observation.observation_id)


def test_failed_durable_publication_never_exposes_partial_commit(tmp_path, monkeypatch):
    backend = FakeBackend(raw_snapshot(), store=tmp_path)
    observer = PageObserver(backend)
    monkeypatch.setattr(
        "dingdongditch.page_observer.publish_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk failure")),
    )
    with pytest.raises(OSError, match="disk failure"):
        observer.observe_page()
    assert observer._observations == {}
    assert observer._commits == {}
