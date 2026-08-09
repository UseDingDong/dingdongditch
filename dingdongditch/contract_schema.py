"""Canonical, versioned JSON Schema definitions for public DingDongDitch data.

The executable parser remains the authority for runtime validation.  This
module is the single public schema source used by the Python API, CLI, tool
helpers, adapters, and committed schema resources.  Keeping every projection
here avoids vendor-specific plan grammars.
"""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
import json
from importlib import resources
from typing import Any

from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserEngine,
    BrowserProvider,
)
from dingdongditch.contract.dialog import DialogAction, DialogRequirement, DialogType
from dingdongditch.contract.download import (
    DownloadChecksumPolicy,
    DownloadCollisionPolicy,
    DownloadPageEffectPolicy,
    DownloadTriggerAction,
)
from dingdongditch.contract.expectation import ExpectationType
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.network import NetworkArtifactKind, NetworkUrlMatchMode
from dingdongditch.contract.operation import ActionType, KeyPressScope, LocatorStrategy
from dingdongditch.contract.page import PageTransitionPolicy
from dingdongditch.contract.page_precondition import FragmentPolicy, PageConditionType
from dingdongditch.contract.pointer import PointerOrigin
from dingdongditch.contract.screenshot import ScreenshotPolicy
from dingdongditch.contract.target import (
    AttributeOperator,
    CardinalityPolicy,
    ConstraintType,
    NameMatchMode,
)
from dingdongditch.contract.wait import LoadState, WaitConditionType
from dingdongditch.contract.authority import ProvenanceClass
from dingdongditch.contract.quorum import EvidenceSourceClass, VerificationPolicy


JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
MACHINE_CONTRACT_VERSION = "1.0.0"
MACHINE_CONTRACT_SCHEMA_ID = (
    "https://schemas.dingdongditch.dev/machine-contract/"
    f"{MACHINE_CONTRACT_VERSION}"
)


def _enum(enum_type: type[Enum]) -> dict[str, Any]:
    return {"type": "string", "enum": [member.value for member in enum_type]}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _array(items: dict[str, Any], *, min_items: int | None = None, max_items: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "array", "items": items}
    if min_items is not None:
        result["minItems"] = min_items
    if max_items is not None:
        result["maxItems"] = max_items
    return result


def _object(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
    additional: bool | dict[str, Any] = False,
    description: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required:
        result["required"] = list(required)
    if description:
        result["description"] = description
    return result


def _scoped_locator_properties() -> dict[str, Any]:
    return {
        "frame": {"$ref": "#/$defs/Locator"},
        "frame_path": _array({"$ref": "#/$defs/Locator"}, max_items=8),
    }


def _without_frame_pair(properties: dict[str, Any]) -> dict[str, Any]:
    """Prohibit the legacy one-hop field together with frame_path."""
    return {
        **_object(properties),
        "allOf": [{"not": {"required": ["frame", "frame_path"]}}],
    }


def _input_defs() -> dict[str, Any]:
    string = {"type": "string"}
    nonempty = {"type": "string", "minLength": 1}
    integer = {"type": "integer"}
    bool_ = {"type": "boolean"}
    locator_ref = {"$ref": "#/$defs/Locator"}
    scope = _scoped_locator_properties()

    constraint_base = {
        "type": _enum(ConstraintType),
        "within": locator_ref,
        "attribute_name": nonempty,
        "attribute_operator": _enum(AttributeOperator),
        "attribute_value": string,
        "visible": bool_,
        "enabled": bool_,
        "exclude_names_exact": _array(nonempty),
        "exclude_names_contains": _array(nonempty),
        "exclude_attribute_name": nonempty,
        "exclude_attribute_value": string,
        "exclude_css": nonempty,
    }
    constraints = [
        _object({"type": {"const": ConstraintType.WITHIN.value}, "within": locator_ref}, required=("type", "within")),
        _object(
            {"type": {"const": ConstraintType.ATTRIBUTE.value}, "attribute_name": nonempty, "attribute_operator": _enum(AttributeOperator), "attribute_value": string},
            required=("type", "attribute_name", "attribute_operator"),
            additional=False,
        ),
        _object({"type": {"const": ConstraintType.VISIBLE.value}, "visible": bool_}, required=("type", "visible")),
        _object({"type": {"const": ConstraintType.ENABLED.value}, "enabled": bool_}, required=("type", "enabled")),
        {
            **_object(
                {
                    "type": {"const": ConstraintType.EXCLUDE.value},
                    "exclude_names_exact": _array(nonempty),
                    "exclude_names_contains": _array(nonempty),
                    "exclude_attribute_name": nonempty,
                    "exclude_attribute_value": string,
                    "exclude_css": nonempty,
                },
                required=("type",),
            ),
            "anyOf": [
                {"required": ["exclude_names_exact"]},
                {"required": ["exclude_names_contains"]},
                {"required": ["exclude_css"]},
                {"required": ["exclude_attribute_name", "exclude_attribute_value"]},
            ],
        },
    ]
    locator = {
        "oneOf": [
            _object(
                {
                    "strategy": {"const": LocatorStrategy.ROLE_NAME.value},
                    "role": nonempty,
                    "name": nonempty,
                    "name_match": _enum(NameMatchMode),
                    "constraints": _array({"$ref": "#/$defs/TargetConstraint"}),
                },
                required=("strategy", "role", "name"),
            ),
            *[
                _object(
                    {
                        "strategy": {"const": strategy.value},
                        "value": nonempty,
                        "constraints": _array({"$ref": "#/$defs/TargetConstraint"}),
                    },
                    required=("strategy", "value"),
                )
                for strategy in (
                    LocatorStrategy.TEST_ID,
                    LocatorStrategy.PLACEHOLDER,
                    LocatorStrategy.EXACT_TEXT,
                    LocatorStrategy.CSS,
                )
            ],
        ],
    }

    target_wait_common = {"locator": locator_ref, **scope}
    wait_conditions = [
        _without_frame_pair({"type": {"const": kind.value}, **target_wait_common})
        for kind in (
            WaitConditionType.ELEMENT_VISIBLE,
            WaitConditionType.ELEMENT_HIDDEN,
            WaitConditionType.VIDEO_ENDED,
            WaitConditionType.VIDEO_PLAYING,
            WaitConditionType.VIDEO_COMPLETED_ONCE,
        )
    ]
    wait_conditions.extend(
        [
            _without_frame_pair({"type": {"const": WaitConditionType.TEXT_PRESENT.value}, **target_wait_common, "text_value": string, "text_match": _enum(TextMatchMode)}),
            _object({"type": {"const": WaitConditionType.URL_MATCHES.value}, "url_value": nonempty, "url_match": _enum(UrlMatchMode)}, required=("type", "url_value")),
            _without_frame_pair({"type": {"const": WaitConditionType.ATTRIBUTE_EQUALS.value}, **target_wait_common, "attribute_name": nonempty, "attribute_value": string}),
            _without_frame_pair({"type": {"const": WaitConditionType.VALUE_EQUALS.value}, **target_wait_common, "value": string}),
            _without_frame_pair({"type": {"const": WaitConditionType.CHECKED_EQUALS.value}, **target_wait_common, "checked": bool_}),
            _without_frame_pair({"type": {"const": WaitConditionType.SELECTED_VALUE_EQUALS.value}, **target_wait_common, "selected_value": string}),
            _without_frame_pair({"type": {"const": WaitConditionType.ELEMENT_IN_VIEWPORT.value}, **target_wait_common, "in_viewport": bool_}),
            _object({"type": {"const": WaitConditionType.LOAD_STATE.value}, "load_state": _enum(LoadState)}, required=("type", "load_state")),
        ]
    )
    for condition in wait_conditions:
        properties = condition.get("properties", {})
        if properties.get("type", {}).get("const") in {
            WaitConditionType.TEXT_PRESENT.value,
            WaitConditionType.ATTRIBUTE_EQUALS.value,
            WaitConditionType.VALUE_EQUALS.value,
            WaitConditionType.CHECKED_EQUALS.value,
            WaitConditionType.SELECTED_VALUE_EQUALS.value,
            WaitConditionType.ELEMENT_IN_VIEWPORT.value,
        }:
            condition.setdefault("required", ["type", "locator"])
        if properties.get("type", {}).get("const") == WaitConditionType.TEXT_PRESENT.value:
            condition["required"].append("text_value")
        if properties.get("type", {}).get("const") == WaitConditionType.ATTRIBUTE_EQUALS.value:
            condition["required"].extend(["attribute_name", "attribute_value"])
        if properties.get("type", {}).get("const") == WaitConditionType.VALUE_EQUALS.value:
            condition["required"].append("value")
        if properties.get("type", {}).get("const") == WaitConditionType.CHECKED_EQUALS.value:
            condition["required"].append("checked")
        if properties.get("type", {}).get("const") == WaitConditionType.SELECTED_VALUE_EQUALS.value:
            condition["required"].append("selected_value")
        if properties.get("type", {}).get("const") == WaitConditionType.ELEMENT_IN_VIEWPORT.value:
            condition["required"].append("in_viewport")
        if properties.get("type", {}).get("const") in {
            WaitConditionType.ELEMENT_VISIBLE.value,
            WaitConditionType.ELEMENT_HIDDEN.value,
            WaitConditionType.VIDEO_ENDED.value,
            WaitConditionType.VIDEO_PLAYING.value,
            WaitConditionType.VIDEO_COMPLETED_ONCE.value,
        }:
            condition["required"] = ["type", "locator"]

    expectation_target = {"locator": locator_ref, **scope}
    expectations = [
        _object({"type": {"const": ExpectationType.URL.value}, "expectation_id": string, "url_value": nonempty, "url_match": _enum(UrlMatchMode)}, required=("type", "url_value")),
        _without_frame_pair({"type": {"const": ExpectationType.ELEMENT_EXISTS.value}, "expectation_id": string, **expectation_target, "exists": bool_}),
        _without_frame_pair({"type": {"const": ExpectationType.ELEMENT_VISIBLE.value}, "expectation_id": string, **expectation_target, "visible": bool_}),
        _without_frame_pair({"type": {"const": ExpectationType.ELEMENT_IN_VIEWPORT.value}, "expectation_id": string, **expectation_target, "in_viewport": bool_}),
        _without_frame_pair({"type": {"const": ExpectationType.TEXT.value}, "expectation_id": string, **expectation_target, "text_value": string, "text_match": _enum(TextMatchMode)}),
        _without_frame_pair({"type": {"const": ExpectationType.ATTRIBUTE.value}, "expectation_id": string, **expectation_target, "attribute_name": nonempty, "attribute_value": string}),
        _object(
            {
                "type": {"const": ExpectationType.NETWORK.value},
                "expectation_id": string,
                "network_url_substring": nonempty,
                "network_method": {"type": "string", "pattern": "^[A-Z]+$"},
                "network_status": {"type": "integer", "minimum": 100, "maximum": 599},
                "network_url_match": _enum(NetworkUrlMatchMode),
                "network_request_observed": bool_,
                "network_response_observed": bool_,
                "network_max_elapsed_ms": {"type": "integer", "minimum": 0, "maximum": 300000},
            },
            required=("type", "network_url_substring"),
        ),
        _without_frame_pair({"type": {"const": ExpectationType.UPLOAD_FILE_NAMES.value}, "expectation_id": string, **expectation_target, "file_names": _array(nonempty, min_items=1)}),
        _without_frame_pair({"type": {"const": ExpectationType.UPLOAD_FILE_COUNT.value}, "expectation_id": string, **expectation_target, "file_count": {"type": "integer", "minimum": 0}}),
    ]
    for expectation in expectations:
        kind = expectation["properties"]["type"]["const"]
        if kind == ExpectationType.ELEMENT_EXISTS.value:
            expectation["required"] = ["type", "locator", "exists"]
        elif kind == ExpectationType.ELEMENT_VISIBLE.value:
            expectation["required"] = ["type", "locator", "visible"]
        elif kind == ExpectationType.ELEMENT_IN_VIEWPORT.value:
            expectation["required"] = ["type", "locator", "in_viewport"]
        elif kind == ExpectationType.TEXT.value:
            expectation["required"] = ["type", "locator", "text_value"]
        elif kind == ExpectationType.ATTRIBUTE.value:
            expectation["required"] = ["type", "locator", "attribute_name", "attribute_value"]
        elif kind == ExpectationType.UPLOAD_FILE_NAMES.value:
            expectation["required"] = ["type", "locator", "file_names"]
        elif kind == ExpectationType.UPLOAD_FILE_COUNT.value:
            expectation["required"] = ["type", "locator", "file_count"]

    action_scope = {"locator": locator_ref, **scope}
    target_actions = [
        _without_frame_pair({"type": {"const": kind.value}, **action_scope})
        for kind in (ActionType.CLICK, ActionType.HOVER, ActionType.SCROLL_TO_TARGET)
    ]
    for action in target_actions:
        action["required"] = ["type", "locator"]
    fill_base = {"type": {"const": ActionType.FILL.value}, **action_scope, "text": string, "secret_reference": {"$ref": "#/$defs/SecretReference"}, "secret_timeout_ms": {"type": "integer", "minimum": 10, "maximum": 60000}}
    actions: list[dict[str, Any]] = [
        _object({"type": {"const": ActionType.NAVIGATE.value}}, required=("type",)),
        *target_actions,
        {
            **_without_frame_pair(fill_base),
            "required": ["type", "locator"],
            "oneOf": [
                {"required": ["text"], "not": {"required": ["secret_reference"]}},
                {"required": ["secret_reference"], "not": {"required": ["text"]}},
            ],
        },
        {
            "oneOf": [
                _without_frame_pair({"type": {"const": ActionType.PRESS_KEY.value}, "key": nonempty, "key_scope": {"const": KeyPressScope.TARGET.value}, **action_scope}),
                _without_frame_pair({"type": {"const": ActionType.PRESS_KEY.value}, "key": nonempty, **action_scope}),
                _object({"type": {"const": ActionType.PRESS_KEY.value}, "key": nonempty, "key_scope": {"const": KeyPressScope.ACTIVE_PAGE.value}}, required=("type", "key", "key_scope")),
            ],
        },
        *[
            {
                **_without_frame_pair({"type": {"const": ActionType.SELECT_OPTION.value}, **action_scope, field: schema}),
                "required": ["type", "locator", field],
            }
            for field, schema in (
                ("option_value", nonempty),
                ("option_label", nonempty),
                ("option_values", _array(nonempty, min_items=1)),
            )
        ],
        {**_without_frame_pair({"type": {"const": ActionType.SET_CHECKED.value}, **action_scope, "checked": bool_}), "required": ["type", "locator", "checked"]},
        {
            "oneOf": [
                _object({"type": {"const": ActionType.POINTER_MOVE.value}, "pointer_request": {"$ref": "#/$defs/ViewportPointerRequest"}}, required=("type", "pointer_request")),
                {**_without_frame_pair({"type": {"const": ActionType.POINTER_MOVE.value}, "pointer_request": {"$ref": "#/$defs/ElementPointerRequest"}, **action_scope}), "required": ["type", "pointer_request", "locator"]},
            ],
        },
        _object({"type": {"const": ActionType.WAIT_FOR.value}, "wait_condition": {"$ref": "#/$defs/WaitCondition"}, "wait_timeout_ms": {"type": "integer", "minimum": 100, "maximum": 60000}}, required=("type", "wait_condition")),
        _object({"type": {"enum": [ActionType.SWITCH_TO_PAGE.value, ActionType.CLOSE_PAGE.value]}, "page_id": nonempty}, required=("type", "page_id")),
        _object({"type": {"const": ActionType.SWITCH_TO_OPENER.value}}, required=("type",)),
        _object({"type": {"const": ActionType.DOWNLOAD.value}, "locator": locator_ref, "download_request": {"$ref": "#/$defs/DownloadRequest"}}, required=("type", "locator", "download_request")),
        {**_without_frame_pair({"type": {"const": ActionType.UPLOAD_FILE.value}, **action_scope, "file_paths": _array(nonempty, min_items=1), "allowed_files": _array(nonempty), "allowed_roots": _array(nonempty)}), "required": ["type", "locator", "file_paths"], "anyOf": [{"required": ["allowed_files"]}, {"required": ["allowed_roots"]}]},
        {**_without_frame_pair({"type": {"const": ActionType.SELECT_COMBOBOX_OPTION.value}, **action_scope, "combobox": {"$ref": "#/$defs/ComboboxSelection"}}), "required": ["type", "locator", "combobox"]},
    ]
    # The second target-scope key variant permits omitted key_scope (target is
    # the runtime default); constrain it to avoid collision with active_page.
    actions[5]["oneOf"][0]["required"] = ["type", "key", "key_scope", "locator"]
    actions[5]["oneOf"][1]["required"] = ["type", "key", "locator"]
    actions[5]["oneOf"][1]["not"] = {"required": ["key_scope"]}

    page_conditions = [
        _object({"condition_id": nonempty, "type": {"const": PageConditionType.EXACT_URL.value}, "url_value": nonempty, "fragment_policy": _enum(FragmentPolicy)}, required=("condition_id", "type", "url_value")),
        _object({"condition_id": nonempty, "type": {"const": PageConditionType.ORIGIN_EQUALS.value}, "origin_value": nonempty}, required=("condition_id", "type", "origin_value")),
        _object({"condition_id": nonempty, "type": {"const": PageConditionType.PATH_EQUALS.value}, "path_value": {"type": "string", "pattern": "^/"}}, required=("condition_id", "type", "path_value")),
        _object({"condition_id": nonempty, "type": {"const": PageConditionType.PATH_STARTS_WITH.value}, "path_value": {"type": "string", "pattern": "^/"}}, required=("condition_id", "type", "path_value")),
        _object({"condition_id": nonempty, "type": {"const": PageConditionType.QUERY_PARAM_EQUALS.value}, "query_name": nonempty, "query_value": string}, required=("condition_id", "type", "query_name", "query_value")),
        {**_without_frame_pair({"condition_id": nonempty, "type": {"const": PageConditionType.ELEMENT_VISIBLE.value}, "locator": locator_ref, **scope}), "required": ["condition_id", "type", "locator"]},
    ]

    browser_config = _object(
        {
            "provider": _enum(BrowserProvider),
            "engine": _enum(BrowserEngine),
            # Current runtime supports only bundled Playwright engines.
            "channel": {"const": BrowserChannel.BUNDLED.value},
            "headless": bool_,
            "profile": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
            "download_policy": {"$ref": "#/$defs/DownloadPolicy"},
        }
    )
    operation_properties = {
        "operation_id": nonempty,
        "url": nonempty,
        "action": {"$ref": "#/$defs/Action"},
        "expectations": _array({"$ref": "#/$defs/Expectation"}),
        "timeout_ms": {"type": "integer", "minimum": 100},
        "freshness": _object({"max_age_ms": {"type": "integer", "minimum": 1}}),
        "require_unique_target": {"const": True},
        "locate_retry_ms": {"type": "integer", "minimum": 0},
        "cardinality": {"const": CardinalityPolicy.EXACTLY_ONE.value},
        "page_transition": {"$ref": "#/$defs/PageTransition"},
        "dialog_contract": {"$ref": "#/$defs/DialogContract"},
        "screenshot_config": {"$ref": "#/$defs/ScreenshotConfig"},
        "page_precondition": {"$ref": "#/$defs/PagePrecondition"},
        "target_preparation": _object({"dismiss_overlay_locators": _array(locator_ref)}),
        "guard": {"$ref": "#/$defs/OperationGuard"},
        "network_artifact": {"$ref": "#/$defs/NetworkArtifactRequest"},
        "webauthn": {"$ref": "#/$defs/WebAuthnParticipationRequest"},
        "provenance": _array(_enum(ProvenanceClass), max_items=16),
        "verification_quorum": {"$ref": "#/$defs/VerificationQuorum"},
    }
    execution_plan_properties = {
        "plan_id": nonempty,
        "operations": _array({"$ref": "#/$defs/Operation"}, min_items=1, max_items=256),
        "failure_policy": {"const": "stop_on_failure"},
        "browser_config": browser_config,
        "initial_plan_timeout_ms": {"type": "integer", "minimum": 100},
        "adaptive_timeout_enabled": bool_,
        "max_plan_timeout_ms": {"type": "integer", "minimum": 100},
        "screenshot_config": {"$ref": "#/$defs/ScreenshotConfig"},
        "authority_envelope": {"$ref": "#/$defs/AuthorityEnvelope"},
        "speculative_plans": _array({"$ref": "#/$defs/SpeculativePlan"}, max_items=8),
    }
    return {
        "TargetConstraint": {"oneOf": constraints},
        "Locator": locator,
        "WaitCondition": {"oneOf": wait_conditions},
        "Expectation": {"oneOf": expectations},
        "SecretReference": _object({"reference_id": {"type": "string", "minLength": 1, "maxLength": 128}}, required=("reference_id",)),
        "ViewportPointerRequest": _object({"origin": {"const": PointerOrigin.VIEWPORT.value}, "x": {"type": "number", "minimum": -1000000, "maximum": 1000000}, "y": {"type": "number", "minimum": -1000000, "maximum": 1000000}, "steps": {"type": "integer", "minimum": 1, "maximum": 1000}, "verify_position": bool_}, required=("origin", "x", "y")),
        "ElementPointerRequest": _object({"origin": {"enum": [PointerOrigin.ELEMENT_CENTER.value, PointerOrigin.ELEMENT_OFFSET.value]}, "x": {"type": "number", "minimum": -1000000, "maximum": 1000000}, "y": {"type": "number", "minimum": -1000000, "maximum": 1000000}, "steps": {"type": "integer", "minimum": 1, "maximum": 1000}, "verify_position": bool_}, required=("origin",)),
        "DownloadPolicy": _object({"max_filename_length": {"type": "integer", "minimum": 32}, "max_subdirectory_depth": {"type": "integer", "minimum": 0, "maximum": 32}, "allow_unknown_mime": bool_, "allow_extension_derived_mime": bool_}),
        "DownloadRequest": _object({"trigger_action": _enum(DownloadTriggerAction), "trigger_key": nonempty, "preferred_filename": nonempty, "destination_subdirectory": nonempty, "collision_policy": _enum(DownloadCollisionPolicy), "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 3600000}, "checksum_policy": _enum(DownloadChecksumPolicy), "minimum_bytes": {"type": "integer", "minimum": 0}, "maximum_bytes": {"type": "integer", "minimum": 0}, "allowed_extensions": _array({"type": "string", "pattern": "^\\.[A-Za-z0-9]{1,20}$"}), "allowed_mime_types": _array({"type": "string", "pattern": "^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$"}), "page_effect_policy": _enum(DownloadPageEffectPolicy), "expected_download_events": {"const": 1}, "correlation_window_ms": {"type": "integer", "minimum": 50}, "late_event_guard_ms": {"type": "integer", "minimum": 0}}),
        "ComboboxSelection": _object({"query": string, "expected_option": nonempty, "match": _enum(TextMatchMode), "clear_existing": bool_, "dropdown_timeout_ms": {"type": "integer", "minimum": 1, "maximum": 30000}}, required=("query", "expected_option")),
        "Action": {"oneOf": actions},
        "PageTransition": _object({"policy": _enum(PageTransitionPolicy), "timeout_ms": {"type": "integer", "minimum": 100}, "activate_new_page_when_allowed": bool_, "new_page_expectations": _array({"$ref": "#/$defs/NewPageExpectation"})}),
        "NewPageExpectation": {**_object({"url_value": nonempty, "url_match": _enum(UrlMatchMode), "title_value": nonempty, "title_match": _enum(TextMatchMode), "visible_locator": locator_ref}), "anyOf": [{"required": ["url_value"]}, {"required": ["title_value"]}, {"required": ["visible_locator"]}]},
        "DialogContract": _object({"requirement": _enum(DialogRequirement), "dialog_type": _enum(DialogType), "message": string, "message_contains": bool_, "action": _enum(DialogAction), "prompt_text": string, "timeout_ms": {"type": "integer", "minimum": 1}, "redact_prompt_text": bool_}),
        "DesktopRedactionRegion": _object({"region_id": nonempty, "x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0}, "width": {"type": "integer", "minimum": 1}, "height": {"type": "integer", "minimum": 1}}, required=("region_id", "x", "y", "width", "height")),
        "ScreenshotConfig": _object({"policy": _enum(ScreenshotPolicy), "full_page": bool_, "max_per_operation": {"type": "integer", "minimum": 0}, "max_per_plan": {"type": "integer", "minimum": 0}, "artifact_root": nonempty, "sensitive_selectors": _array(nonempty), "redact_password_inputs": bool_, "mandatory_redaction": bool_, "desktop_redaction_regions": _array({"$ref": "#/$defs/DesktopRedactionRegion"}), "capture_timeout_ms": {"type": "integer", "minimum": 1}}),
        "PageCondition": {"oneOf": page_conditions},
        "PagePrecondition": _object({"logic": {"const": "all"}, "conditions": _array({"$ref": "#/$defs/PageCondition"}, min_items=1, max_items=32)}, required=("conditions",)),
        "OperationGuard": {
            "oneOf": [
                _object({"when_target_absent": _object({"expectations": _array({"$ref": "#/$defs/Expectation"}, min_items=1)}, required=("expectations",))}, required=("when_target_absent",)),
                _object({"branches": _array({"$ref": "#/$defs/GuardBranch"}, min_items=1, max_items=8), "otherwise": _array({"$ref": "#/$defs/Action"}, max_items=8)}, required=("branches",)),
            ]
        },
        "GuardBranch": _object({"branch_id": nonempty, "when": _object({"expectations": _array({"$ref": "#/$defs/Expectation"}, min_items=1, max_items=8)}, required=("expectations",)), "execute": _array({"$ref": "#/$defs/Action"}, max_items=8)}, required=("branch_id", "when")),
        "NetworkArtifactRequest": _object({"kind": _enum(NetworkArtifactKind), "max_records": {"type": "integer", "minimum": 1, "maximum": 128}}),
        "WebAuthnParticipationRequest": _object({"request_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$"}, "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 60000}}, required=("request_id",)),
        "VerificationCheck": _object({"verifier_id": nonempty, "expectation_id": nonempty, "evidence_source": _enum(EvidenceSourceClass)}, required=("verifier_id", "expectation_id", "evidence_source")),
        "VerificationQuorum": _object({"policy": _enum(VerificationPolicy), "required": {"type": "integer", "minimum": 1, "maximum": 16}, "checks": _array({"$ref": "#/$defs/VerificationCheck"}, min_items=1, max_items=16)}, required=("policy", "checks")),
        "BrowserConfig": browser_config,
        "AuthorityEnvelope": _object({
            "policy_id": nonempty,
            "granted_authorities": _array(_enum(ProvenanceClass), min_items=1),
            "allowed_origins": _array(nonempty), "denied_origins": _array(nonempty),
            "allowed_action_types": _array(nonempty), "denied_action_types": _array(nonempty),
            "allowed_file_names": _array(nonempty), "allowed_secret_references": _array(nonempty),
            "max_upload_bytes": _nullable({"type": "integer", "minimum": 0}),
            "irreversible_action_types": _array(nonempty), "require_preparation_for": _array(nonempty),
            "required_authority_by_action": {"type": "object", "additionalProperties": _enum(ProvenanceClass)},
            "expires_at_ms": _nullable({"type": "integer", "minimum": 0}), "max_action_count": _nullable({"type": "integer", "minimum": 0}), "max_side_effect_count": _nullable({"type": "integer", "minimum": 0}),
            "deny_untrusted_for_irreversible": bool_, "transfer_prepared_operations": bool_, "allow_frame_actions": bool_,
        }, required=("policy_id", "granted_authorities")),
        "Operation": _object(operation_properties, required=("operation_id", "url", "action")),
        "ExecutionPlan": _object(execution_plan_properties, required=("plan_id", "operations")),
        "CanonicalExecutionPlan": _object({key: value for key, value in execution_plan_properties.items() if key != "browser_config"}, required=("plan_id", "operations")),
    }


def _output_defs() -> dict[str, Any]:
    any_object = {"type": "object", "additionalProperties": True}
    nullable_object = _nullable(any_object)
    string = {"type": "string"}
    nullable_string = _nullable(string)
    nullable_integer = _nullable({"type": "integer"})
    geometry = _object({"x": {"type": "number"}, "y": {"type": "number"}, "width": {"type": "number"}, "height": {"type": "number"}}, required=("x", "y", "width", "height"))
    return {
        "AnyObject": any_object,
        "Geometry": geometry,
        "LocatorCandidate": _object({"locator_type": string, "locator_value": {}, "confidence": {"type": "number"}, "match_count": nullable_integer, "unique": {"type": "boolean"}, "known_ambiguity": nullable_string}, required=("locator_type", "locator_value", "confidence", "unique"), additional=True),
        "ObservedElement": _object({"element_id": string, "node_continuity_token": nullable_string, "dom_tag": string, "semantic_role": nullable_string, "accessible_name": nullable_string, "visible_text": nullable_string, "input_type": nullable_string, "href": nullable_string, "placeholder": nullable_string, "current_value": nullable_string, "value_redacted": {"type": "boolean"}, "enabled": {"type": "boolean"}, "visible": {"type": "boolean"}, "editable": {"type": "boolean"}, "focusable": {"type": "boolean"}, "focused": {"type": "boolean"}, "checked": _nullable({"type": "boolean"}), "selected": _nullable({"type": "boolean"}), "selected_state_source": nullable_string, "expanded": _nullable({"type": "boolean"}), "pressed": _nullable({"type": "boolean"}), "required": {"type": "boolean"}, "readonly": {"type": "boolean"}, "bounds_px": {"$ref": "#/$defs/Geometry"}, "bounds_normalized": {"$ref": "#/$defs/Geometry"}, "center_px": _object({"x": {"type": "number"}, "y": {"type": "number"}}, required=("x", "y")), "center_normalized": _object({"x": {"type": "number"}, "y": {"type": "number"}}, required=("x", "y")), "viewport_inclusion": string, "occlusion_state": string, "owning_region_id": nullable_string, "parent_interactive_element_id": nullable_string, "useful_attributes": any_object, "locator_candidates": _array({"$ref": "#/$defs/LocatorCandidate"})}, required=("element_id", "dom_tag", "visible", "enabled", "editable", "focusable", "focused", "value_redacted"), additional=True),
        "ObservedRegion": _object({"region_id": string, "semantic_role": string, "accessible_name": nullable_string, "visible": {"type": "boolean"}, "bounds_px": {"$ref": "#/$defs/Geometry"}, "bounds_normalized": {"$ref": "#/$defs/Geometry"}, "parent_region_id": nullable_string, "child_region_ids": _array(string), "interactive_element_ids": _array(string)}, required=("region_id", "semantic_role", "visible", "bounds_px", "bounds_normalized"), additional=True),
        "ObservedTextBlock": _object({"text_block_id": string, "text_group_id": string, "text": string, "owning_region_id": nullable_string, "bounds_px": {"$ref": "#/$defs/Geometry"}, "bounds_normalized": {"$ref": "#/$defs/Geometry"}, "truncated": {"type": "boolean"}}, required=("text_block_id", "text_group_id", "text", "bounds_px", "bounds_normalized", "truncated"), additional=True),
        "Overlay": _object({"overlay_id": string, "role": string, "accessible_name": nullable_string, "bounds_px": {"$ref": "#/$defs/Geometry"}, "bounds_normalized": {"$ref": "#/$defs/Geometry"}, "blocking": {"type": "boolean"}, "contained_interactive_element_ids": _array(string), "z_index": _nullable({"type": "number"})}, required=("overlay_id", "role", "bounds_px", "bounds_normalized", "blocking"), additional=True),
        "Observation": _object({"observation_id": string, "timestamp": string, "captured_at_ms": {"type": "integer"}, "browser_profile": string, "url": string, "title": string, "viewport": any_object, "document": any_object, "focus": any_object, "overlays": _array({"$ref": "#/$defs/Overlay"}), "regions": _array({"$ref": "#/$defs/ObservedRegion"}), "visible_text": _array({"$ref": "#/$defs/ObservedTextBlock"}), "interactive_elements": _array({"$ref": "#/$defs/ObservedElement"}), "spatial_relationships": _array(any_object), "scroll_context": any_object, "freshness": any_object, "diagnostics": any_object, "transaction_id": string, "snapshot_id": string, "commit_id": string, "observation_hash": string, "provenance": _array(_enum(ProvenanceClass), min_items=1)}, required=("observation_id", "timestamp", "captured_at_ms", "browser_profile", "url", "title", "viewport", "document", "focus", "overlays", "regions", "visible_text", "interactive_elements", "spatial_relationships", "scroll_context", "freshness", "diagnostics", "transaction_id", "snapshot_id", "commit_id", "observation_hash")),
        "ObservationSummary": _object({"collected_at_ms": {"type": "integer"}, "url": nullable_string, "notes": string, "signal_ids": _array(string)}, required=("collected_at_ms",)),
        "ExpectationResult": _object({"expectation_id": string, "expectation_type": string, "expected": any_object, "observed": any_object, "result": {"enum": ["pass", "fail", "indeterminate"]}, "evidence_refs": _array(string), "evidence_timestamp_ms": nullable_integer, "explanation": string, "freshness_ok": _nullable({"type": "boolean"}), "failure_evidence": nullable_object}, required=("expectation_id", "expectation_type", "expected", "observed", "result", "evidence_refs", "explanation", "freshness_ok", "failure_evidence")),
        "EvidenceSignal": _object({"signal_id": string, "kind": string, "availability": string, "collected_at_ms": {"type": "integer"}, "payload": any_object, "notes": string}, required=("signal_id", "kind", "availability", "collected_at_ms", "payload", "notes")),
        "FreshnessEvaluation": _object({"policy_max_age_ms": {"type": "integer"}, "action_started_at_ms": nullable_integer, "verification_completed_at_ms": nullable_integer, "stale_signal_ids": _array(string), "notes": string}, required=("policy_max_age_ms", "action_started_at_ms", "verification_completed_at_ms", "stale_signal_ids", "notes")),
        "RecoveryAttempt": _object({"reason": string, "attempt_index": {"type": "integer"}, "occurred_at_ms": {"type": "integer"}, "detail": string}, required=("reason", "attempt_index", "occurred_at_ms", "detail")),
        "PreparedOperation": _object({"token": string, "session_id": string, "expires_at_ms": {"type": "integer"}, "status": {"enum": ["PREPARED", "COMMITTED", "INVALIDATED"]}, "action_type": string, "origin": string, "page_id": string, "state_fingerprint": string, "target_fingerprint": nullable_string, "operation_hash": string, "authority_policy_hash": nullable_string, "authority_decision": nullable_object, "mutation_epoch": nullable_integer, "arbitration_policy": nullable_string}, required=("token", "session_id", "expires_at_ms", "status", "action_type", "origin", "page_id", "state_fingerprint", "target_fingerprint", "operation_hash", "authority_policy_hash", "authority_decision", "mutation_epoch", "arbitration_policy")),
        "AgentHandoffCheckpoint": _object({"handoff_token": string, "session_id": string, "old_agent_id": nullable_string, "recipient_agent_id": nullable_string, "control_epoch": {"type": "integer", "minimum": 0}, "expires_at_ms": {"type": "integer"}, "selected_page_id": nullable_string, "pages": _array(any_object), "observation_checkpoint": any_object, "authority": nullable_object, "receipt_chain_head": nullable_string, "pending_preparations": _array(any_object), "runtime_capabilities": _array(string), "identity": nullable_object, "mutation": nullable_object, "mutation_epoch": nullable_integer}, required=("handoff_token", "session_id", "old_agent_id", "recipient_agent_id", "control_epoch", "expires_at_ms", "selected_page_id", "pages", "observation_checkpoint", "authority", "receipt_chain_head", "pending_preparations", "runtime_capabilities", "identity", "mutation", "mutation_epoch")),
        "AgentHandoff": _object({"session_id": string, "agent_id": string, "control_epoch": {"type": "integer", "minimum": 0}, "control_token": string, "receipt_chain_head": nullable_string, "authority": nullable_object, "identity": nullable_object}, required=("session_id", "agent_id", "control_epoch", "control_token", "receipt_chain_head", "authority", "identity")),
        "SignedPlanAuthority": _object({"version": {"const": "1.0"}, "algorithm": {"const": "ed25519"}, "plan_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "contract_version": string, "authority_envelope_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "signer_id": string, "issued_at_ms": {"type": "integer", "minimum": 0}, "expires_at_ms": {"type": "integer", "minimum": 0}, "nonce": string, "signature": {"type": "string", "minLength": 80, "maxLength": 128}, "session_scope": nullable_string, "agent_identity_id": nullable_string, "allowed_execution_count": {"type": "integer", "minimum": 1, "maximum": 1024}, "policy_version": nullable_string}, required=("version", "algorithm", "plan_hash", "contract_version", "authority_envelope_hash", "signer_id", "issued_at_ms", "expires_at_ms", "nonce", "signature", "session_scope", "agent_identity_id", "allowed_execution_count", "policy_version")),
        "IdentityKey": _object({"key_id": string, "public_key": string, "algorithm": {"const": "ed25519"}, "fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, required=("key_id", "public_key", "algorithm", "fingerprint")),
        "AgentIdentity": _object({"identity_id": string, "owner_id": string, "issuer_id": string, "created_at_ms": {"type": "integer", "minimum": 0}, "version": {"type": "integer", "minimum": 1}, "keys": _array({"$ref": "#/$defs/IdentityKey"}, min_items=1, max_items=8), "capability_references": _array(string, max_items=32), "status": {"enum": ["active", "revoked"]}}, required=("identity_id", "owner_id", "issuer_id", "created_at_ms", "version", "keys", "capability_references", "status")),
        "IdentityAssertion": _object({"version": {"const": "1.0"}, "algorithm": {"const": "ed25519"}, "identity_id": string, "identity_version": {"type": "integer", "minimum": 1}, "key_id": string, "issued_at_ms": {"type": "integer", "minimum": 0}, "expires_at_ms": {"type": "integer", "minimum": 0}, "assertion_id": string, "signature": {"type": "string", "minLength": 80, "maxLength": 128}, "controller_scope": nullable_string}, required=("version", "algorithm", "identity_id", "identity_version", "key_id", "issued_at_ms", "expires_at_ms", "assertion_id", "signature", "controller_scope")),
        "MutationEvidence": _object({"mutation_epoch": {"type": "integer", "minimum": 0}, "actor": {"enum": ["agent", "human", "external_unknown"]}, "policy": {"enum": ["fail_on_external_mutation", "require_reprepare", "human_priority"]}, "detected_at_ms": {"type": "integer", "minimum": 0}, "source": {"enum": ["browser_state", "trusted_host", "agent_dispatch"]}, "preparation_invalidated": {"type": "boolean"}}, required=("mutation_epoch", "actor", "policy", "detected_at_ms", "source", "preparation_invalidated")),
        "ReceiptChainCheckpoint": _object({"session_id": string, "chain_length": {"type": "integer", "minimum": 0}, "chain_head_hash": nullable_string, "timestamp_ms": {"type": "integer", "minimum": 0}, "chain_version": string, "runtime_version": nullable_string}, required=("session_id", "chain_length", "chain_head_hash", "timestamp_ms", "chain_version", "runtime_version")),
        "ExecutionAttestationStatement": _object({"version": {"const": "1.0"}, "plan_hash": nullable_string, "signed_plan_reference": _nullable({"type": "object", "maxProperties": 8, "additionalProperties": {"type": ["string", "integer", "boolean", "null"], "maxLength": 256}}), "session_id": string, "identity_reference": _nullable({"type": "object", "maxProperties": 8, "additionalProperties": {"type": ["string", "integer", "boolean", "null"], "maxLength": 256}}), "authority_policy_hash": nullable_string, "checkpoint": {"$ref": "#/$defs/ReceiptChainCheckpoint"}, "receipt_chain_head": nullable_string, "receipt_count": {"type": "integer", "minimum": 0}, "quorum_verdict": nullable_string, "artifact_manifest_hash": nullable_string, "runtime_version": string, "contract_version": string, "browser": _nullable({"type": "object", "maxProperties": 8, "additionalProperties": {"type": ["string", "integer", "boolean", "null"], "maxLength": 256}}), "speculation_reference": _nullable({"type": "object", "maxProperties": 4, "additionalProperties": {"type": ["string", "integer", "boolean", "null"], "maxLength": 256}}), "issued_at_ms": {"type": "integer", "minimum": 0}, "expires_at_ms": {"type": "integer", "minimum": 0}, "nonce": string, "attester_id": string, "assurance_level": {"enum": ["host_attested", "independent_attester"]}}, required=("version", "plan_hash", "signed_plan_reference", "session_id", "identity_reference", "authority_policy_hash", "checkpoint", "receipt_chain_head", "receipt_count", "quorum_verdict", "artifact_manifest_hash", "runtime_version", "contract_version", "browser", "speculation_reference", "issued_at_ms", "expires_at_ms", "nonce", "attester_id", "assurance_level")),
        "ExecutionAttestation": _object({"statement": {"$ref": "#/$defs/ExecutionAttestationStatement"}, "algorithm": {"const": "ed25519"}, "signature": string}, required=("statement", "algorithm", "signature")),
    }


def _refine_input_defs(defs: dict[str, Any]) -> None:
    """Add static conditional rules that mirror existing typed validation."""
    defs["PageTransition"]["allOf"] = [
        {
            "if": {
                "properties": {
                    "policy": {
                        "enum": [
                            PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH.value,
                            PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT.value,
                        ]
                    }
                },
                "required": ["policy"],
            },
            "then": {
                "required": ["new_page_expectations"],
                "properties": {"new_page_expectations": {"minItems": 1}},
            },
        },
        {
            "if": {
                "properties": {"activate_new_page_when_allowed": {"const": True}},
                "required": ["activate_new_page_when_allowed"],
            },
            "then": {
                "required": ["policy"],
                "properties": {
                    "policy": {"const": PageTransitionPolicy.ALLOW_SAME_OR_NEW_PAGE.value}
                },
            },
        },
    ]
    defs["DialogContract"]["allOf"] = [
        {
            "if": {
                "properties": {"requirement": {"not": {"const": DialogRequirement.FORBIDDEN.value}}},
                "required": ["requirement"],
            },
            "then": {"required": ["dialog_type"]},
        },
        {
            "if": {
                "properties": {"message_contains": {"const": True}},
                "required": ["message_contains"],
            },
            "then": {"required": ["message"]},
        },
        {
            "if": {"required": ["prompt_text"]},
            "then": {
                "required": ["dialog_type"],
                "properties": {"dialog_type": {"const": DialogType.PROMPT.value}},
            },
        },
        {
            "if": {
                "properties": {
                    "dialog_type": {"const": DialogType.PROMPT.value},
                    "action": {"const": DialogAction.ACCEPT.value},
                },
                "required": ["dialog_type", "action"],
            },
            "then": {"required": ["prompt_text"]},
        },
    ]
    defs["ScreenshotConfig"]["allOf"] = [
        {
            "if": {
                "properties": {"mandatory_redaction": {"const": True}},
                "required": ["mandatory_redaction"],
            },
            "then": {
                "anyOf": [
                    {"properties": {"redact_password_inputs": {"const": True}}, "required": ["redact_password_inputs"]},
                    {"properties": {"sensitive_selectors": {"minItems": 1}}, "required": ["sensitive_selectors"]},
                    {"properties": {"desktop_redaction_regions": {"minItems": 1}}, "required": ["desktop_redaction_regions"]},
                ]
            },
        }
    ]
    defs["ExecutionPlan"]["allOf"] = [
        {
            "if": {
                "properties": {"adaptive_timeout_enabled": {"const": True}},
                "required": ["adaptive_timeout_enabled"],
            },
            "then": {"required": ["initial_plan_timeout_ms", "max_plan_timeout_ms"]},
        },
        {
            "if": {"required": ["max_plan_timeout_ms"]},
            "then": {"required": ["initial_plan_timeout_ms"]},
        },
    ]
    defs["CanonicalExecutionPlan"]["allOf"] = deepcopy(defs["ExecutionPlan"]["allOf"])
    defs["VerificationQuorum"]["allOf"] = [
        {
            "if": {"properties": {"policy": {"const": "n_of_m"}}, "required": ["policy"]},
            "then": {"required": ["required"]},
        },
        {
            "if": {"properties": {"policy": {"const": "all"}}, "required": ["policy"]},
            "then": {"not": {"required": ["required"]}},
        },
    ]


def _refine_observation_defs(defs: dict[str, Any]) -> None:
    """Name stable observation substructures without changing capture behavior."""
    number = {"type": "number"}
    boolean = {"type": "boolean"}
    string = {"type": "string"}
    nullable_string = _nullable(string)
    defs.update(
        {
            "Viewport": _object(
                {"width": number, "height": number, "device_pixel_ratio": number},
                required=("width", "height", "device_pixel_ratio"),
                additional=True,
            ),
            "PageDocumentMetadata": _object(
                {"width": number, "height": number, "scroll_x": number, "scroll_y": number},
                required=("width", "height", "scroll_x", "scroll_y"),
                additional=True,
            ),
            "ActiveFrame": _object({"url": string, "name": nullable_string}, required=("url", "name")),
            "ActiveDomElement": _object(
                {"tag": string, "id": nullable_string, "role": nullable_string, "editable": boolean, "focusable": boolean, "visible": boolean},
                required=("tag", "id", "role", "editable", "focusable", "visible"),
            ),
            "FocusState": _object(
                {
                    "page_has_focus": boolean,
                    "focused_element_id": nullable_string,
                    "focused_element_role": nullable_string,
                    "focused_element_accessible_name": nullable_string,
                    "focused_element_editable": boolean,
                    "active_frame": {"$ref": "#/$defs/ActiveFrame"},
                    "active_dom_element": _nullable({"$ref": "#/$defs/ActiveDomElement"}),
                    "inside_dialog_or_overlay": boolean,
                },
                required=("page_has_focus", "focused_element_id", "focused_element_role", "focused_element_accessible_name", "focused_element_editable", "active_frame", "active_dom_element", "inside_dialog_or_overlay"),
                additional=True,
            ),
            "RelationshipEvidence": _object(
                {
                    "source_element_id": string,
                    "target_element_id": string,
                    "relationship_types": _array(string),
                    "horizontal_distance_px": number,
                    "vertical_distance_px": number,
                    "euclidean_distance_px": number,
                    "center_distance_px": number,
                    "overlap_percentage": number,
                },
                required=("source_element_id", "target_element_id", "relationship_types", "horizontal_distance_px", "vertical_distance_px", "euclidean_distance_px", "center_distance_px", "overlap_percentage"),
            ),
            "ScrollableContainer": _object(
                {
                    "container_id": string,
                    "bounds_px": {"$ref": "#/$defs/Geometry"},
                    "scroll_x": number,
                    "scroll_y": number,
                    "scroll_width": number,
                    "scroll_height": number,
                    "client_width": number,
                    "client_height": number,
                    "max_scroll_x": number,
                    "max_scroll_y": number,
                    "contained_region_ids": _array(string),
                    "contained_interactive_element_ids": _array(string),
                },
                required=("container_id", "bounds_px", "scroll_x", "scroll_y", "scroll_width", "scroll_height", "client_width", "client_height", "max_scroll_x", "max_scroll_y", "contained_region_ids", "contained_interactive_element_ids"),
            ),
            "ScrollContext": _object(
                {
                    "width": number,
                    "height": number,
                    "scroll_x": number,
                    "scroll_y": number,
                    "viewport_width": number,
                    "viewport_height": number,
                    "can_scroll_up": boolean,
                    "can_scroll_down": boolean,
                    "scrollable_containers": _array({"$ref": "#/$defs/ScrollableContainer"}),
                },
                required=("width", "height", "scroll_x", "scroll_y", "viewport_width", "viewport_height", "can_scroll_up", "can_scroll_down", "scrollable_containers"),
                additional=True,
            ),
            "ObservationFreshness": _object(
                {"fingerprint": string, "max_age_ms": {"type": "integer", "minimum": 1}, "page_id": string, "captured_at_ms": {"type": "integer"}},
                required=("fingerprint", "max_age_ms", "page_id", "captured_at_ms"),
                additional=True,
            ),
            "ObservationDiagnostics": _object(
                {
                    "capture_duration_ms": {"type": "integer", "minimum": 0},
                    "timing": {"type": "object", "additionalProperties": True},
                    "truncated": {"type": "object", "additionalProperties": {"type": "boolean"}},
                    "counts_before_limits": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
                    "evidence_sources": _array(string),
                    "transaction": {"type": "object", "additionalProperties": True},
                },
                required=("capture_duration_ms", "timing", "truncated", "counts_before_limits", "evidence_sources", "transaction"),
                additional=True,
            ),
        }
    )
    observation = defs["Observation"]["properties"]
    observation.update(
        {
            "viewport": {"$ref": "#/$defs/Viewport"},
            "document": {"$ref": "#/$defs/PageDocumentMetadata"},
            "focus": {"$ref": "#/$defs/FocusState"},
            "spatial_relationships": _array({"$ref": "#/$defs/RelationshipEvidence"}),
            "scroll_context": {"$ref": "#/$defs/ScrollContext"},
            "freshness": {"$ref": "#/$defs/ObservationFreshness"},
            "diagnostics": {"$ref": "#/$defs/ObservationDiagnostics"},
        }
    )


def _schema(title: str, schema_id: str, root: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "$id": f"{MACHINE_CONTRACT_SCHEMA_ID}/{schema_id}.schema.json",
        "title": title,
        **root,
        "$defs": defs,
    }


def _schemas() -> dict[str, dict[str, Any]]:
    input_defs = _input_defs()
    _refine_input_defs(input_defs)
    input_defs["SpeculativeBranch"] = _object({"branch_id": {"type": "string"}, "preconditions": _array({"$ref": "#/$defs/Expectation"}, min_items=1, max_items=8), "continuation": {"$ref": "#/$defs/Operation"}}, required=("branch_id", "preconditions", "continuation"))
    input_defs["SpeculativePlan"] = _object({"speculation_id": {"type": "string"}, "parent_operation_id": {"type": "string"}, "parent_operation": {"$ref": "#/$defs/Operation"}, "max_depth": {"const": 1}, "branches": _array({"$ref": "#/$defs/SpeculativeBranch"}, min_items=1, max_items=8)}, required=("speculation_id", "parent_operation_id", "parent_operation", "max_depth", "branches"))
    output_defs = _output_defs()
    _refine_observation_defs(output_defs)
    string = {"type": "string"}
    plan_document = _schema(
        "DingDongDitch PlanDocument",
        "plan-document",
        _object(
            {
                "schema_version": {"const": MACHINE_CONTRACT_VERSION},
                "browser": {"$ref": "#/$defs/BrowserConfig"},
                "plan": {"$ref": "#/$defs/CanonicalExecutionPlan"},
            },
            required=("schema_version", "browser", "plan"),
            description="The sole normative root for new external-agent integrations.",
        ),
        input_defs,
    )
    execution_plan = _schema(
        "DingDongDitch ExecutionPlan",
        "execution-plan",
        {"$ref": "#/$defs/ExecutionPlan"},
        input_defs,
    )
    operation = _schema(
        "DingDongDitch Operation",
        "operation",
        {"$ref": "#/$defs/Operation"},
        input_defs,
    )
    speculative_plan = _schema("DingDongDitch SpeculativePlan", "speculative-plan", {"$ref": "#/$defs/SpeculativePlan"}, input_defs)
    observation = _schema(
        "DingDongDitch PageObservation",
        "observation",
        {"$ref": "#/$defs/Observation"},
        output_defs,
    )
    execution_receipt_props = {
        "schema_version": {"const": "1.8.0"}, "operation_id": string, "verdict": {"enum": ["VERIFIED", "NOT_VERIFIED", "EXECUTION_FAILED", "INDETERMINATE"]}, "action_type": string, "target_locator": _nullable({"type": "object", "additionalProperties": True}), "target_resolution": _nullable({"type": "object", "additionalProperties": True}), "target_url": string, "started_at_ms": {"type": "integer"}, "finished_at_ms": {"type": "integer"}, "action_started_at_ms": _nullable({"type": "integer"}), "action_completed_at_ms": _nullable({"type": "integer"}), "verification_completed_at_ms": _nullable({"type": "integer"}), "execution_status": string, "execution_error": _nullable(string), "failure_kind": _nullable(string), "action_executed_successfully": {"type": "boolean"}, "action_evidence": _nullable({"type": "object", "additionalProperties": True}), "page_precondition": _nullable({"type": "object", "additionalProperties": True}), "navigation_occurred": {"type": "boolean"}, "dispatch_document_url": _nullable(string), "telemetry": _array({"type": "object", "additionalProperties": True}), "operation_timing": _nullable({"type": "object", "additionalProperties": {"type": "integer"}}), "expectation_evidence": _array({"type": "object", "additionalProperties": True}), "artifacts": _array({"type": "object", "additionalProperties": True}), "cleanup": _nullable({"type": "object", "additionalProperties": True}), "page_transition": _nullable({"type": "object", "additionalProperties": True}), "authority_decision": _nullable({"type": "object", "additionalProperties": True}), "expectations_declared": {"type": "integer", "minimum": 0}, "pre_action_observation": _nullable({"$ref": "#/$defs/ObservationSummary"}), "post_action_observation": _nullable({"$ref": "#/$defs/ObservationSummary"}), "expectation_results": _array({"$ref": "#/$defs/ExpectationResult"}), "evidence": _array({"$ref": "#/$defs/EvidenceSignal"}), "freshness": {"$ref": "#/$defs/FreshnessEvaluation"}, "recovery_attempts": _array({"$ref": "#/$defs/RecoveryAttempt"}), "limitations": _array(string), "backend_identity": string, "browser_identity": string, "browser": _nullable({"type": "object", "additionalProperties": True}), "runtime_version": string,
    }
    # Additive governance fields intentionally remain optional for legacy receipts.
    execution_receipt_props["transaction"] = _nullable({"type": "object", "additionalProperties": True})
    execution_receipt_props["quorum_verification"] = _nullable({"type": "object", "additionalProperties": True})
    execution_receipt_props["control_epoch"] = _nullable({"type": "integer", "minimum": 0})
    execution_receipt_props["receipt_chain"] = _nullable({"type": "object", "additionalProperties": True})
    execution_receipt_props["signed_plan"] = _nullable({"type": "object", "additionalProperties": True})
    execution_receipt_props["identity"] = _nullable({"type": "object", "additionalProperties": True})
    execution_receipt_props["mutation_arbitration"] = _nullable({"$ref": "#/$defs/MutationEvidence"})
    execution_receipt_props["speculation"] = _nullable({"type": "object", "additionalProperties": True})
    execution_receipt = _schema(
        "DingDongDitch ExecutionReceipt",
        "execution-receipt",
        _object(execution_receipt_props, required=tuple(key for key in execution_receipt_props if key not in {"authority_decision", "transaction", "quorum_verification", "control_epoch", "receipt_chain", "signed_plan", "identity", "mutation_arbitration", "speculation"})),
        output_defs,
    )
    step_record = _object({"step_index": {"type": "integer", "minimum": 0}, "operation_id": string, "attempted": {"type": "boolean"}, "skipped": {"type": "boolean"}, "skip_reason": _nullable(string), "operation_verdict": _nullable(string), "failure_kind": _nullable(string), "started_at_ms": _nullable({"type": "integer"}), "finished_at_ms": _nullable({"type": "integer"}), "browser_session_id": _nullable(string), "context_id": _nullable(string), "page_id": _nullable(string), "receipt": _nullable({"$ref": "#/$defs/EmbeddedExecutionReceipt"})}, required=("step_index", "operation_id", "attempted", "skipped", "skip_reason", "operation_verdict", "failure_kind", "started_at_ms", "finished_at_ms", "browser_session_id", "context_id", "page_id", "receipt"))
    plan_receipt_props = {"schema_version": {"const": "2.2.0"}, "plan_id": string, "plan_verdict": {"enum": ["VERIFIED", "NOT_VERIFIED", "EXECUTION_FAILED", "INDETERMINATE"]}, "completion_status": {"enum": ["completed", "stopped", "not_started"]}, "failure_policy": {"const": "stop_on_failure"}, "declared_step_count": {"type": "integer", "minimum": 0}, "attempted_step_count": {"type": "integer", "minimum": 0}, "verified_step_count": {"type": "integer", "minimum": 0}, "skipped_step_count": {"type": "integer", "minimum": 0}, "decisive_step_index": _nullable({"type": "integer"}), "decisive_operation_id": _nullable(string), "failure_kind": _nullable(string), "started_at_ms": {"type": "integer"}, "finished_at_ms": {"type": "integer"}, "duration_ms": {"type": "integer", "minimum": 0}, "browser": _nullable({"type": "object", "additionalProperties": True}), "backend_identity": string, "browser_session_id": _nullable(string), "context_id": _nullable(string), "page_id": _nullable(string), "steps": _array({"$ref": "#/$defs/PlanStepRecord"}), "limitations": _array(string), "runtime_version": string, "execution_error": _nullable(string), "plan": _nullable({"type": "object", "additionalProperties": True}), "plan_timing": _nullable({"type": "object", "additionalProperties": True}), "lifecycle": _nullable({"type": "object", "additionalProperties": True}), "telemetry": _array({"type": "object", "additionalProperties": True})}
    plan_defs = {**output_defs, "EmbeddedExecutionReceipt": _object(execution_receipt_props, required=tuple(key for key in execution_receipt_props if key not in {"authority_decision", "transaction", "quorum_verification", "control_epoch", "receipt_chain", "signed_plan", "identity", "mutation_arbitration", "speculation"})), "PlanStepRecord": step_record}
    plan_receipt = _schema("DingDongDitch PlanReceipt", "plan-receipt", _object(plan_receipt_props, required=tuple(plan_receipt_props)), plan_defs)
    prepared_operation = _schema("DingDongDitch PreparedOperation", "prepared-operation", {"$ref": "#/$defs/PreparedOperation"}, output_defs)
    agent_handoff_checkpoint = _schema("DingDongDitch AgentHandoffCheckpoint", "agent-handoff-checkpoint", {"$ref": "#/$defs/AgentHandoffCheckpoint"}, output_defs)
    agent_handoff = _schema("DingDongDitch AgentHandoff", "agent-handoff", {"$ref": "#/$defs/AgentHandoff"}, output_defs)
    signed_plan_authority = _schema("DingDongDitch SignedPlanAuthority", "signed-plan-authority", {"$ref": "#/$defs/SignedPlanAuthority"}, output_defs)
    agent_identity = _schema("DingDongDitch AgentIdentity", "agent-identity", {"$ref": "#/$defs/AgentIdentity"}, output_defs)
    identity_assertion = _schema("DingDongDitch IdentityAssertion", "identity-assertion", {"$ref": "#/$defs/IdentityAssertion"}, output_defs)
    mutation_evidence = _schema("DingDongDitch MutationEvidence", "mutation-evidence", {"$ref": "#/$defs/MutationEvidence"}, output_defs)
    execution_attestation = _schema("DingDongDitch ExecutionAttestation", "execution-attestation", {"$ref": "#/$defs/ExecutionAttestation"}, output_defs)
    return {"plan-document": plan_document, "execution-plan": execution_plan, "operation": operation, "speculative-plan": speculative_plan, "observation": observation, "execution-receipt": execution_receipt, "plan-receipt": plan_receipt, "prepared-operation": prepared_operation, "agent-handoff-checkpoint": agent_handoff_checkpoint, "agent-handoff": agent_handoff, "signed-plan-authority": signed_plan_authority, "agent-identity": agent_identity, "identity-assertion": identity_assertion, "mutation-evidence": mutation_evidence, "execution-attestation": execution_attestation}


def schema(name: str) -> dict[str, Any]:
    """Return a detached Draft 2020-12 public schema by stable name."""
    try:
        return deepcopy(_schemas()[name])
    except KeyError as exc:
        raise KeyError(f"unknown DingDongDitch schema: {name}") from exc


def schema_names() -> tuple[str, ...]:
    return tuple(_schemas())


def published_schema(name: str) -> dict[str, Any]:
    """Load the committed/package-distributed JSON Schema resource.

    ``schema()`` is the authoritative in-memory generation API. This helper
    exists for packaging verification and consumers that need the exact JSON
    artifact shipped in a wheel.
    """
    if name not in schema_names():
        raise KeyError(f"unknown DingDongDitch schema: {name}")
    resource = resources.files("dingdongditch").joinpath(
        "schemas", f"{name}.schema.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))
