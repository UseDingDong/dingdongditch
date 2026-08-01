"""One-shot PageObservation-driven Monkeytype Words challenge."""

from __future__ import annotations

import json
from pathlib import Path

from dingdongditch import (
    Action,
    ActionType,
    BrowserConfig,
    BrowserProfile,
    Locator,
    LocatorStrategy,
    NameMatchMode,
    ObservationReference,
    Operation,
    execute_operation,
    observe_page,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


def compact(element):
    return {
        key: element.get(key)
        for key in (
            "element_id",
            "semantic_role",
            "accessible_name",
            "visible_text",
            "selected",
            "pressed",
            "bounds_px",
            "bounds_normalized",
            "owning_region_id",
            "useful_attributes",
            "locator_candidates",
        )
    }


def main() -> None:
    backend = PlaywrightBackend(
        BrowserConfig(headless=False, profile=BrowserProfile.DINGDONG)
    )
    output = Path("artifacts/monkeytype_words_challenge.json")
    report = {"status": "stopped", "reason": "not_started"}
    try:
        backend.start()
        if backend.page.url in ("", "about:blank"):
            backend.page.goto(
                "https://monkeytype.com/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            backend.page.wait_for_timeout(4_000)

        before = observe_page(backend)
        matches = [
            element
            for element in before.interactive_elements
            if element["visible"]
            and element["semantic_role"] == "button"
            and element["accessible_name"] == "words"
        ]
        report = {
            "status": "stopped",
            "before_observation_id": before.observation_id,
            "before_url": before.url,
            "words_match_count": len(matches),
        }
        if len(matches) != 1:
            report["reason"] = "PageObservation did not contain exactly one visible button named words"
            return

        target = matches[0]
        reference = ObservationReference(
            before.observation_id,
            target["element_id"],
            expected={"semantic_role": "button", "accessible_name": "words", "visible": True},
        )
        freshness = backend.validate_observation_reference(reference)
        report["freshness_validation"] = freshness.to_dict()
        report["target_before"] = compact(target)
        if not freshness.fresh:
            report["reason"] = f"observation reference rejected: {freshness.reason}"
            return

        ranked = target["locator_candidates"]
        if not ranked or not ranked[0]["unique"]:
            report["reason"] = "highest-ranked locator was absent or ambiguous"
            return
        candidate = ranked[0]
        if candidate["locator_type"] != "role_name":
            report["reason"] = f"unsupported highest-ranked locator type: {candidate['locator_type']}"
            return
        value = candidate["locator_value"]
        locator = Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role=value["role"],
            name=value["name"],
            name_match=NameMatchMode.EXACT,
        )
        receipt = execute_operation(
            Operation(
                operation_id="observation-driven-words-click",
                url=before.url,
                action=Action(type=ActionType.CLICK, locator=locator),
            ),
            backend=backend,
        )
        report["locator_used"] = locator.describe()
        report["receipt"] = {
            "action_executed_successfully": receipt.action_executed_successfully,
            "verdict": receipt.verdict.value,
            "match_count": (
                receipt.target_resolution.get("final_candidate_count")
                if isinstance(receipt.target_resolution, dict)
                else (
                    receipt.target_resolution.final_candidate_count
                    if receipt.target_resolution
                    else None
                )
            ),
        }
        if not receipt.action_executed_successfully:
            report["reason"] = "declared click operation failed"
            return

        after = observe_page(backend)
        after_matches = [
            element
            for element in after.interactive_elements
            if element["visible"]
            and element["semantic_role"] == "button"
            and element["accessible_name"] == "words"
        ]
        report["after_observation_id"] = after.observation_id
        report["after_words_match_count"] = len(after_matches)
        report["fresh_observation"] = after.captured_at_ms >= receipt.finished_at_ms
        if len(after_matches) != 1:
            report["reason"] = "fresh observation no longer uniquely identified Words"
            return
        after_target = after_matches[0]
        report["target_after"] = compact(after_target)
        report["target_class_changed"] = (
            target["useful_attributes"].get("class")
            != after_target["useful_attributes"].get("class")
        )
        report["document_fingerprint_changed"] = (
            before.freshness["fingerprint"] != after.freshness["fingerprint"]
        )
        semantically_selected = (
            after_target["selected"] is True or after_target["pressed"] is True
        )
        report["semantic_selected_evidence"] = semantically_selected
        if semantically_selected:
            report["status"] = "passed"
            report["reason"] = "fresh semantic browser state proves Words is selected"
        else:
            report["reason"] = (
                "click succeeded and fresh DOM evidence changed, but the Words control "
                "does not expose selected or pressed state; mode success cannot be proven "
                "without interpreting site styling"
            )
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        backend.stop()


if __name__ == "__main__":
    main()
