from pathlib import Path

import pytest

from dingdongditch import (
    BrowserConfig,
    Locator,
    LocatorStrategy,
    ObservationReference,
    PageObservationOptions,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.page_observer import ObservationUnstableError, PageObserver


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
        assert unrelated_change.reason == "re_resolved_with_unrelated_dom_change"
        backend.page.evaluate("document.querySelector('[data-testid=time]').remove()")
        result = backend.validate_observation_reference(
            ObservationReference(observation.observation_id, target["element_id"])
        )
        assert result.fresh is False
        assert result.reason == "element_disappeared_or_ambiguous"
    finally:
        backend.stop()


def test_transient_browser_mutations_restart_complete_observation(monkeypatch):
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.goto(FIXTURE.resolve().as_uri())
        observer = PageObserver(backend)
        original = observer._verify_locator_candidates
        original_capture = observer._capture_once
        remaining = {"count": 2}
        attempt = {"inject": False, "injected": False}

        def mutate_after_attestation(candidates):
            original(candidates)
            if attempt["inject"] and not attempt["injected"]:
                attempt["injected"] = True
                backend.page.evaluate(
                    "document.body.appendChild(document.createElement('i'))"
                )

        def capture(options):
            attempt["inject"] = remaining["count"] > 0
            attempt["injected"] = False
            if attempt["inject"]:
                remaining["count"] -= 1
            return original_capture(options)

        monkeypatch.setattr(
            observer, "_verify_locator_candidates", mutate_after_attestation
        )
        monkeypatch.setattr(observer, "_capture_once", capture)
        observation = observer.observe_page(PageObservationOptions(
            observation_budget_ms=5_000,
            mutation_quiescence_ms=25,
        ))
        assert observation.diagnostics["transaction"]["attempts"] == 3
        assert len(
            observation.diagnostics["transaction"]["discarded_attempts"]
        ) == 2
        assert len(observer._observations) == 1
    finally:
        backend.stop()


def test_continuous_browser_dom_churn_fails_safely():
    backend = PlaywrightBackend(BrowserConfig(headless=True))
    try:
        backend.start()
        backend.page.goto(FIXTURE.resolve().as_uri())
        backend.page.evaluate(
            """() => {
              const node=document.createElement('i');
              document.body.appendChild(node);
              window.__observationChurn=setInterval(() => {
                node.textContent=String(Number(node.textContent || '0') + 1);
              }, 5);
            }"""
        )
        observer = PageObserver(backend)
        with pytest.raises(ObservationUnstableError) as caught:
            observer.observe_page(PageObservationOptions(
                observation_budget_ms=750,
                mutation_quiescence_ms=50,
            ))
        assert caught.value.evidence["reason"] in {
            "dom_never_reached_quiescence",
            "observation_budget_exhausted",
        }
        assert observer._observations == {}
    finally:
        if backend.is_started:
            backend.page.evaluate("clearInterval(window.__observationChurn)")
        backend.stop()
