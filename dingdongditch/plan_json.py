"""JSON adapter: plan documents -> existing typed contracts.

This module does not execute plans, plan workflows, or invent behavior. It only
deserializes host-authored JSON into BrowserConfig / ExecutionPlan / Operation
trees and rejects unknown fields fail-closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dingdongditch.contract_schema import MACHINE_CONTRACT_VERSION

from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
    BrowserProfile,
)
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    FreshnessPolicy,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
    TargetPreparation,
    TARGET_BASED_ACTIONS,
)
from dingdongditch.contract.plan import ExecutionPlan, FailurePolicy
from dingdongditch.contract.page import (
    NewPageExpectation,
    PageTransition,
    PageTransitionPolicy,
)
from dingdongditch.contract.authority import ProvenanceClass
from dingdongditch.contract.page_precondition import (
    FragmentPolicy,
    PageCondition,
    PageConditionType,
    PagePrecondition,
)
from dingdongditch.contract.dialog import DialogAction, DialogContract, DialogRequirement, DialogType
from dingdongditch.contract.target import (
    AttributeOperator,
    CardinalityPolicy,
    ConstraintType,
    NameMatchMode,
    TargetConstraint,
)
from dingdongditch.contract.wait import LoadState, WaitCondition, WaitConditionType
from dingdongditch.contract.download import (
    DownloadChecksumPolicy, DownloadCollisionPolicy, DownloadPageEffectPolicy,
    DownloadPolicy, DownloadRequest, DownloadTriggerAction,
)
from dingdongditch.contract.pointer import PointerMoveRequest, PointerOrigin
from dingdongditch.contract.screenshot import (
    DesktopRedactionRegion,
    ScreenshotConfig,
    ScreenshotPolicy,
)
from dingdongditch.contract.speculation import SpeculativeBranch, SpeculativePlan


class PlanLoadError(ValueError):
    """Structured JSON / contract load failure (before browser launch)."""

    def __init__(self, message: str, *, code: str = "invalid_plan") -> None:
        super().__init__(message)
        self.code = code


_ABS_URL_PREFIXES = ("http://", "https://", "file://", "about:")


def _reject_unknown(data: dict[str, Any], allowed: frozenset[str], *, ctx: str) -> None:
    if not isinstance(data, dict):
        raise PlanLoadError(f"{ctx}: expected object", code="invalid_type")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise PlanLoadError(
            f"{ctx}: unknown fields: {', '.join(unknown)}",
            code="unknown_field",
        )


def _require_mapping(data: Any, *, ctx: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PlanLoadError(f"{ctx}: expected object", code="invalid_type")
    return data


def _parse_enum(enum_cls: type, value: Any, *, ctx: str):
    if not isinstance(value, str):
        raise PlanLoadError(
            f"{ctx}: expected string enum value, got {type(value).__name__}",
            code="invalid_enum",
        )
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise PlanLoadError(
            f"{ctx}: invalid {enum_cls.__name__}: {value!r}",
            code="invalid_enum",
        ) from exc


def resolve_operation_url(url: str, *, plan_path: Path | None) -> str:
    """Resolve relative filesystem paths against the plan file directory.

    Absolute http(s)/file/about URLs are left unchanged. Relative paths become
    file:// URIs via Path.resolve().as_uri().
    """
    if not isinstance(url, str) or not url.strip():
        raise PlanLoadError("operation url must be a non-empty string", code="missing_field")
    if url.startswith(_ABS_URL_PREFIXES):
        return url
    if plan_path is None:
        raise PlanLoadError(
            "relative operation url requires a plan file path",
            code="invalid_url",
        )
    candidate = (plan_path.parent / url).resolve()
    if not candidate.exists():
        raise PlanLoadError(
            f"relative url path does not exist: {candidate}",
            code="invalid_url",
        )
    return candidate.as_uri()


def browser_config_from_dict(data: Any, *, ctx: str = "browser") -> BrowserConfig:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset({"provider", "engine", "channel", "headless", "profile", "download_policy"}),
        ctx=ctx,
    )
    provider = (
        _parse_enum(BrowserProvider, raw["provider"], ctx=f"{ctx}.provider")
        if "provider" in raw
        else BrowserProvider.PLAYWRIGHT
    )
    engine = (
        _parse_enum(BrowserEngine, raw["engine"], ctx=f"{ctx}.engine")
        if "engine" in raw
        else BrowserEngine.CHROMIUM
    )
    channel = (
        _parse_enum(BrowserChannel, raw["channel"], ctx=f"{ctx}.channel")
        if "channel" in raw
        else BrowserChannel.BUNDLED
    )
    headless = raw.get("headless", True)
    if not isinstance(headless, bool):
        raise PlanLoadError(f"{ctx}.headless must be a bool", code="invalid_type")
    if "profile" in raw and not isinstance(raw["profile"], str):
        raise PlanLoadError(f"{ctx}.profile must be a string", code="invalid_type")
    config = BrowserConfig(
        provider=provider,
        engine=engine,
        channel=channel,
        headless=headless,
        profile=(
            BrowserProfile(raw["profile"])
            if "profile" in raw and raw["profile"] in {p.value for p in BrowserProfile}
            else raw["profile"] if "profile" in raw and isinstance(raw["profile"], str)
            else BrowserProfile.BENCHMARK
        ),
        download_policy=(
            _download_policy_from_dict(raw["download_policy"], ctx=f"{ctx}.download_policy")
            if raw.get("download_policy") is not None else DownloadPolicy()
        ),
    )
    config.validate()
    return config


def _download_policy_from_dict(data: Any, *, ctx: str) -> DownloadPolicy:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset({
            "max_filename_length", "max_subdirectory_depth",
            "allow_unknown_mime", "allow_extension_derived_mime",
        }),
        ctx=ctx,
    )
    policy = DownloadPolicy(
        max_filename_length=raw.get("max_filename_length", 180),
        max_subdirectory_depth=raw.get("max_subdirectory_depth", 8),
        allow_unknown_mime=raw.get("allow_unknown_mime", False),
        allow_extension_derived_mime=raw.get("allow_extension_derived_mime", False),
    )
    policy.validate()
    return policy


def _download_request_from_dict(data: Any, *, ctx: str) -> DownloadRequest:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(raw, frozenset({
        "trigger_action", "trigger_key", "preferred_filename",
        "destination_subdirectory", "collision_policy", "timeout_ms",
        "checksum_policy", "minimum_bytes", "maximum_bytes",
        "allowed_extensions", "allowed_mime_types", "page_effect_policy",
        "expected_download_events",
        "correlation_window_ms", "late_event_guard_ms",
    }), ctx=ctx)
    def tuple_strings(name: str) -> tuple[str, ...]:
        value = raw.get(name, [])
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise PlanLoadError(f"{ctx}.{name} must be a list of strings", code="invalid_type")
        return tuple(value)
    request = DownloadRequest(
        trigger_action=_parse_enum(DownloadTriggerAction, raw.get("trigger_action", "click"), ctx=f"{ctx}.trigger_action"),
        trigger_key=raw.get("trigger_key"),
        preferred_filename=raw.get("preferred_filename"),
        destination_subdirectory=raw.get("destination_subdirectory"),
        collision_policy=_parse_enum(DownloadCollisionPolicy, raw.get("collision_policy", "uniquify"), ctx=f"{ctx}.collision_policy"),
        timeout_ms=raw.get("timeout_ms", 30_000),
        checksum_policy=_parse_enum(DownloadChecksumPolicy, raw.get("checksum_policy", "sha256"), ctx=f"{ctx}.checksum_policy"),
        minimum_bytes=raw.get("minimum_bytes"),
        maximum_bytes=raw.get("maximum_bytes"),
        allowed_extensions=tuple_strings("allowed_extensions"),
        allowed_mime_types=tuple_strings("allowed_mime_types"),
        page_effect_policy=_parse_enum(DownloadPageEffectPolicy, raw.get("page_effect_policy", "no_new_page"), ctx=f"{ctx}.page_effect_policy"),
        expected_download_events=raw.get("expected_download_events", 1),
        correlation_window_ms=raw.get("correlation_window_ms", 750),
        late_event_guard_ms=raw.get("late_event_guard_ms", 250),
    )
    request.validate()
    return request


def _pointer_request_from_dict(data: Any, *, ctx: str) -> PointerMoveRequest:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset({"origin", "x", "y", "steps", "verify_position"}),
        ctx=ctx,
    )
    if "origin" not in raw:
        raise PlanLoadError(f"{ctx}: missing origin", code="missing_field")
    return PointerMoveRequest(
        origin=_parse_enum(PointerOrigin, raw["origin"], ctx=f"{ctx}.origin"),
        x=raw.get("x"),
        y=raw.get("y"),
        steps=raw.get("steps", 1),
        verify_position=raw.get("verify_position", True),
    )


def _screenshot_config_from_dict(data: Any, *, ctx: str) -> ScreenshotConfig:
    """Deserialize the public screenshot contract without adding CLI-only fields."""
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "policy",
                "full_page",
                "max_per_operation",
                "max_per_plan",
                "artifact_root",
                "sensitive_selectors",
                "redact_password_inputs",
                "mandatory_redaction",
                "desktop_redaction_regions",
                "capture_timeout_ms",
            }
        ),
        ctx=ctx,
    )
    selectors = raw.get("sensitive_selectors", [])
    if not isinstance(selectors, list) or any(
        not isinstance(item, str) for item in selectors
    ):
        raise PlanLoadError(
            f"{ctx}.sensitive_selectors must be a list of strings",
            code="invalid_type",
        )
    regions_raw = raw.get("desktop_redaction_regions", [])
    if not isinstance(regions_raw, list):
        raise PlanLoadError(
            f"{ctx}.desktop_redaction_regions must be a list", code="invalid_type"
        )
    regions: list[DesktopRedactionRegion] = []
    for index, item in enumerate(regions_raw):
        region_ctx = f"{ctx}.desktop_redaction_regions[{index}]"
        region = _require_mapping(item, ctx=region_ctx)
        _reject_unknown(region, frozenset({"region_id", "x", "y", "width", "height"}), ctx=region_ctx)
        for field_name in ("region_id", "x", "y", "width", "height"):
            if field_name not in region:
                raise PlanLoadError(
                    f"{region_ctx}: missing {field_name}", code="missing_field"
                )
        regions.append(
            DesktopRedactionRegion(
                region_id=region["region_id"],
                x=region["x"],
                y=region["y"],
                width=region["width"],
                height=region["height"],
            )
        )
    config = ScreenshotConfig(
        policy=_parse_enum(
            ScreenshotPolicy,
            raw.get("policy", ScreenshotPolicy.ON_FAILURE.value),
            ctx=f"{ctx}.policy",
        ),
        full_page=raw.get("full_page", False),
        max_per_operation=raw.get("max_per_operation", 4),
        max_per_plan=raw.get("max_per_plan", 32),
        artifact_root=raw.get("artifact_root", "artifacts/evidence_screenshots"),
        sensitive_selectors=tuple(selectors),
        redact_password_inputs=raw.get("redact_password_inputs", True),
        mandatory_redaction=raw.get("mandatory_redaction", False),
        desktop_redaction_regions=tuple(regions),
        capture_timeout_ms=raw.get("capture_timeout_ms", 5_000),
    )
    try:
        config.validate()
    except ValueError as exc:
        raise PlanLoadError(f"{ctx}: {exc}", code="invalid_plan") from exc
    return config


def _locator_from_dict(data: Any, *, ctx: str) -> Locator:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "strategy",
                "value",
                "role",
                "name",
                "name_match",
                "constraints",
            }
        ),
        ctx=ctx,
    )
    if "strategy" not in raw:
        raise PlanLoadError(f"{ctx}: missing strategy", code="missing_field")
    strategy = _parse_enum(LocatorStrategy, raw["strategy"], ctx=f"{ctx}.strategy")
    name_match = None
    if "name_match" in raw and raw["name_match"] is not None:
        name_match = _parse_enum(
            NameMatchMode, raw["name_match"], ctx=f"{ctx}.name_match"
        )
    constraints: tuple[TargetConstraint, ...] = ()
    if "constraints" in raw and raw["constraints"] is not None:
        if not isinstance(raw["constraints"], list):
            raise PlanLoadError(f"{ctx}.constraints must be a list", code="invalid_type")
        constraints = tuple(
            _constraint_from_dict(item, ctx=f"{ctx}.constraints[{i}]")
            for i, item in enumerate(raw["constraints"])
        )
    return Locator(
        strategy=strategy,
        value=raw.get("value", "") or "",
        role=raw.get("role"),
        name=raw.get("name"),
        name_match=name_match,
        constraints=constraints,
    )


def _frame_path_from_dict(data: Any, *, ctx: str) -> tuple[Locator, ...]:
    if not isinstance(data, list):
        raise PlanLoadError(f"{ctx} must be a list of locators", code="invalid_type")
    return tuple(
        _locator_from_dict(item, ctx=f"{ctx}[{index}]")
        for index, item in enumerate(data)
    )


def _constraint_from_dict(data: Any, *, ctx: str) -> TargetConstraint:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "type",
                "within",
                "attribute_name",
                "attribute_operator",
                "attribute_value",
                "visible",
                "enabled",
                "exclude_names_exact",
                "exclude_names_contains",
                "exclude_attribute_name",
                "exclude_attribute_value",
                "exclude_css",
            }
        ),
        ctx=ctx,
    )
    if "type" not in raw:
        raise PlanLoadError(f"{ctx}: missing type", code="missing_field")
    ctype = _parse_enum(ConstraintType, raw["type"], ctx=f"{ctx}.type")
    within = None
    if "within" in raw and raw["within"] is not None:
        within = _locator_from_dict(raw["within"], ctx=f"{ctx}.within")
    attr_op = None
    if "attribute_operator" in raw and raw["attribute_operator"] is not None:
        attr_op = _parse_enum(
            AttributeOperator,
            raw["attribute_operator"],
            ctx=f"{ctx}.attribute_operator",
        )
    exact = raw.get("exclude_names_exact") or ()
    contains = raw.get("exclude_names_contains") or ()
    if exact is not None and not isinstance(exact, (list, tuple)):
        raise PlanLoadError(
            f"{ctx}.exclude_names_exact must be a list", code="invalid_type"
        )
    if contains is not None and not isinstance(contains, (list, tuple)):
        raise PlanLoadError(
            f"{ctx}.exclude_names_contains must be a list", code="invalid_type"
        )
    return TargetConstraint(
        type=ctype,
        within=within,
        attribute_name=raw.get("attribute_name"),
        attribute_operator=attr_op,
        attribute_value=raw.get("attribute_value"),
        visible=raw.get("visible"),
        enabled=raw.get("enabled"),
        exclude_names_exact=tuple(exact),
        exclude_names_contains=tuple(contains),
        exclude_attribute_name=raw.get("exclude_attribute_name"),
        exclude_attribute_value=raw.get("exclude_attribute_value"),
        exclude_css=raw.get("exclude_css"),
    )


def _wait_condition_from_dict(data: Any, *, ctx: str) -> WaitCondition:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "type",
                "locator",
                "text_value",
                "text_match",
                "url_value",
                "url_match",
                "attribute_name",
                "attribute_value",
                "value",
                "checked",
                "selected_value",
                "in_viewport",
                "load_state",
                "frame",
                "frame_path",
            }
        ),
        ctx=ctx,
    )
    if "type" not in raw:
        raise PlanLoadError(f"{ctx}: missing type", code="missing_field")
    wtype = _parse_enum(WaitConditionType, raw["type"], ctx=f"{ctx}.type")
    locator = None
    if "locator" in raw and raw["locator"] is not None:
        locator = _locator_from_dict(raw["locator"], ctx=f"{ctx}.locator")
    frame = None
    if "frame" in raw and raw["frame"] is not None:
        frame = _locator_from_dict(raw["frame"], ctx=f"{ctx}.frame")
    frame_path = (
        _frame_path_from_dict(raw["frame_path"], ctx=f"{ctx}.frame_path")
        if raw.get("frame_path") is not None
        else ()
    )
    text_match = TextMatchMode.CONTAINS
    if "text_match" in raw and raw["text_match"] is not None:
        text_match = _parse_enum(
            TextMatchMode, raw["text_match"], ctx=f"{ctx}.text_match"
        )
    url_match = UrlMatchMode.CONTAINS
    if "url_match" in raw and raw["url_match"] is not None:
        url_match = _parse_enum(UrlMatchMode, raw["url_match"], ctx=f"{ctx}.url_match")
    load_state = None
    if "load_state" in raw and raw["load_state"] is not None:
        load_state = _parse_enum(LoadState, raw["load_state"], ctx=f"{ctx}.load_state")
    return WaitCondition(
        type=wtype,
        locator=locator,
        text_value=raw.get("text_value"),
        text_match=text_match,
        url_value=raw.get("url_value"),
        url_match=url_match,
        attribute_name=raw.get("attribute_name"),
        attribute_value=raw.get("attribute_value"),
        value=raw.get("value"),
        checked=raw.get("checked"),
        selected_value=raw.get("selected_value"),
        in_viewport=raw.get("in_viewport"),
        load_state=load_state,
        frame=frame,
        frame_path=frame_path,
    )


def _page_transition_from_dict(data: Any, *, ctx: str) -> PageTransition:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "policy",
                "timeout_ms",
                "activate_new_page_when_allowed",
                "new_page_expectations",
            }
        ),
        ctx=ctx,
    )
    policy = _parse_enum(
        PageTransitionPolicy,
        raw.get("policy", PageTransitionPolicy.SAME_PAGE.value),
        ctx=f"{ctx}.policy",
    )
    expectations: list[NewPageExpectation] = []
    for index, item in enumerate(raw.get("new_page_expectations") or []):
        item_ctx = f"{ctx}.new_page_expectations[{index}]"
        exp = _require_mapping(item, ctx=item_ctx)
        _reject_unknown(
            exp,
            frozenset(
                {
                    "url_value",
                    "url_match",
                    "title_value",
                    "title_match",
                    "visible_locator",
                }
            ),
            ctx=item_ctx,
        )
        locator = (
            _locator_from_dict(
                exp["visible_locator"], ctx=f"{item_ctx}.visible_locator"
            )
            if exp.get("visible_locator") is not None
            else None
        )
        expectations.append(
            NewPageExpectation(
                url_value=exp.get("url_value"),
                url_match=_parse_enum(
                    UrlMatchMode,
                    exp.get("url_match", UrlMatchMode.EXACT.value),
                    ctx=f"{item_ctx}.url_match",
                ),
                title_value=exp.get("title_value"),
                title_match=_parse_enum(
                    TextMatchMode,
                    exp.get("title_match", TextMatchMode.EXACT.value),
                    ctx=f"{item_ctx}.title_match",
                ),
                visible_locator=locator,
            )
        )
    return PageTransition(
        policy=policy,
        timeout_ms=raw.get("timeout_ms", 250),
        activate_new_page_when_allowed=raw.get(
            "activate_new_page_when_allowed", False
        ),
        new_page_expectations=tuple(expectations),
    )


def _dialog_contract_from_dict(data: Any, *, ctx: str) -> DialogContract:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(raw, frozenset({"requirement", "dialog_type", "message", "message_contains", "action", "prompt_text", "timeout_ms", "redact_prompt_text"}), ctx=ctx)
    return DialogContract(
        requirement=_parse_enum(DialogRequirement, raw.get("requirement", DialogRequirement.FORBIDDEN.value), ctx=f"{ctx}.requirement"),
        dialog_type=(_parse_enum(DialogType, raw["dialog_type"], ctx=f"{ctx}.dialog_type") if raw.get("dialog_type") is not None else None),
        message=raw.get("message"),
        message_contains=bool(raw.get("message_contains", False)),
        action=_parse_enum(DialogAction, raw.get("action", DialogAction.DISMISS.value), ctx=f"{ctx}.action"),
        prompt_text=raw.get("prompt_text"),
        timeout_ms=raw.get("timeout_ms", 1_000),
        redact_prompt_text=bool(raw.get("redact_prompt_text", False)),
    )


def _action_from_dict(data: Any, *, ctx: str) -> Action:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "type",
                "locator",
                "text",
                "secret_reference",
                "secret_timeout_ms",
                "key",
                "key_scope",
                "option_value",
                "option_label",
                "option_values",
                "checked",
                "wait_condition",
                "wait_timeout_ms",
                "frame",
                "frame_path",
                "page_id",
                "download_request",
                "pointer_request",
                "file_paths",
                "allowed_files",
                "allowed_roots",
                "combobox",
            }
        ),
        ctx=ctx,
    )
    if "type" not in raw:
        raise PlanLoadError(f"{ctx}: missing type", code="missing_field")
    atype = _parse_enum(ActionType, raw["type"], ctx=f"{ctx}.type")
    locator = None
    if "locator" in raw and raw["locator"] is not None:
        locator = _locator_from_dict(raw["locator"], ctx=f"{ctx}.locator")
    frame = None
    if "frame" in raw and raw["frame"] is not None:
        frame = _locator_from_dict(raw["frame"], ctx=f"{ctx}.frame")
    frame_path = (
        _frame_path_from_dict(raw["frame_path"], ctx=f"{ctx}.frame_path")
        if raw.get("frame_path") is not None
        else ()
    )
    key_scope = None
    if "key_scope" in raw and raw["key_scope"] is not None:
        key_scope = _parse_enum(KeyPressScope, raw["key_scope"], ctx=f"{ctx}.key_scope")
    wait_condition = None
    if "wait_condition" in raw and raw["wait_condition"] is not None:
        wait_condition = _wait_condition_from_dict(
            raw["wait_condition"], ctx=f"{ctx}.wait_condition"
        )
    option_values = None
    if "option_values" in raw and raw["option_values"] is not None:
        if not isinstance(raw["option_values"], list):
            raise PlanLoadError(
                f"{ctx}.option_values must be a list", code="invalid_type"
            )
        option_values = tuple(raw["option_values"])
    secret_reference = None
    if raw.get("secret_reference") is not None:
        from dingdongditch.authentication.secrets import SecretReference

        secret_raw = _require_mapping(raw["secret_reference"], ctx=f"{ctx}.secret_reference")
        _reject_unknown(secret_raw, frozenset({"reference_id"}), ctx=f"{ctx}.secret_reference")
        if not isinstance(secret_raw.get("reference_id"), str):
            raise PlanLoadError(
                f"{ctx}.secret_reference.reference_id must be a string",
                code="invalid_type",
            )
        secret_reference = SecretReference(secret_raw["reference_id"])
    upload_authorization = None
    if atype == ActionType.UPLOAD_FILE:
        from dingdongditch.contract.upload import UploadAuthorization
        def _string_tuple(name: str) -> tuple[str, ...]:
            value = raw.get(name, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise PlanLoadError(f"{ctx}.{name} must be a list of strings", code="invalid_type")
            return tuple(value)
        upload_authorization = UploadAuthorization(
            file_paths=_string_tuple("file_paths"),
            allowed_files=_string_tuple("allowed_files"),
            allowed_roots=_string_tuple("allowed_roots"),
        )
    combobox_selection = None
    if atype == ActionType.SELECT_COMBOBOX_OPTION:
        from dingdongditch.contract.combobox import ComboboxSelection
        combo = _require_mapping(raw.get("combobox"), ctx=f"{ctx}.combobox")
        _reject_unknown(combo, frozenset({"query", "expected_option", "match", "clear_existing", "dropdown_timeout_ms"}), ctx=f"{ctx}.combobox")
        if "query" not in combo or "expected_option" not in combo:
            raise PlanLoadError(f"{ctx}.combobox: missing query or expected_option", code="missing_field")
        from dingdongditch.contract.modes import TextMatchMode
        combobox_selection = ComboboxSelection(
            query=combo["query"], expected_option=combo["expected_option"],
            match=_parse_enum(TextMatchMode, combo.get("match", "exact"), ctx=f"{ctx}.combobox.match"),
            clear_existing=combo.get("clear_existing", True),
            dropdown_timeout_ms=combo.get("dropdown_timeout_ms", 5000),
        )
    return Action(
        type=atype,
        locator=locator,
        text=raw.get("text"),
        secret_reference=secret_reference,
        secret_timeout_ms=raw.get("secret_timeout_ms", 5_000),
        key=raw.get("key"),
        key_scope=key_scope,
        option_value=raw.get("option_value"),
        option_label=raw.get("option_label"),
        option_values=option_values,
        checked=raw.get("checked"),
        wait_condition=wait_condition,
        wait_timeout_ms=raw.get("wait_timeout_ms"),
        frame=frame,
        frame_path=frame_path,
        page_id=raw.get("page_id"),
        download_request=(
            _download_request_from_dict(raw["download_request"], ctx=f"{ctx}.download_request")
            if raw.get("download_request") is not None else None
        ),
        pointer_request=(
            _pointer_request_from_dict(
                raw["pointer_request"], ctx=f"{ctx}.pointer_request"
            )
            if raw.get("pointer_request") is not None else None
        ),
        upload_authorization=upload_authorization,
        combobox_selection=combobox_selection,
    )


def _expectation_from_dict(data: Any, *, ctx: str) -> Expectation:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "type",
                "expectation_id",
                "url_value",
                "url_match",
                "locator",
                "exists",
                "visible",
                "in_viewport",
                "text_value",
                "text_match",
                "attribute_name",
                "attribute_value",
                "network_url_substring",
                "network_method",
                "network_status",
                "network_url_match",
                "network_request_observed",
                "network_response_observed",
                "network_max_elapsed_ms",
                "file_names",
                "file_count",
                "frame",
                "frame_path",
            }
        ),
        ctx=ctx,
    )
    if "type" not in raw:
        raise PlanLoadError(f"{ctx}: missing type", code="missing_field")
    etype = _parse_enum(ExpectationType, raw["type"], ctx=f"{ctx}.type")
    locator = None
    if "locator" in raw and raw["locator"] is not None:
        locator = _locator_from_dict(raw["locator"], ctx=f"{ctx}.locator")
    frame = None
    if "frame" in raw and raw["frame"] is not None:
        frame = _locator_from_dict(raw["frame"], ctx=f"{ctx}.frame")
    frame_path = (
        _frame_path_from_dict(raw["frame_path"], ctx=f"{ctx}.frame_path")
        if raw.get("frame_path") is not None
        else ()
    )
    url_match = UrlMatchMode.EXACT
    if "url_match" in raw and raw["url_match"] is not None:
        url_match = _parse_enum(UrlMatchMode, raw["url_match"], ctx=f"{ctx}.url_match")
    text_match = TextMatchMode.CONTAINS
    if "text_match" in raw and raw["text_match"] is not None:
        text_match = _parse_enum(
            TextMatchMode, raw["text_match"], ctx=f"{ctx}.text_match"
        )
    file_names = None
    if raw.get("file_names") is not None:
        if not isinstance(raw["file_names"], list) or any(
            not isinstance(item, str) for item in raw["file_names"]
        ):
            raise PlanLoadError(
                f"{ctx}.file_names must be a list of strings", code="invalid_type"
            )
        file_names = tuple(raw["file_names"])
    from dingdongditch.contract.network import NetworkUrlMatchMode

    network_url_match = _parse_enum(
        NetworkUrlMatchMode,
        raw.get("network_url_match", "contains"),
        ctx=f"{ctx}.network_url_match",
    )
    return Expectation(
        type=etype,
        expectation_id=raw.get("expectation_id", "") or "",
        url_value=raw.get("url_value"),
        url_match=url_match,
        locator=locator,
        exists=raw.get("exists"),
        visible=raw.get("visible"),
        in_viewport=raw.get("in_viewport"),
        text_value=raw.get("text_value"),
        text_match=text_match,
        attribute_name=raw.get("attribute_name"),
        attribute_value=raw.get("attribute_value"),
        network_url_substring=raw.get("network_url_substring"),
        network_method=raw.get("network_method"),
        network_status=raw.get("network_status"),
        network_url_match=network_url_match,
        network_request_observed=raw.get("network_request_observed", True),
        network_response_observed=raw.get("network_response_observed"),
        network_max_elapsed_ms=raw.get("network_max_elapsed_ms"),
        file_names=file_names,
        file_count=raw.get("file_count"),
        frame=frame,
        frame_path=frame_path,
    )


def _freshness_from_dict(data: Any, *, ctx: str) -> FreshnessPolicy:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(raw, frozenset({"max_age_ms"}), ctx=ctx)
    max_age = raw.get("max_age_ms", 5_000)
    if not isinstance(max_age, int) or isinstance(max_age, bool):
        raise PlanLoadError(f"{ctx}.max_age_ms must be an int", code="invalid_type")
    return FreshnessPolicy(max_age_ms=max_age)


def _page_condition_from_dict(data: Any, *, ctx: str) -> PageCondition:
    raw = _require_mapping(data, ctx=ctx)
    for required in ("condition_id", "type"):
        if required not in raw:
            raise PlanLoadError(f"{ctx}: missing {required}", code="missing_field")
    ctype = _parse_enum(PageConditionType, raw["type"], ctx=f"{ctx}.type")
    allowed_by_type = {
        PageConditionType.EXACT_URL: frozenset(
            {"condition_id", "type", "url_value", "fragment_policy"}
        ),
        PageConditionType.ORIGIN_EQUALS: frozenset(
            {"condition_id", "type", "origin_value"}
        ),
        PageConditionType.PATH_EQUALS: frozenset(
            {"condition_id", "type", "path_value"}
        ),
        PageConditionType.PATH_STARTS_WITH: frozenset(
            {"condition_id", "type", "path_value"}
        ),
        PageConditionType.QUERY_PARAM_EQUALS: frozenset(
            {"condition_id", "type", "query_name", "query_value"}
        ),
        PageConditionType.ELEMENT_VISIBLE: frozenset(
            {"condition_id", "type", "locator", "frame", "frame_path"}
        ),
    }
    _reject_unknown(raw, allowed_by_type[ctype], ctx=ctx)
    condition_id = raw["condition_id"]
    if not isinstance(condition_id, str):
        raise PlanLoadError(
            f"{ctx}.condition_id must be a string", code="invalid_type"
        )
    fragment_policy = FragmentPolicy.IGNORE
    if "fragment_policy" in raw:
        fragment_policy = _parse_enum(
            FragmentPolicy,
            raw["fragment_policy"],
            ctx=f"{ctx}.fragment_policy",
        )
    locator = None
    frame = None
    frame_path: tuple[Locator, ...] = ()
    if ctype == PageConditionType.ELEMENT_VISIBLE:
        if "locator" not in raw:
            raise PlanLoadError(f"{ctx}: missing locator", code="missing_field")
        locator = _locator_from_dict(raw["locator"], ctx=f"{ctx}.locator")
        if raw.get("frame") is not None:
            frame = _locator_from_dict(raw["frame"], ctx=f"{ctx}.frame")
        if raw.get("frame_path") is not None:
            frame_path = _frame_path_from_dict(
                raw["frame_path"], ctx=f"{ctx}.frame_path"
            )
    condition = PageCondition(
        condition_id=condition_id,
        type=ctype,
        url_value=raw.get("url_value"),
        fragment_policy=fragment_policy,
        origin_value=raw.get("origin_value"),
        path_value=raw.get("path_value"),
        query_name=raw.get("query_name"),
        query_value=raw.get("query_value"),
        locator=locator,
        frame=frame,
        frame_path=frame_path,
    )
    try:
        condition.validate()
    except ValueError as exc:
        raise PlanLoadError(f"{ctx}: {exc}", code="invalid_plan") from exc
    return condition


def _page_precondition_from_dict(data: Any, *, ctx: str) -> PagePrecondition:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(raw, frozenset({"logic", "conditions"}), ctx=ctx)
    if "conditions" not in raw:
        raise PlanLoadError(f"{ctx}: missing conditions", code="missing_field")
    if not isinstance(raw["conditions"], list):
        raise PlanLoadError(f"{ctx}.conditions must be a list", code="invalid_type")
    logic = raw.get("logic", "all")
    if not isinstance(logic, str):
        raise PlanLoadError(f"{ctx}.logic must be a string", code="invalid_type")
    precondition = PagePrecondition(
        logic=logic,
        conditions=tuple(
            _page_condition_from_dict(item, ctx=f"{ctx}.conditions[{index}]")
            for index, item in enumerate(raw["conditions"])
        ),
    )
    try:
        precondition.validate()
    except ValueError as exc:
        raise PlanLoadError(f"{ctx}: {exc}", code="invalid_plan") from exc
    return precondition


def operation_from_dict(
    data: Any,
    *,
    ctx: str = "operation",
    plan_path: Path | None = None,
) -> Operation:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "operation_id",
                "url",
                "action",
                "expectations",
                "timeout_ms",
                "freshness",
                "require_unique_target",
                "locate_retry_ms",
                "cardinality",
                "page_transition",
                "dialog_contract",
                "screenshot_config",
                "page_precondition",
                "target_preparation",
                "guard",
                "network_artifact",
                "webauthn",
                "provenance",
                "verification_quorum",
            }
        ),
        ctx=ctx,
    )
    for required in ("operation_id", "url", "action"):
        if required not in raw:
            raise PlanLoadError(f"{ctx}: missing {required}", code="missing_field")
    url = resolve_operation_url(raw["url"], plan_path=plan_path)
    action = _action_from_dict(raw["action"], ctx=f"{ctx}.action")
    expectations: list[Expectation] = []
    if "expectations" in raw and raw["expectations"] is not None:
        if not isinstance(raw["expectations"], list):
            raise PlanLoadError(f"{ctx}.expectations must be a list", code="invalid_type")
        expectations = [
            _expectation_from_dict(item, ctx=f"{ctx}.expectations[{i}]")
            for i, item in enumerate(raw["expectations"])
        ]
    freshness = FreshnessPolicy()
    if "freshness" in raw and raw["freshness"] is not None:
        freshness = _freshness_from_dict(raw["freshness"], ctx=f"{ctx}.freshness")
    cardinality = CardinalityPolicy.EXACTLY_ONE
    if "cardinality" in raw and raw["cardinality"] is not None:
        cardinality = _parse_enum(
            CardinalityPolicy, raw["cardinality"], ctx=f"{ctx}.cardinality"
        )
    require_unique = raw.get("require_unique_target", True)
    if not isinstance(require_unique, bool):
        raise PlanLoadError(
            f"{ctx}.require_unique_target must be a bool", code="invalid_type"
        )
    timeout_ms = raw.get("timeout_ms", 10_000)
    locate_retry_ms = raw.get("locate_retry_ms", 1_000)
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        raise PlanLoadError(f"{ctx}.timeout_ms must be an int", code="invalid_type")
    if not isinstance(locate_retry_ms, int) or isinstance(locate_retry_ms, bool):
        raise PlanLoadError(f"{ctx}.locate_retry_ms must be an int", code="invalid_type")
    target_preparation = TargetPreparation()
    if raw.get("target_preparation") is not None:
        preparation_raw = _require_mapping(
            raw["target_preparation"], ctx=f"{ctx}.target_preparation"
        )
        _reject_unknown(
            preparation_raw,
            frozenset({"dismiss_overlay_locators"}),
            ctx=f"{ctx}.target_preparation",
        )
        overlay_raw = preparation_raw.get("dismiss_overlay_locators", [])
        if not isinstance(overlay_raw, list):
            raise PlanLoadError(
                f"{ctx}.target_preparation.dismiss_overlay_locators must be a list",
                code="invalid_type",
            )
        target_preparation = TargetPreparation(
            dismiss_overlay_locators=tuple(
                _locator_from_dict(
                    item,
                    ctx=f"{ctx}.target_preparation.dismiss_overlay_locators[{index}]",
                )
                for index, item in enumerate(overlay_raw)
            )
        )
    guard = None
    provenance: tuple[ProvenanceClass, ...] = ()
    if raw.get("provenance") is not None:
        if not isinstance(raw["provenance"], list):
            raise PlanLoadError(f"{ctx}.provenance must be a list", code="invalid_type")
        provenance = tuple(
            _parse_enum(ProvenanceClass, item, ctx=f"{ctx}.provenance[{index}]")
            for index, item in enumerate(raw["provenance"])
        )
    verification_quorum = None
    if raw.get("verification_quorum") is not None:
        from dingdongditch.contract.quorum import (
            EvidenceSourceClass,
            VerificationCheck,
            VerificationPolicy,
            VerificationQuorum,
        )
        quorum_raw = _require_mapping(raw["verification_quorum"], ctx=f"{ctx}.verification_quorum")
        _reject_unknown(quorum_raw, frozenset({"policy", "required", "checks"}), ctx=f"{ctx}.verification_quorum")
        checks_raw = quorum_raw.get("checks")
        if not isinstance(checks_raw, list):
            raise PlanLoadError(f"{ctx}.verification_quorum.checks must be a list", code="invalid_type")
        checks = []
        for index, item in enumerate(checks_raw):
            check_ctx = f"{ctx}.verification_quorum.checks[{index}]"
            check_raw = _require_mapping(item, ctx=check_ctx)
            _reject_unknown(check_raw, frozenset({"verifier_id", "expectation_id", "evidence_source"}), ctx=check_ctx)
            checks.append(VerificationCheck(
                verifier_id=check_raw.get("verifier_id"),
                expectation_id=check_raw.get("expectation_id"),
                evidence_source=_parse_enum(EvidenceSourceClass, check_raw.get("evidence_source"), ctx=f"{check_ctx}.evidence_source"),
            ))
        verification_quorum = VerificationQuorum(
            policy=_parse_enum(VerificationPolicy, quorum_raw.get("policy"), ctx=f"{ctx}.verification_quorum.policy"),
            required=quorum_raw.get("required"),
            checks=tuple(checks),
        )
    network_artifact = None
    if raw.get("network_artifact") is not None:
        from dingdongditch.contract.network import (
            NetworkArtifactKind,
            NetworkArtifactRequest,
        )

        artifact_raw = _require_mapping(
            raw["network_artifact"], ctx=f"{ctx}.network_artifact"
        )
        _reject_unknown(
            artifact_raw, frozenset({"kind", "max_records"}),
            ctx=f"{ctx}.network_artifact",
        )
        network_artifact = NetworkArtifactRequest(
            kind=_parse_enum(
                NetworkArtifactKind,
                artifact_raw.get("kind", "sanitized_trace"),
                ctx=f"{ctx}.network_artifact.kind",
            ),
            max_records=artifact_raw.get("max_records", 32),
        )
    webauthn = None
    if raw.get("webauthn") is not None:
        from dingdongditch.authentication.webauthn import WebAuthnParticipationRequest

        webauthn_raw = _require_mapping(raw["webauthn"], ctx=f"{ctx}.webauthn")
        _reject_unknown(
            webauthn_raw, frozenset({"request_id", "timeout_ms"}),
            ctx=f"{ctx}.webauthn",
        )
        if not isinstance(webauthn_raw.get("request_id"), str):
            raise PlanLoadError(
                f"{ctx}.webauthn.request_id must be a string", code="invalid_type"
            )
        webauthn = WebAuthnParticipationRequest(
            request_id=webauthn_raw["request_id"],
            timeout_ms=webauthn_raw.get("timeout_ms", 30_000),
        )
    if raw.get("guard") is not None:
        from dingdongditch.contract.operation import (
            GuardBranch,
            OperationGuard,
            TargetAbsentGuard,
        )

        guard_raw = _require_mapping(raw["guard"], ctx=f"{ctx}.guard")
        _reject_unknown(
            guard_raw,
            frozenset({"when_target_absent", "branches", "otherwise"}),
            ctx=f"{ctx}.guard",
        )
        has_legacy = "when_target_absent" in guard_raw
        has_branches = "branches" in guard_raw or "otherwise" in guard_raw
        if has_legacy == has_branches:
            raise PlanLoadError(
                f"{ctx}.guard: declare exactly one of when_target_absent or branches",
                code="invalid_plan",
            )
        if has_legacy:
            absent_raw = _require_mapping(
                guard_raw["when_target_absent"],
                ctx=f"{ctx}.guard.when_target_absent",
            )
            _reject_unknown(
                absent_raw,
                frozenset({"expectations"}),
                ctx=f"{ctx}.guard.when_target_absent",
            )
            absent_expectations = absent_raw.get("expectations")
            if not isinstance(absent_expectations, list):
                raise PlanLoadError(
                    f"{ctx}.guard.when_target_absent.expectations must be a list",
                    code="invalid_type",
                )
            if not absent_expectations:
                raise PlanLoadError(
                    f"{ctx}.guard.when_target_absent.expectations must not be empty",
                    code="invalid_plan",
                )
            guard = OperationGuard(
                when_target_absent=TargetAbsentGuard(
                    expectations=tuple(
                        _expectation_from_dict(
                            item,
                            ctx=f"{ctx}.guard.when_target_absent.expectations[{index}]",
                        )
                        for index, item in enumerate(absent_expectations)
                    )
                )
            )
        else:
            branches_raw = guard_raw.get("branches")
            if not isinstance(branches_raw, list) or not branches_raw:
                raise PlanLoadError(
                    f"{ctx}.guard.branches must be a non-empty list",
                    code="invalid_plan",
                )
            branches: list[GuardBranch] = []
            for branch_index, branch_item in enumerate(branches_raw):
                branch_ctx = f"{ctx}.guard.branches[{branch_index}]"
                branch_raw = _require_mapping(branch_item, ctx=branch_ctx)
                _reject_unknown(
                    branch_raw,
                    frozenset({"branch_id", "when", "execute"}),
                    ctx=branch_ctx,
                )
                if "branch_id" not in branch_raw or "when" not in branch_raw:
                    raise PlanLoadError(
                        f"{branch_ctx}: missing branch_id or when", code="missing_field"
                    )
                when_raw = _require_mapping(branch_raw["when"], ctx=f"{branch_ctx}.when")
                _reject_unknown(
                    when_raw, frozenset({"expectations"}), ctx=f"{branch_ctx}.when"
                )
                branch_expectations = when_raw.get("expectations")
                if not isinstance(branch_expectations, list) or not branch_expectations:
                    raise PlanLoadError(
                        f"{branch_ctx}.when.expectations must be a non-empty list",
                        code="invalid_plan",
                    )
                execute_raw = branch_raw.get("execute", [])
                if not isinstance(execute_raw, list):
                    raise PlanLoadError(
                        f"{branch_ctx}.execute must be a list", code="invalid_type"
                    )
                branches.append(
                    GuardBranch(
                        branch_id=branch_raw["branch_id"],
                        when=tuple(
                            _expectation_from_dict(
                                item,
                                ctx=f"{branch_ctx}.when.expectations[{index}]",
                            )
                            for index, item in enumerate(branch_expectations)
                        ),
                        execute=tuple(
                            _action_from_dict(item, ctx=f"{branch_ctx}.execute[{index}]")
                            for index, item in enumerate(execute_raw)
                        ),
                    )
                )
            otherwise_raw = guard_raw.get("otherwise")
            if otherwise_raw is not None and not isinstance(otherwise_raw, list):
                raise PlanLoadError(
                    f"{ctx}.guard.otherwise must be a list", code="invalid_type"
                )
            guard = OperationGuard(
                branches=tuple(branches),
                otherwise=(
                    tuple(
                        _action_from_dict(item, ctx=f"{ctx}.guard.otherwise[{index}]")
                        for index, item in enumerate(otherwise_raw)
                    )
                    if otherwise_raw is not None
                    else None
                ),
            )
        if action.locator is None or action.type not in TARGET_BASED_ACTIONS:
            raise PlanLoadError(
                f"{ctx}.guard is supported only for target-based actions",
                code="invalid_plan",
            )
    return Operation(
        operation_id=raw["operation_id"],
        url=url,
        action=action,
        expectations=expectations,
        timeout_ms=timeout_ms,
        freshness=freshness,
        require_unique_target=require_unique,
        locate_retry_ms=locate_retry_ms,
        cardinality=cardinality,
        page_transition=(
            _page_transition_from_dict(
                raw["page_transition"], ctx=f"{ctx}.page_transition"
            )
            if raw.get("page_transition") is not None
            else None
        ),
        dialog_contract=(
            _dialog_contract_from_dict(raw["dialog_contract"], ctx=f"{ctx}.dialog_contract")
            if raw.get("dialog_contract") is not None else None
        ),
        screenshot_config=(
            _screenshot_config_from_dict(
                raw["screenshot_config"], ctx=f"{ctx}.screenshot_config"
            )
            if raw.get("screenshot_config") is not None
            else None
        ),
        page_precondition=(
            _page_precondition_from_dict(
                raw["page_precondition"], ctx=f"{ctx}.page_precondition"
            )
            if raw.get("page_precondition") is not None
            else None
        ),
        target_preparation=target_preparation,
        guard=guard,
        network_artifact=network_artifact,
        webauthn=webauthn,
        provenance=provenance,
        verification_quorum=verification_quorum,
    )


def _speculative_plan_from_dict(
    data: Any,
    *,
    ctx: str,
    plan_path: Path | None = None,
) -> SpeculativePlan:
    """Parse a bounded declared graph; execution still requires a parent bind."""
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset({"speculation_id", "parent_operation_id", "parent_operation", "max_depth", "branches"}),
        ctx=ctx,
    )
    required = ("speculation_id", "parent_operation_id", "max_depth", "branches")
    if any(key not in raw for key in required):
        raise PlanLoadError(f"{ctx}: missing required speculative field", code="missing_field")
    if not isinstance(raw["branches"], list):
        raise PlanLoadError(f"{ctx}.branches must be a list", code="invalid_type")
    if raw.get("parent_operation") is not None and not isinstance(raw["parent_operation"], dict):
        raise PlanLoadError(f"{ctx}.parent_operation must be an object", code="invalid_type")
    branches: list[SpeculativeBranch] = []
    for index, item in enumerate(raw["branches"]):
        branch_ctx = f"{ctx}.branches[{index}]"
        branch = _require_mapping(item, ctx=branch_ctx)
        _reject_unknown(branch, frozenset({"branch_id", "preconditions", "continuation"}), ctx=branch_ctx)
        if "branch_id" not in branch or "continuation" not in branch:
            raise PlanLoadError(f"{branch_ctx}: missing required field", code="missing_field")
        if not isinstance(branch.get("preconditions"), list):
            raise PlanLoadError(f"{branch_ctx}.preconditions must be a list", code="invalid_type")
        branches.append(SpeculativeBranch(
            branch_id=branch["branch_id"],
            preconditions=tuple(
                _expectation_from_dict(condition, ctx=f"{branch_ctx}.preconditions[{condition_index}]")
                for condition_index, condition in enumerate(branch["preconditions"])
            ),
            continuation=operation_from_dict(branch["continuation"], ctx=f"{branch_ctx}.continuation", plan_path=plan_path),
        ))
    try:
        result = SpeculativePlan(
            speculation_id=raw["speculation_id"],
            parent_operation_id=raw["parent_operation_id"],
            parent_operation=(
                operation_from_dict(raw["parent_operation"], ctx=f"{ctx}.parent_operation", plan_path=plan_path)
                if raw.get("parent_operation") is not None else None
            ),
            max_depth=raw["max_depth"],
            branches=tuple(branches),
        )
        result.validate()
        return result
    except (TypeError, ValueError) as exc:
        raise PlanLoadError(f"{ctx}: invalid speculative plan", code="invalid_plan") from exc


def _authority_envelope_from_dict(data: Any, *, ctx: str):
    from dingdongditch.contract.authority import AuthorityEnvelope, ProvenanceClass
    raw = _require_mapping(data, ctx=ctx)
    allowed = frozenset({
        "policy_id", "granted_authorities", "allowed_origins", "denied_origins",
        "allowed_action_types", "denied_action_types", "allowed_file_names",
        "allowed_secret_references", "max_upload_bytes", "irreversible_action_types",
        "require_preparation_for", "required_authority_by_action", "expires_at_ms",
        "max_action_count", "max_side_effect_count", "deny_untrusted_for_irreversible",
        "transfer_prepared_operations", "allow_frame_actions",
    })
    _reject_unknown(raw, allowed, ctx=ctx)
    if not isinstance(raw.get("policy_id"), str):
        raise PlanLoadError(f"{ctx}.policy_id must be a string", code="invalid_type")
    def strings(name: str) -> tuple[str, ...]:
        value = raw.get(name, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise PlanLoadError(f"{ctx}.{name} must be a list of strings", code="invalid_type")
        return tuple(value)
    grants_raw = raw.get("granted_authorities", [])
    if not isinstance(grants_raw, list):
        raise PlanLoadError(f"{ctx}.granted_authorities must be a list", code="invalid_type")
    required_raw = raw.get("required_authority_by_action", {})
    if not isinstance(required_raw, dict):
        raise PlanLoadError(f"{ctx}.required_authority_by_action must be an object", code="invalid_type")
    numeric_names = ("max_upload_bytes", "expires_at_ms", "max_action_count", "max_side_effect_count")
    for name in numeric_names:
        value = raw.get(name)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise PlanLoadError(f"{ctx}.{name} must be an integer", code="invalid_type")
    for name in ("deny_untrusted_for_irreversible", "transfer_prepared_operations", "allow_frame_actions"):
        if name in raw and not isinstance(raw[name], bool):
            raise PlanLoadError(f"{ctx}.{name} must be a bool", code="invalid_type")
    return AuthorityEnvelope(
        policy_id=raw["policy_id"],
        granted_authorities=tuple(_parse_enum(ProvenanceClass, item, ctx=f"{ctx}.granted_authorities[{index}]") for index, item in enumerate(grants_raw)),
        allowed_origins=strings("allowed_origins"), denied_origins=strings("denied_origins"),
        allowed_action_types=strings("allowed_action_types"), denied_action_types=strings("denied_action_types"),
        allowed_file_names=strings("allowed_file_names"), allowed_secret_references=strings("allowed_secret_references"),
        max_upload_bytes=raw.get("max_upload_bytes"), irreversible_action_types=strings("irreversible_action_types"),
        require_preparation_for=strings("require_preparation_for"),
        required_authority_by_action={key: _parse_enum(ProvenanceClass, value, ctx=f"{ctx}.required_authority_by_action.{key}") for key, value in required_raw.items()},
        expires_at_ms=raw.get("expires_at_ms"), max_action_count=raw.get("max_action_count"),
        max_side_effect_count=raw.get("max_side_effect_count"),
        deny_untrusted_for_irreversible=raw.get("deny_untrusted_for_irreversible", False),
        transfer_prepared_operations=raw.get("transfer_prepared_operations", False),
        allow_frame_actions=raw.get("allow_frame_actions", False),
    )


def execution_plan_from_dict(
    data: Any,
    *,
    browser_config: BrowserConfig | None = None,
    ctx: str = "plan",
    plan_path: Path | None = None,
) -> ExecutionPlan:
    raw = _require_mapping(data, ctx=ctx)
    _reject_unknown(
        raw,
        frozenset(
            {
                "plan_id",
                "operations",
                "failure_policy",
                "browser_config",
                "initial_plan_timeout_ms",
                "adaptive_timeout_enabled",
                "max_plan_timeout_ms",
                "screenshot_config",
                "authority_envelope",
                "speculative_plans",
            }
        ),
        ctx=ctx,
    )
    if "plan_id" not in raw:
        raise PlanLoadError(f"{ctx}: missing plan_id", code="missing_field")
    if "operations" not in raw:
        raise PlanLoadError(f"{ctx}: missing operations", code="missing_field")
    if not isinstance(raw["operations"], list):
        raise PlanLoadError(f"{ctx}.operations must be a list", code="invalid_type")

    failure_policy = FailurePolicy.STOP_ON_FAILURE
    if "failure_policy" in raw and raw["failure_policy"] is not None:
        failure_policy = _parse_enum(
            FailurePolicy, raw["failure_policy"], ctx=f"{ctx}.failure_policy"
        )

    nested_browser = browser_config
    if "browser_config" in raw and raw["browser_config"] is not None:
        nested_browser = browser_config_from_dict(
            raw["browser_config"], ctx=f"{ctx}.browser_config"
        )
    if nested_browser is None:
        nested_browser = BrowserConfig()

    operations = [
        operation_from_dict(
            item, ctx=f"{ctx}.operations[{i}]", plan_path=plan_path
        )
        for i, item in enumerate(raw["operations"])
    ]
    speculative_raw = raw.get("speculative_plans", [])
    if not isinstance(speculative_raw, list):
        raise PlanLoadError(f"{ctx}.speculative_plans must be a list", code="invalid_type")
    speculative_plans = tuple(
        _speculative_plan_from_dict(item, ctx=f"{ctx}.speculative_plans[{index}]", plan_path=plan_path)
        for index, item in enumerate(speculative_raw)
    )
    adaptive = raw.get("adaptive_timeout_enabled", False)
    if adaptive is not None and not isinstance(adaptive, bool):
        raise PlanLoadError(
            f"{ctx}.adaptive_timeout_enabled must be a bool", code="invalid_type"
        )
    initial_budget = raw.get("initial_plan_timeout_ms")
    max_budget = raw.get("max_plan_timeout_ms")
    for name, val in (
        ("initial_plan_timeout_ms", initial_budget),
        ("max_plan_timeout_ms", max_budget),
    ):
        if val is not None and (not isinstance(val, int) or isinstance(val, bool)):
            raise PlanLoadError(f"{ctx}.{name} must be an int", code="invalid_type")
    plan = ExecutionPlan(
        plan_id=raw["plan_id"],
        operations=operations,
        browser_config=nested_browser,
        failure_policy=failure_policy,
        initial_plan_timeout_ms=initial_budget,
        adaptive_timeout_enabled=bool(adaptive) if adaptive is not None else False,
        max_plan_timeout_ms=max_budget,
        screenshot_config=(
            _screenshot_config_from_dict(
                raw["screenshot_config"], ctx=f"{ctx}.screenshot_config"
            )
            if raw.get("screenshot_config") is not None
            else None
        ),
        authority_envelope=(
            _authority_envelope_from_dict(raw["authority_envelope"], ctx=f"{ctx}.authority_envelope")
            if raw.get("authority_envelope") is not None else None
        ),
        speculative_plans=speculative_plans,
    )
    plan.validate()
    return plan


def plan_document_from_dict(
    data: Any,
    *,
    plan_path: Path | None = None,
) -> ExecutionPlan:
    """Load a top-level plan document.

    Supported legacy and canonical shapes (all fail-closed on unknown fields):

    1. ``{"schema_version": "1.0.0", "browser": {...}, "plan": {...}}``
       — canonical public machine-contract document
    2. ``{"browser": {...}, "plan": {...}}`` — legacy CLI document
    3. ``{"plan_id": ..., "operations": [...], "browser_config"?: {...}}`` —
       bare ExecutionPlan object
    """
    raw = _require_mapping(data, ctx="document")
    if "schema_version" in raw:
        _reject_unknown(raw, frozenset({"schema_version", "browser", "plan"}), ctx="document")
        if raw.get("schema_version") != MACHINE_CONTRACT_VERSION:
            raise PlanLoadError(
                f"document.schema_version: unsupported machine contract version {raw.get('schema_version')!r}",
                code="unsupported_contract_version",
            )
        if "plan" not in raw:
            raise PlanLoadError("document: missing plan", code="missing_field")
        if "browser" not in raw:
            raise PlanLoadError("document: missing browser", code="missing_field")
        if not isinstance(raw["plan"], dict):
            raise PlanLoadError("document.plan: expected object", code="invalid_type")
        if "browser_config" in raw["plan"]:
            raise PlanLoadError(
                "document.plan.browser_config: canonical documents put browser configuration at document.browser",
                code="canonical_field_forbidden",
            )
        browser = browser_config_from_dict(raw["browser"], ctx="browser")
        return execution_plan_from_dict(
            raw["plan"], browser_config=browser, ctx="plan", plan_path=plan_path
        )
    if "browser" in raw or "plan" in raw:
        _reject_unknown(raw, frozenset({"browser", "plan"}), ctx="document")
        if "plan" not in raw:
            raise PlanLoadError("document: missing plan", code="missing_field")
        browser = None
        if "browser" in raw and raw["browser"] is not None:
            browser = browser_config_from_dict(raw["browser"], ctx="browser")
        return execution_plan_from_dict(
            raw["plan"],
            browser_config=browser,
            ctx="plan",
            plan_path=plan_path,
        )
    return execution_plan_from_dict(raw, ctx="plan", plan_path=plan_path)


def load_plan_json_text(
    text: str,
    *,
    plan_path: Path | None = None,
    source: str = "input",
) -> ExecutionPlan:
    """Parse a JSON text document into a validated ExecutionPlan."""
    if text.startswith("\ufeff"):
        text = text[1:]
    if not str(text).strip():
        raise PlanLoadError(f"{source}: empty JSON document", code="invalid_json")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanLoadError(
            f"invalid JSON in {source}: {exc.msg} (line {exc.lineno})",
            code="invalid_json",
        ) from exc
    return plan_document_from_dict(data, plan_path=plan_path)


def load_plan_file(path: str | Path) -> ExecutionPlan:
    """Read JSON from disk and return a validated ExecutionPlan."""
    plan_path = Path(path)
    if not plan_path.is_file():
        raise PlanLoadError(f"plan file not found: {plan_path}", code="missing_file")
    try:
        # utf-8-sig tolerates Windows BOM without changing valid UTF-8 plans.
        text = plan_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PlanLoadError(
            f"cannot read plan file: {plan_path}: {exc}", code="io_error"
        ) from exc
    return load_plan_json_text(
        text,
        plan_path=plan_path.resolve(),
        source=str(plan_path),
    )


def load_plan_stdin(stream: Any | None = None) -> ExecutionPlan:
    """Read UTF-8 JSON from stdin (or a provided text stream). No temp files."""
    import sys

    handle = stream if stream is not None else sys.stdin
    try:
        text = handle.read()
    except OSError as exc:
        raise PlanLoadError(f"cannot read stdin: {exc}", code="io_error") from exc
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8-sig")
    return load_plan_json_text(text, plan_path=None, source="stdin")


def apply_browser_overrides(
    plan: ExecutionPlan,
    *,
    engine: str | None = None,
    headless: bool | None = None,
) -> ExecutionPlan:
    """Return a new plan with CLI browser overrides applied (CLI wins)."""
    cfg = plan.browser_config
    new_engine = cfg.engine
    new_headless = cfg.headless
    if engine is not None:
        new_engine = _parse_enum(BrowserEngine, engine, ctx="--engine")
    if headless is not None:
        if not isinstance(headless, bool):
            raise PlanLoadError("--headed/--headless produced non-bool", code="invalid_type")
        new_headless = headless
    new_cfg = BrowserConfig(
        provider=cfg.provider,
        engine=new_engine,
        channel=cfg.channel,
        headless=new_headless,
        download_policy=cfg.download_policy,
        profile=cfg.profile,
    )
    new_cfg.validate()
    return ExecutionPlan(
        plan_id=plan.plan_id,
        operations=list(plan.operations),
        browser_config=new_cfg,
        failure_policy=plan.failure_policy,
        initial_plan_timeout_ms=plan.initial_plan_timeout_ms,
        adaptive_timeout_enabled=plan.adaptive_timeout_enabled,
        max_plan_timeout_ms=plan.max_plan_timeout_ms,
        screenshot_config=plan.screenshot_config,
        authority_envelope=plan.authority_envelope,
    )
