from pathlib import Path

import pytest

from dingdongditch import (
    BrowserConfig,
    BrowserEngine,
    Locator,
    LocatorStrategy,
    ObservationReference,
    PageObservationOptions,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.page_observer import PageObserver


FIXTURE = Path(__file__).parents[1] / "fixtures" / "page_observation_app.html"


def test_precise_page_observation_contract():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.goto(FIXTURE.resolve().as_uri())
        observation = backend.observe_page()
        by_name = {e["accessible_name"]: e for e in observation.interactive_elements}

        assert {"Time", "Words", "Typing input", "Disabled", "Password"} <= by_name.keys()
        assert "Hidden" not in by_name
        assert by_name["Time"]["pressed"] is True
        assert by_name["Words"]["pressed"] is False
        assert by_name["Disabled"]["enabled"] is False
        assert by_name["Typing input"]["focused"] is True
        assert by_name["Password"]["current_value"] == "[REDACTED]"
        assert by_name["Current tab"]["selected"] is True
        assert by_name["Other tab"]["selected"] is False
        assert by_name["Custom active"]["selected"] is True
        assert by_name["Custom active"]["selected_state_source"] == "class_state_token"
        assert by_name["Time"]["bounds_normalized"]["x"] >= 0
        assert by_name["Time"]["locator_candidates"][0]["locator_type"] == "test_id"
        assert backend.count_matches(
            Locator(strategy=LocatorStrategy.EXACT_TEXT, value="Words")
        ) == 1
        duplicates = [e for e in observation.interactive_elements if e["accessible_name"] == "Duplicate"]
        assert duplicates[0]["locator_candidates"][0]["unique"] is False
        roles = {r["semantic_role"] for r in observation.regions}
        assert {"header", "main", "footer", "dialog"} <= roles
        assert observation.overlays[0]["role"] == "dialog"
        assert observation.scroll_context["scrollable_containers"]
        assert any(
            rel["source_element_id"] == by_name["Time"]["element_id"]
            and rel["target_element_id"] == by_name["Words"]["element_id"]
            and "same_row_as" in rel["relationship_types"]
            for rel in observation.spatial_relationships
        )
    finally:
        backend.stop()


def test_unique_placeholder_candidate_is_directly_executable():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.set_content('<textarea placeholder="Ask anything"></textarea>')
        observation = backend.observe_page()
        prompt = next(
            e for e in observation.interactive_elements
            if e["placeholder"] == "Ask anything"
        )
        candidate = next(
            c for c in prompt["locator_candidates"]
            if c["locator_type"] == "placeholder"
        )
        assert candidate["unique"] is True
        assert backend.count_matches(
            Locator(
                strategy=LocatorStrategy.PLACEHOLDER,
                value="Ask anything",
            )
        ) == 1
        freshness = backend.validate_observation_reference(
            ObservationReference(
                observation.observation_id,
                prompt["element_id"],
                {"visible": True, "enabled": True},
            )
        )
        assert freshness.fresh is True
        assert freshness.commit_id == observation.commit_id
        assert freshness.observation_hash == observation.observation_hash
    finally:
        backend.stop()


def test_truncation_and_dynamic_staleness():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.goto(FIXTURE.resolve().as_uri())
        observation = backend.observe_page(PageObservationOptions(max_interactive_elements=2))
        assert len(observation.interactive_elements) == 2
        assert observation.diagnostics["truncated"]["interactive_elements"] is True

        target = next(e for e in observation.interactive_elements if e["accessible_name"] == "Time")
        fresh = backend.validate_observation_reference(
            ObservationReference(
                observation.observation_id,
                target["element_id"],
                {"visible": True, "semantic_role": "button", "accessible_name": "Time"},
            )
        )
        assert fresh.fresh is True
        backend.page.evaluate(
            "document.body.appendChild(document.createElement('div'))"
        )
        unrelated_change = backend.validate_observation_reference(
            ObservationReference(
                observation.observation_id,
                target["element_id"],
                {"visible": True, "semantic_role": "button", "accessible_name": "Time"},
            )
        )
        assert unrelated_change.fresh is True
        assert unrelated_change.reason == "same_node_with_unrelated_dom_change"
        backend.page.evaluate("document.querySelector('[data-testid=time]').remove()")
        result = backend.validate_observation_reference(
            ObservationReference(observation.observation_id, target["element_id"])
        )
        assert result.fresh is False
        assert result.reason == "element_disappeared_or_ambiguous"
    finally:
        backend.stop()


@pytest.mark.parametrize(
    "engine",
    [BrowserEngine.CHROMIUM, BrowserEngine.FIREFOX, BrowserEngine.WEBKIT],
)
def test_replaced_equivalent_element_is_not_fresh(engine):
    backend = PlaywrightBackend(BrowserConfig(headless=True, engine=engine))
    try:
        backend.start()
        backend.page.set_content(
            '<button data-testid="stable" aria-label="Continue">Continue</button>'
        )
        observation = backend.observe_page()
        target = observation.interactive_elements[0]
        backend.page.evaluate("""() => {
            const old = document.querySelector('[data-testid=stable]');
            const replacement = old.cloneNode(true);
            old.replaceWith(replacement);
        }""")
        result = backend.validate_observation_reference(
            ObservationReference(observation.observation_id, target["element_id"])
        )
        assert result.fresh is False
        assert result.reason == "element_replaced"
    finally:
        backend.stop()


def test_observation_waits_for_quiescence_and_publishes_timing_evidence():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.set_content('<button>Stable</button>')
        started = __import__("time").monotonic()
        observation = backend.observe_page(
            PageObservationOptions(
                mutation_quiescence_ms=75,
                observation_budget_ms=2_000,
            )
        )
        elapsed_ms = (__import__("time").monotonic() - started) * 1_000
        assert elapsed_ms >= 60
        assert observation.diagnostics["timing"] == {
            "observation_budget_ms": 2_000,
            "mutation_quiescence_ms": 75,
            "quiescence_enforced": True,
            "budget_enforced_before_publication": True,
        }
    finally:
        backend.stop()


def test_continuous_mutation_exhausts_budget_without_commit():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.set_content('<button>Busy</button>')
        backend.page.evaluate("""() => {
            window.__mutationTimer = setInterval(() => {
                document.body.dataset.tick = String(Date.now());
            }, 10);
        }""")
        with pytest.raises(Exception, match="observation_budget_exceeded"):
            backend.observe_page(
                PageObservationOptions(
                    mutation_quiescence_ms=80,
                    observation_budget_ms=200,
                )
            )
        observer = backend._page_observer
        assert observer._observations == {}
        assert observer._commits == {}
        transaction = next(iter(observer._transactions.values()))
        assert transaction.state.value == "aborted"
    finally:
        if backend.is_started:
            backend.page.evaluate("clearInterval(window.__mutationTimer)")
        backend.stop()


def test_v2_observation_commit_does_not_run_locator_attestation(monkeypatch):
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.goto(FIXTURE.resolve().as_uri())
        observer = PageObserver(backend)
        monkeypatch.setattr(
            observer, "_verify_locator_candidates",
            lambda candidates: (_ for _ in ()).throw(
                AssertionError("attestation entered observation transaction")
            ),
        )
        observation = observer.observe_page()
        assert observation.diagnostics["transaction"]["state"] == "committed"
        assert observation.diagnostics["transaction"]["locator_attestation_boundary"] == "independent"
        assert len(observer._observations) == 1
    finally:
        backend.stop()


def test_v2_independent_attestation_and_evidence_view():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.goto(FIXTURE.resolve().as_uri())
        observation = backend.observe_page()
        before = observation.to_dict()
        attestations = backend.attest_observation_locators(
            observation.observation_id
        )
        view = backend.observation_evidence_view(observation.observation_id)
        assert attestations
        assert view.attestations == attestations
        assert view.commit.observation_hash == observation.observation_hash
        assert observation.to_dict() == before
        assert any(record.unique for record in attestations)
        assert any(not record.unique for record in attestations)
    finally:
        backend.stop()


def test_within_region_attestation_is_browser_scoped_to_owning_region():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.set_content("""
            <main aria-label="First"><button>Go</button></main>
            <section aria-label="Second"><button>Go</button></section>
        """)
        observation = backend.observe_page()
        records = backend.attest_observation_locators(observation.observation_id)
        global_role = [item for item in records if item.locator_type == "role_name"]
        scoped_role = [item for item in records if item.locator_type == "within_region"]
        assert global_role and all(item.match_count == 2 for item in global_role)
        assert scoped_role and all(item.match_count == 1 for item in scoped_role)
        assert all(item.unique for item in scoped_role)
    finally:
        backend.stop()
