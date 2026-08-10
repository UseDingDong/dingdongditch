"""Strict observation-budget attempt at the Monkeytype grand challenge."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from dingdongditch import (
    Action, ActionType, BrowserConfig, BrowserProfile, Locator, LocatorStrategy,
    NameMatchMode, ObservationReference, Operation, execute_operation, observe_page,
    TypingSession, TypingSessionConfig,
)
from dingdongditch.backends.playwright_backend import PlaywrightBackend


def main() -> None:
    started = time.monotonic()
    observations = []
    checkpoints = []
    report = {
        "challenge_result": "stopped_safely",
        "browser_profile": BrowserProfile.DINGDONG.value,
        "page_observations_performed": 0,
        "observation_freshness_validations": [],
        "words_navigation_verified": False,
        "typing_session_used": False,
        "fast_key_dispatch_used": False,
        "words_completed": False,
        "wpm": None, "accuracy": None, "errors": None,
        "active_typing_time_ms": 0, "recovery_events": [],
    }
    backend = PlaywrightBackend(BrowserConfig(
        headless=False, profile=BrowserProfile.DINGDONG))
    try:
        backend.start()
        initialization = execute_operation(
            Operation(
                operation_id="grand-challenge-initialize",
                url="https://monkeytype.com/",
                action=Action(type=ActionType.NAVIGATE),
                timeout_ms=60_000,
            ),
            backend=backend,
        )
        checkpoints.append({
            "checkpoint": "declared_initial_navigation",
            "passed": initialization.action_executed_successfully,
        })
        if not initialization.action_executed_successfully:
            report["stop_reason"] = "Declared initial navigation failed"
            return

        before = observe_page(backend)
        observations.append({"phase": "before_navigation", "observation_id": before.observation_id,
                             "url": before.url, "captured_at_ms": before.captured_at_ms})
        candidates = [e for e in before.interactive_elements if e["visible"] and
                      e["semantic_role"] == "button" and e["accessible_name"] == "words"]
        checkpoints.append({"checkpoint": "unique_visible_words", "passed": len(candidates) == 1,
                            "match_count": len(candidates)})
        if len(candidates) != 1:
            report["stop_reason"] = "Words was not uniquely identified by PageObservation"
            return
        target = candidates[0]
        freshness = backend.validate_observation_reference(ObservationReference(
            before.observation_id, target["element_id"],
            {"semantic_role": "button", "accessible_name": "words", "visible": True}))
        report["observation_freshness_validations"].append(freshness.to_dict())
        checkpoints.append({"checkpoint": "reference_fresh", "passed": freshness.fresh,
                            "reason": freshness.reason})
        if not freshness.fresh:
            report["stop_reason"] = f"Words reference was stale: {freshness.reason}"
            return
        ranked = target["locator_candidates"]
        if not ranked or not ranked[0]["unique"]:
            report["stop_reason"] = "highest-ranked observation locator was not unique"
            return
        value = ranked[0]["locator_value"]
        if ranked[0]["locator_type"] == "role_name":
            locator = Locator(strategy=LocatorStrategy.ROLE_NAME, role=value["role"],
                              name=value["name"], name_match=NameMatchMode.EXACT)
        elif ranked[0]["locator_type"] == "exact_text":
            locator = Locator(strategy=LocatorStrategy.EXACT_TEXT, value=value)
        else:
            report["stop_reason"] = (
                f"highest-ranked locator type is not executable: {ranked[0]['locator_type']}")
            return
        receipt = execute_operation(Operation(
            operation_id="grand-challenge-words-navigation", url=before.url,
            action=Action(type=ActionType.CLICK, locator=locator)), backend=backend)
        report["words_click_receipt"] = {
            "action_executed_successfully": receipt.action_executed_successfully,
            "verdict": receipt.verdict.value,
            "execution_status": receipt.execution_status,
            "execution_error": receipt.execution_error,
            "failure_kind": receipt.failure_kind,
            "target_resolution": receipt.target_resolution,
            "action_evidence": receipt.action_evidence,
        }
        checkpoints.append({"checkpoint": "words_click_dispatched",
                            "passed": receipt.action_executed_successfully,
                            "locator": locator.describe()})
        if not receipt.action_executed_successfully:
            report["stop_reason"] = "Words click dispatch failed"
            return

        after = observe_page(backend)
        observations.append({"phase": "after_navigation", "observation_id": after.observation_id,
                             "url": after.url, "captured_at_ms": after.captured_at_ms})
        after_words = [e for e in after.interactive_elements if e["visible"] and
                       e["semantic_role"] == "button" and e["accessible_name"] == "words"]
        semantic_proof = len(after_words) == 1 and (
            after_words[0]["selected"] is True or after_words[0]["pressed"] is True)
        before_region_signature = sorted(
            (e["semantic_role"] or "", e["accessible_name"] or "", e["visible_text"] or "")
            for e in before.interactive_elements
            if e["owning_region_id"] == target["owning_region_id"]
        )
        after_region_signature = sorted(
            (e["semantic_role"] or "", e["accessible_name"] or "", e["visible_text"] or "")
            for e in after.interactive_elements
            if len(after_words) == 1
            and e["owning_region_id"] == after_words[0]["owning_region_id"]
        )
        target_attributes_changed = len(after_words) == 1 and (
            target["useful_attributes"] != after_words[0]["useful_attributes"])
        region_transition = before_region_signature != after_region_signature
        deterministic_transition_proof = (
            len(after_words) == 1
            and target_attributes_changed
            and region_transition
            and receipt.action_executed_successfully
        )
        checkpoints.append({"checkpoint": "words_mode_semantically_selected",
                            "passed": semantic_proof,
                            "selected": after_words[0]["selected"] if len(after_words) == 1 else None,
                            "pressed": after_words[0]["pressed"] if len(after_words) == 1 else None})
        checkpoints.append({"checkpoint": "words_region_transition",
                            "passed": deterministic_transition_proof,
                            "target_attributes_changed": target_attributes_changed,
                            "owning_region_signature_changed": region_transition})
        if not (semantic_proof or deterministic_transition_proof):
            report["stop_reason"] = (
                "Fresh PageObservation shows neither semantic selection nor a deterministic "
                "target-and-owning-region transition after the Words click.")
            return
        report["words_navigation_verified"] = True

        typing_candidates = []
        for element in after.interactive_elements:
            words = (element.get("visible_text") or "").split()
            executable = next(
                (candidate for candidate in element["locator_candidates"]
                 if candidate["unique"] and candidate["locator_type"] in
                 {"test_id", "css", "exact_text", "role_name"}),
                None,
            )
            if (element["visible"] and element["focusable"] and len(words) >= 10
                    and executable is not None):
                typing_candidates.append((element, words, executable))
        typing_element = None
        if len(typing_candidates) == 1:
            typing_element, word_list, typing_candidate = typing_candidates[0]
            locator_type = typing_candidate["locator_type"]
            locator_value = typing_candidate["locator_value"]
            if locator_type == "test_id":
                typing_locator = Locator(strategy=LocatorStrategy.TEST_ID, value=locator_value)
            elif locator_type == "css":
                typing_locator = Locator(strategy=LocatorStrategy.CSS, value=locator_value)
            elif locator_type == "exact_text":
                typing_locator = Locator(strategy=LocatorStrategy.EXACT_TEXT, value=locator_value)
            else:
                typing_locator = Locator(
                    strategy=LocatorStrategy.ROLE_NAME, role=locator_value["role"],
                    name=locator_value["name"], name_match=NameMatchMode.EXACT)
            typing_context_source = "interactive_element"
        else:
            mains = [region for region in after.regions
                     if region["visible"] and region["semantic_role"] == "main"]
            interactive_labels = {
                (element.get("visible_text") or "").strip().lower()
                for element in after.interactive_elements
            }
            blocks = [(index, block) for index, block in enumerate(after.visible_text)
                      if len(mains) == 1
                      and block["owning_region_id"] == mains[0]["region_id"]
                      and re.fullmatch(r"[a-z]+", block["text"].strip())
                      and block["text"].strip().lower() not in interactive_labels]
            blocks.sort(key=lambda item: (
                item[1]["bounds_px"]["y"], item[1]["bounds_px"]["x"]))
            clusters = []
            for indexed_block in blocks:
                block = indexed_block[1]
                if not clusters or block["bounds_px"]["y"] - clusters[-1][-1][1]["bounds_px"]["y"] > 70:
                    clusters.append([indexed_block])
                else:
                    clusters[-1].append(indexed_block)
            clusters.sort(key=len, reverse=True)
            word_blocks = sorted(clusters[0], key=lambda item: item[0]) if clusters else []
            word_list = [block["text"].strip() for _, block in word_blocks]
            selected_counts = [
                int(element["visible_text"])
                for element in after.interactive_elements
                if element.get("selected") is True
                and (element.get("visible_text") or "").isdigit()
            ]
            if len(selected_counts) == 1:
                word_list = word_list[:selected_counts[0]]
            typing_locator = Locator(strategy=LocatorStrategy.CSS, value="main")
            main_count = backend.count_matches(typing_locator)
            page_context_proven = (
                len(typing_candidates) == 0 and len(mains) == 1
                and main_count == 1 and len(word_list) >= 10
                and (len(selected_counts) != 1 or len(word_list) == selected_counts[0])
                and after.focus["page_has_focus"]
                and (after.focus.get("active_dom_element") or {}).get("tag")
                    in {"input", "textarea"}
                and (after.focus.get("active_dom_element") or {}).get("editable") is True)
            checkpoints.append({"checkpoint": "page_keyboard_typing_context",
                                "passed": page_context_proven,
                                "main_region_count": len(mains),
                                "main_locator_count": main_count,
                                "word_cluster_size": len(word_list),
                                "selected_word_counts": selected_counts,
                                "page_has_focus": after.focus["page_has_focus"]})
            if not page_context_proven:
                report["stop_reason"] = (
                    "Fresh observation did not prove a unique page-level typing context.")
                return
            typing_context_source = "page_keyboard_main_region"
        checkpoints.append({"checkpoint": "unique_typing_surface",
                            "passed": len(typing_candidates) == 1 or typing_context_source == "page_keyboard_main_region",
                            "interactive_match_count": len(typing_candidates),
                            "source": typing_context_source})
        if typing_element is not None:
            typing_freshness = backend.validate_observation_reference(ObservationReference(
                after.observation_id, typing_element["element_id"],
                {"visible": True, "focusable": True}))
            report["observation_freshness_validations"].append(typing_freshness.to_dict())
            if not typing_freshness.fresh:
                report["stop_reason"] = (
                    f"Typing context reference was stale: {typing_freshness.reason}")
                return
        # The observed test advances word-by-word on the same separator used
        # between every lexical token; include it after the final observed word
        # so the final token is committed within this one session.
        typing_text = " ".join(word_list) + " "
        report["typing_context"] = {
            "element_id": typing_element["element_id"] if typing_element else None,
            "source": typing_context_source,
            "locator": typing_locator.describe(),
            "words": len(word_list),
            "characters": len(typing_text),
            "observed_words": word_list,
        }
        typing_started = time.monotonic()
        report["typing_session_used"] = True
        report["fast_key_dispatch_used"] = True
        typing_result = TypingSession(TypingSessionConfig(
            session_id="grand-challenge-typing",
            url=after.url,
            text=typing_text,
            target_locator=typing_locator,
            max_text_chunk_characters=20,
            inter_key_delay_ms=0,
        ), backend=backend).run()
        report["active_typing_time_ms"] = round((time.monotonic() - typing_started) * 1000)
        report["typing_session"] = typing_result.to_dict()
        report["typed_characters"] = typing_result.typed_characters
        checkpoints.extend(item.to_dict() for item in typing_result.receipts)
        if typing_result.status.value != "completed":
            report["stop_reason"] = (
                f"TypingSession stopped: {typing_result.failure_kind}")
            return

        results = observe_page(backend)
        observations.append({"phase": "results", "observation_id": results.observation_id,
                             "url": results.url, "captured_at_ms": results.captured_at_ms})
        text_blocks = sorted(results.visible_text,
                             key=lambda block: (block["bounds_px"]["y"], block["bounds_px"]["x"]))
        report["results_visible_text"] = [block["text"] for block in text_blocks]
        labels = {"wpm": None, "accuracy": None, "errors": None}
        aliases = {"wpm": {"wpm"}, "accuracy": {"acc", "accuracy"}, "errors": {"errors", "error"}}
        for metric, names in aliases.items():
            anchors = [block for block in text_blocks if block["text"].strip().lower() in names]
            if not anchors:
                continue
            anchor = anchors[0]
            nearby = [block for block in text_blocks if block is not anchor
                      and abs(block["bounds_px"]["x"] - anchor["bounds_px"]["x"]) < 180
                      and 0 <= block["bounds_px"]["y"] - anchor["bounds_px"]["y"] < 100]
            if nearby:
                labels[metric] = min(
                    nearby, key=lambda block: block["bounds_px"]["y"] - anchor["bounds_px"]["y"]
                )["text"]
        report.update({"wpm": labels["wpm"], "accuracy": labels["accuracy"],
                       "errors": labels["errors"]})
        results_proven = labels["wpm"] is not None and labels["accuracy"] is not None
        checkpoints.append({"checkpoint": "results_metrics_visible",
                            "passed": results_proven, **labels})
        if not results_proven:
            report["stop_reason"] = (
                "Typing dispatch completed, but fresh PageObservation did not expose "
                "both WPM and accuracy results.")
            return
        report["words_completed"] = True
        report["challenge_result"] = "completed"
    finally:
        report["page_observations_performed"] = len(observations)
        report["page_observations"] = observations
        report["checkpoints"] = checkpoints
        report["total_execution_time_ms"] = round((time.monotonic() - started) * 1000)
        path = Path("artifacts/monkeytype_grand_challenge.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        backend.stop()


if __name__ == "__main__":
    main()
