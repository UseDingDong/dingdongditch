"""Authoritative runtime capability limitations serialized in all receipts."""

RUNTIME_LIMITATIONS = (
    "playwright_bundled_chromium_firefox_webkit",
    "safari_not_supported",
    "playwright_only",
    "ordered_plans_stop_on_failure_only",
    "no_branches_loops_or_dags",
    "no_ai_planning",
    "no_autonomous_recovery",
    "no_locator_healing",
    "browser_visible_evidence_only",
    "no_external_world_truth_claims",
    "no_positional_index_selection",
    "no_arbitrary_sleep_action",
    "no_compound_wait_conditions",
    "iframe_one_level_same_page_only",
    "no_nested_iframe_path",
    "native_dialogs_host_declared_only",
    "adaptive_plan_timeout_html5_media_only",
)
