"""Public machine-readable contract facade for external planners.

This module deliberately owns no model client, prompt, API key, or browser
loop.  It exposes the existing deterministic contracts as versioned JSON
schemas, public parsing/serialization helpers, and safe validation errors.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from dingdongditch.contract.browser import BrowserConfig
from dingdongditch.contract.plan import (
    CompletionStatus,
    ExecutionPlan,
    PlanReceipt,
    PlanStepRecord,
    PlanVerdict,
)
from dingdongditch.contract.receipt import ExecutionReceipt, RECEIPT_SCHEMA_VERSION
from dingdongditch.contract.verdict import Verdict
from dingdongditch.contract_schema import (
    MACHINE_CONTRACT_VERSION,
    published_schema,
    schema,
    schema_names,
)
from dingdongditch.evidence.models import (
    EvidenceSignal,
    ExpectationResult,
    FreshnessEvaluation,
    ObservationSummary,
    RecoveryAttempt,
    SignalAvailability,
    SignalKind,
)
from dingdongditch.plan_json import (
    PlanLoadError,
    operation_from_dict,
    plan_document_from_dict,
)


@dataclass(frozen=True)
class ValidationIssue:
    """One bounded, safe machine-readable static-contract validation issue."""

    code: str
    pointer: str
    message: str
    expected: str | None = None
    observed_type: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "pointer": self.pointer,
            "message": self.message,
            "expected": self.expected,
            "observed_type": self.observed_type,
        }


class ContractValidationError(ValueError):
    """Public aggregate validation error for generated plan documents.

    Runtime/browser semantics deliberately remain outside this error surface.
    The parser is still called after structural checks, so unknown fields stay
    fail-closed even when a host did not run JSON Schema validation itself.
    """

    def __init__(self, errors: list[ValidationIssue]) -> None:
        self.errors = tuple(errors)
        super().__init__(errors[0].message if errors else "invalid machine contract")

    @property
    def schema_version(self) -> str:
        return MACHINE_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_schema_version": MACHINE_CONTRACT_VERSION,
            "errors": [error.to_dict() for error in self.errors],
        }


@dataclass(frozen=True)
class PlanDocument:
    """Canonical external-agent document: version + browser + execution plan."""

    schema_version: str
    browser: BrowserConfig
    plan: ExecutionPlan

    def to_dict(self) -> dict[str, Any]:
        return serialize_plan_document(self)


def plan_document_schema() -> dict[str, Any]:
    return schema("plan-document")


def execution_schema() -> dict[str, Any]:
    """Alias for the canonical PlanDocument schema used by generic planners."""
    return plan_document_schema()


def execution_plan_schema() -> dict[str, Any]:
    return schema("execution-plan")


def operation_schema() -> dict[str, Any]:
    return schema("operation")


def observation_schema() -> dict[str, Any]:
    return schema("observation")


def execution_receipt_schema() -> dict[str, Any]:
    return schema("execution-receipt")


def plan_receipt_schema() -> dict[str, Any]:
    return schema("plan-receipt")


def public_schema_names() -> tuple[str, ...]:
    return schema_names()


def published_schema_resource(name: str) -> dict[str, Any]:
    """Load the exact JSON Schema file installed with the package."""
    return published_schema(name)


def execution_plan_tool() -> dict[str, Any]:
    """Return a vendor-neutral tool declaration for emitting a PlanDocument.

    This is data only.  Supplying it to a model, interpreting a tool call, and
    deciding whether to execute a parsed plan remain wholly host-owned.
    """
    return {
        "name": "execute_browser_plan",
        "description": (
            "Emit one validated DingDongDitch PlanDocument for deterministic "
            "browser execution. The runtime will not infer missing actions, "
            "targets, waits, or expected outcomes."
        ),
        "input_schema": execution_schema(),
    }


def _to_pointer(context: str | None) -> str:
    if not context or context in {"document", "input"}:
        return ""
    parts: list[str] = []
    for token in re.finditer(r"([^.[\]]+)|\[([0-9]+)\]", context):
        value = token.group(1) if token.group(1) is not None else token.group(2)
        if value:
            parts.append(value.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(parts) if parts else ""


def _value_at_pointer(value: Any, pointer: str) -> Any:
    current = value
    for segment in pointer.lstrip("/").split("/"):
        if not segment:
            continue
        segment = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            current = current.get(segment)
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            return None
    return current


def _safe_type(value: Any, pointer: str) -> str | None:
    # Never echo a secret/path value.  Only type labels are exposed.
    if any(token in pointer.lower() for token in ("secret", "file_path", "allowed_file", "allowed_root")):
        return None
    return type(value).__name__ if value is not None else None


def _issue_from_exception(exc: Exception, payload: Any) -> ValidationIssue:
    message = str(exc)
    context = message.split(":", 1)[0] if ":" in message else ""
    pointer = _to_pointer(context)
    code = getattr(exc, "code", None) or getattr(
        getattr(exc, "failure_kind", None), "value", None
    ) or "invalid_contract"
    observed = _value_at_pointer(payload, pointer)
    expected = {
        "invalid_type": "the documented JSON type",
        "missing_field": "a required field",
        "unknown_field": "a documented field only",
        "invalid_enum": "one documented enum value",
        "invalid_json": "a JSON object",
    }.get(str(code))
    return ValidationIssue(
        code=str(code),
        pointer=pointer,
        message=message,
        expected=expected,
        observed_type=_safe_type(observed, pointer),
    )


def _coerce_payload(payload: Mapping[str, Any] | str | bytes | bytearray) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, (str, bytes, bytearray)):
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ContractValidationError(
                [ValidationIssue("invalid_json", "", "payload must be valid JSON", "JSON object")]
            ) from exc
        if isinstance(value, Mapping):
            return value
    raise ContractValidationError(
        [ValidationIssue("invalid_type", "", "payload must be an object", "object", type(payload).__name__)]
    )


def _canonical_root_errors(raw: Mapping[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    allowed = {"schema_version", "browser", "plan"}
    for key in sorted(set(raw) - allowed):
        issues.append(
            ValidationIssue(
                "unknown_field", f"/{key}", f"document: unknown field {key!r}", "a documented field only"
            )
        )
    for key in ("schema_version", "browser", "plan"):
        if key not in raw:
            issues.append(
                ValidationIssue("missing_field", f"/{key}", f"document: missing {key}", "a required field")
            )
    if "schema_version" in raw:
        actual = raw["schema_version"]
        if actual != MACHINE_CONTRACT_VERSION:
            issues.append(
                ValidationIssue(
                    "unsupported_contract_version",
                    "/schema_version",
                    f"unsupported machine contract version: {actual!r}",
                    MACHINE_CONTRACT_VERSION,
                    _safe_type(actual, "/schema_version"),
                )
            )
    if "browser" in raw and not isinstance(raw["browser"], Mapping):
        issues.append(ValidationIssue("invalid_type", "/browser", "browser must be an object", "object", type(raw["browser"]).__name__))
    if "plan" in raw and not isinstance(raw["plan"], Mapping):
        issues.append(ValidationIssue("invalid_type", "/plan", "plan must be an object", "object", type(raw["plan"]).__name__))
    if isinstance(raw.get("plan"), Mapping) and "browser_config" in raw["plan"]:
        issues.append(
            ValidationIssue(
                "canonical_field_forbidden",
                "/plan/browser_config",
                "canonical PlanDocument puts browser configuration at /browser",
                "omit plan.browser_config and use /browser",
            )
        )
    return issues


def parse_plan_document(
    payload: Mapping[str, Any] | str | bytes | bytearray,
    *,
    plan_path: str | Path | None = None,
) -> PlanDocument:
    """Parse the sole normative external-agent PlanDocument representation."""
    raw = _coerce_payload(payload)
    root_errors = _canonical_root_errors(raw)
    if root_errors:
        raise ContractValidationError(root_errors)
    try:
        plan = plan_document_from_dict(
            {"browser": dict(raw["browser"]), "plan": dict(raw["plan"])},
            plan_path=Path(plan_path).resolve() if plan_path is not None else None,
        )
    except (PlanLoadError, ValueError) as exc:
        raise ContractValidationError([_issue_from_exception(exc, raw)]) from exc
    return PlanDocument(
        schema_version=MACHINE_CONTRACT_VERSION,
        browser=plan.browser_config,
        plan=plan,
    )


def parse_execution_plan(
    payload: Mapping[str, Any] | str | bytes | bytearray,
    *,
    plan_path: str | Path | None = None,
) -> ExecutionPlan:
    """Parse canonical PlanDocument input or a supported legacy plan shape.

    New integrations should call :func:`parse_plan_document`; accepting legacy
    input here preserves current users without making it normative.
    """
    raw = _coerce_payload(payload)
    if "schema_version" in raw:
        return parse_plan_document(raw, plan_path=plan_path).plan
    try:
        return plan_document_from_dict(
            raw, plan_path=Path(plan_path).resolve() if plan_path is not None else None
        )
    except (PlanLoadError, ValueError) as exc:
        raise ContractValidationError([_issue_from_exception(exc, raw)]) from exc


def parse_operation(payload: Mapping[str, Any] | str | bytes | bytearray) -> Any:
    raw = _coerce_payload(payload)
    try:
        return operation_from_dict(raw)
    except (PlanLoadError, ValueError) as exc:
        raise ContractValidationError([_issue_from_exception(exc, raw)]) from exc


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _primitive(getattr(value, field.name)) for field in fields(value) if field.name != "_sealed"}
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    return value


def _action_to_dict(action: Any) -> dict[str, Any]:
    """Serialize only fields valid for the action discriminator branch."""
    result = _primitive(action)
    action_type = result["type"]
    if action.locator is not None:
        result["locator"] = action.locator.describe()
    if action.frame is not None:
        result["frame"] = action.frame.describe()
    if action.frame_path:
        result["frame_path"] = [item.describe() for item in action.frame_path]
    if action.wait_condition is not None:
        result["wait_condition"] = action.wait_condition.describe()
    if action.download_request is not None:
        result["download_request"] = action.download_request.describe()
    if action.pointer_request is not None:
        result["pointer_request"] = action.pointer_request.describe()
    allowed_by_type = {
        "navigate": {"type"},
        "click": {"type", "locator", "frame", "frame_path"},
        "fill": {"type", "locator", "text", "secret_reference", "secret_timeout_ms", "frame", "frame_path"},
        "press_key": {"type", "locator", "key", "key_scope", "frame", "frame_path"},
        "select_option": {"type", "locator", "option_value", "option_label", "option_values", "frame", "frame_path"},
        "set_checked": {"type", "locator", "checked", "frame", "frame_path"},
        "hover": {"type", "locator", "frame", "frame_path"},
        "scroll_to_target": {"type", "locator", "frame", "frame_path"},
        "pointer_move": {"type", "locator", "pointer_request", "frame", "frame_path"},
        "wait_for": {"type", "wait_condition", "wait_timeout_ms"},
        "switch_to_page": {"type", "page_id"},
        "close_page": {"type", "page_id"},
        "switch_to_opener": {"type"},
        "download": {"type", "locator", "download_request"},
        "upload_file": {"type", "locator", "frame", "frame_path", "file_paths", "allowed_files", "allowed_roots"},
        "select_combobox_option": {"type", "locator", "frame", "frame_path", "combobox"},
    }
    if action_type == "upload_file":
        upload = result.get("upload_authorization") or {}
        result.update(upload)
    if action_type == "select_combobox_option":
        result["combobox"] = action.combobox_selection.describe()
    allowed = allowed_by_type[action_type]
    return {
        key: value
        for key, value in result.items()
        if key in allowed and value is not None and value != []
    }


def _guard_to_dict(guard: Any) -> dict[str, Any]:
    if guard.when_target_absent is not None:
        return {
            "when_target_absent": {
                "expectations": [item.describe() for item in guard.when_target_absent.expectations]
            }
        }
    return {
        "branches": [
            {
                "branch_id": branch.branch_id,
                "when": {"expectations": [item.describe() for item in branch.when]},
                "execute": [_action_to_dict(item) for item in branch.execute],
            }
            for branch in guard.branches
        ],
        **(
            {"otherwise": [_action_to_dict(item) for item in guard.otherwise]}
            if guard.otherwise is not None
            else {}
        ),
    }


def _operation_to_dict(operation: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "operation_id": operation.operation_id,
        "url": operation.url,
        "action": _action_to_dict(operation.action),
        "expectations": [item.describe() for item in operation.expectations],
        "timeout_ms": operation.timeout_ms,
        "freshness": _primitive(operation.freshness),
        "require_unique_target": operation.require_unique_target,
        "locate_retry_ms": operation.locate_retry_ms,
        "cardinality": operation.cardinality.value,
    }
    if operation.page_transition is not None:
        result["page_transition"] = operation.page_transition.describe()
    if operation.dialog_contract is not None:
        result["dialog_contract"] = {
            key: value
            for key, value in _primitive(operation.dialog_contract).items()
            if value is not None
        }
    if operation.screenshot_config is not None:
        result["screenshot_config"] = _primitive(operation.screenshot_config)
    if operation.page_precondition is not None:
        result["page_precondition"] = operation.page_precondition.describe()
    if operation.target_preparation.dismiss_overlay_locators:
        result["target_preparation"] = {
            "dismiss_overlay_locators": [
                locator.describe() for locator in operation.target_preparation.dismiss_overlay_locators
            ]
        }
    if operation.guard is not None:
        result["guard"] = _guard_to_dict(operation.guard)
    if operation.network_artifact is not None:
        result["network_artifact"] = operation.network_artifact.describe()
    if operation.webauthn is not None:
        result["webauthn"] = operation.webauthn.describe()
    return result


def _browser_to_dict(browser: BrowserConfig) -> dict[str, Any]:
    return {
        "provider": browser.provider.value,
        "engine": browser.engine.value,
        "channel": browser.channel.value,
        "headless": browser.headless,
        "profile": browser.profile.value if isinstance(browser.profile, Enum) else browser.profile,
        "download_policy": _primitive(browser.download_policy),
    }


def serialize_execution_plan(plan: ExecutionPlan, *, include_browser_config: bool = True) -> dict[str, Any]:
    """Serialize an ExecutionPlan into its accepted public JSON form."""
    result = _primitive(plan)
    result["operations"] = [_operation_to_dict(operation) for operation in plan.operations]
    result["browser_config"] = _browser_to_dict(plan.browser_config)
    if not include_browser_config:
        result.pop("browser_config", None)
    return {key: value for key, value in result.items() if value is not None}


def serialize_plan_document(document: PlanDocument | ExecutionPlan) -> dict[str, Any]:
    """Serialize the canonical versioned document without losing plan detail."""
    if isinstance(document, ExecutionPlan):
        browser = document.browser_config
        plan = document
        version = MACHINE_CONTRACT_VERSION
    else:
        browser = document.browser
        plan = document.plan
        version = document.schema_version
    if version != MACHINE_CONTRACT_VERSION:
        raise ContractValidationError(
            [ValidationIssue("unsupported_contract_version", "/schema_version", "cannot serialize an unsupported contract version", MACHINE_CONTRACT_VERSION)]
        )
    return {
        "schema_version": version,
        "browser": _browser_to_dict(browser),
        "plan": serialize_execution_plan(plan, include_browser_config=False),
    }


def _require_receipt_mapping(payload: Any, *, expected_version: str, kind: str) -> Mapping[str, Any]:
    raw = _coerce_payload(payload)
    if raw.get("schema_version") != expected_version:
        raise ContractValidationError(
            [ValidationIssue("unsupported_receipt_version", "/schema_version", f"unsupported {kind} schema version", expected_version, _safe_type(raw.get("schema_version"), "/schema_version"))]
        )
    return raw


def parse_execution_receipt(payload: Mapping[str, Any] | str | bytes | bytearray) -> ExecutionReceipt:
    raw = _require_receipt_mapping(payload, expected_version=RECEIPT_SCHEMA_VERSION, kind="execution receipt")
    try:
        receipt = ExecutionReceipt(
            schema_version=raw["schema_version"], operation_id=raw["operation_id"], verdict=Verdict(raw["verdict"]), action_type=raw["action_type"], target_locator=raw["target_locator"], target_resolution=raw["target_resolution"], target_url=raw["target_url"], started_at_ms=raw["started_at_ms"], finished_at_ms=raw["finished_at_ms"], action_started_at_ms=raw["action_started_at_ms"], action_completed_at_ms=raw["action_completed_at_ms"], verification_completed_at_ms=raw["verification_completed_at_ms"], execution_status=raw["execution_status"], execution_error=raw["execution_error"], failure_kind=raw["failure_kind"], action_executed_successfully=raw["action_executed_successfully"], action_evidence=raw["action_evidence"], page_precondition=raw["page_precondition"], navigation_occurred=raw["navigation_occurred"], dispatch_document_url=raw["dispatch_document_url"], telemetry=list(raw["telemetry"]), operation_timing=raw["operation_timing"], expectation_evidence=list(raw["expectation_evidence"]), artifacts=list(raw["artifacts"]), cleanup=raw["cleanup"], page_transition=raw["page_transition"], expectations_declared=raw["expectations_declared"], pre_action_observation=(ObservationSummary(**raw["pre_action_observation"]) if raw["pre_action_observation"] is not None else None), post_action_observation=(ObservationSummary(**raw["post_action_observation"]) if raw["post_action_observation"] is not None else None), expectation_results=[ExpectationResult(**item) for item in raw["expectation_results"]], evidence=[EvidenceSignal(signal_id=item["signal_id"], kind=SignalKind(item["kind"]), availability=SignalAvailability(item["availability"]), collected_at_ms=item["collected_at_ms"], payload=item["payload"], notes=item.get("notes", "")) for item in raw["evidence"]], freshness=FreshnessEvaluation(**raw["freshness"]), recovery_attempts=[RecoveryAttempt(**item) for item in raw["recovery_attempts"]], limitations=list(raw["limitations"]), backend_identity=raw["backend_identity"], browser_identity=raw["browser_identity"], browser=raw["browser"], runtime_version=raw["runtime_version"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError([_issue_from_exception(exc, raw)]) from exc
    return receipt.seal()


def parse_plan_receipt(payload: Mapping[str, Any] | str | bytes | bytearray) -> PlanReceipt:
    from dingdongditch.contract.plan import PLAN_RECEIPT_SCHEMA_VERSION

    raw = _require_receipt_mapping(payload, expected_version=PLAN_RECEIPT_SCHEMA_VERSION, kind="plan receipt")
    try:
        steps = [
            PlanStepRecord(
                step_index=item["step_index"], operation_id=item["operation_id"], attempted=item["attempted"], skipped=item["skipped"], skip_reason=item["skip_reason"], operation_verdict=item["operation_verdict"], failure_kind=item["failure_kind"], started_at_ms=item["started_at_ms"], finished_at_ms=item["finished_at_ms"], browser_session_id=item["browser_session_id"], context_id=item["context_id"], page_id=item["page_id"], receipt=parse_execution_receipt(item["receipt"]) if item["receipt"] is not None else None,
            )
            for item in raw["steps"]
        ]
        receipt = PlanReceipt(
            schema_version=raw["schema_version"], plan_id=raw["plan_id"], plan_verdict=PlanVerdict(raw["plan_verdict"]), completion_status=CompletionStatus(raw["completion_status"]), failure_policy=raw["failure_policy"], declared_step_count=raw["declared_step_count"], attempted_step_count=raw["attempted_step_count"], verified_step_count=raw["verified_step_count"], skipped_step_count=raw["skipped_step_count"], decisive_step_index=raw["decisive_step_index"], decisive_operation_id=raw["decisive_operation_id"], failure_kind=raw["failure_kind"], started_at_ms=raw["started_at_ms"], finished_at_ms=raw["finished_at_ms"], browser=raw["browser"], backend_identity=raw["backend_identity"], browser_session_id=raw["browser_session_id"], context_id=raw["context_id"], page_id=raw["page_id"], steps=steps, limitations=list(raw["limitations"]), runtime_version=raw["runtime_version"], execution_error=raw["execution_error"], plan_describe=raw["plan"], plan_timing=raw["plan_timing"], lifecycle=raw["lifecycle"], telemetry=list(raw["telemetry"]),
        )
        receipt.check_invariants()
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError([_issue_from_exception(exc, raw)]) from exc
    return receipt.seal()


def parse_receipt(payload: Mapping[str, Any] | str | bytes | bytearray) -> ExecutionReceipt | PlanReceipt:
    """Decode a receipt by declared public shape without caller key inspection."""
    raw = _coerce_payload(payload)
    if "plan_verdict" in raw:
        return parse_plan_receipt(raw)
    if "verdict" in raw:
        return parse_execution_receipt(raw)
    raise ContractValidationError(
        [ValidationIssue("unknown_receipt_type", "", "payload is not a DingDongDitch receipt")]
    )
