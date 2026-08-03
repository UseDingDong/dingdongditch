"""A focus-aware typing session built from ordinary PRESS_KEY operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from dingdongditch.backends.playwright_backend import PlaywrightBackend, monotonic_ms
from dingdongditch.contract.browser import BrowserConfig
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    KeyPressScope,
    Locator,
    Operation,
)
from dingdongditch.contract.observation import freeze
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.session import (
    ManagedSession,
    SessionCheckpoint,
    SessionPhase,
    SessionStatus,
)


class TypingFocusPolicy(str, Enum):
    TARGET_FOCUSED = "target_focused"
    PAGE_FOCUSED_TARGET_VISIBLE = "page_focused_target_visible"
    TARGET_CONTAINS_FOCUS = "target_contains_focus"
    ACQUIRE_REDIRECTED_FOCUS = "acquire_redirected_focus"
    KEYBOARD_SINK_FOCUSED = "keyboard_sink_focused"


@dataclass(frozen=True)
class TypingSessionConfig:
    session_id: str
    url: str
    text: str
    focus_locator: Locator
    acquire_locator: Locator | None = None
    focus_policy: TypingFocusPolicy = TypingFocusPolicy.TARGET_FOCUSED
    verify_every_characters: int = 20
    inter_key_delay_ms: int = 0
    operation_timeout_ms: int = 10_000
    final_separator_handshake: bool = False
    completion_settle_ms: int = 750

    def validate(self) -> None:
        if not self.session_id.strip():
            raise ValueError("typing session_id is required")
        if not self.url:
            raise ValueError("typing session url is required")
        if not self.text:
            raise ValueError("typing session text is required")
        self.focus_locator.validate()
        if self.acquire_locator is not None:
            self.acquire_locator.validate()
        if not isinstance(self.focus_policy, TypingFocusPolicy):
            raise ValueError("invalid typing focus policy")
        if self.verify_every_characters < 1:
            raise ValueError("verify_every_characters must be >= 1")
        if not 0 <= self.inter_key_delay_ms <= 5_000:
            raise ValueError("inter_key_delay_ms must be between 0 and 5000")
        if self.operation_timeout_ms < 100:
            raise ValueError("operation_timeout_ms must be >= 100")
        if not 0 <= self.completion_settle_ms <= 5_000:
            raise ValueError("completion_settle_ms must be between 0 and 5000")


@dataclass(frozen=True)
class TypingSessionResult:
    session_id: str
    status: SessionStatus
    requested_characters: int
    typed_characters: int
    started_at_ms: int
    finished_at_ms: int
    failure_kind: str | None
    error: str | None
    checkpoints: list[SessionCheckpoint] = field(default_factory=list)
    receipts: list[Any] = field(default_factory=list)
    completion_evidence: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "checkpoints", freeze(self.checkpoints))
        object.__setattr__(self, "receipts", freeze(self.receipts))
        object.__setattr__(self, "completion_evidence", freeze(self.completion_evidence))

    @property
    def duration_ms(self) -> int:
        return max(0, self.finished_at_ms - self.started_at_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "requested_characters": self.requested_characters,
            "typed_characters": self.typed_characters,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "duration_ms": self.duration_ms,
            "failure_kind": self.failure_kind,
            "error": self.error,
            "checkpoints": [item.to_dict() for item in self.checkpoints],
            "receipts": [item.to_dict() for item in self.receipts],
            "completion_evidence": self.completion_evidence,
        }


@dataclass(frozen=True)
class TypingKeyReceipt:
    operation_id: str
    key: str
    started_at_ms: int
    finished_at_ms: int
    dispatched: bool
    failure_kind: str | None
    error: str | None
    evidence: list[dict[str, Any]]
    recovery_attempts: list[dict[str, Any]]
    browser_session_id: str | None
    page_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", freeze(self.evidence))
        object.__setattr__(self, "recovery_attempts", freeze(self.recovery_attempts))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def dispatch_typing_key(
    backend: PlaywrightBackend,
    operation: Operation,
) -> TypingKeyReceipt:
    """Dispatch one validated PRESS_KEY inside an already-verified session."""
    operation.validate()
    if operation.action.type != ActionType.PRESS_KEY:
        raise ValueError("typing fast dispatch accepts only PRESS_KEY")
    started = monotonic_ms()
    if not backend.is_started:
        return TypingKeyReceipt(
            operation_id=operation.operation_id,
            key=str(operation.action.key),
            started_at_ms=started,
            finished_at_ms=monotonic_ms(),
            dispatched=False,
            failure_kind="browser_session_not_active",
            error="host-owned backend must be active before key dispatch",
            evidence=[],
            recovery_attempts=[],
            browser_session_id=backend.browser_session_id,
            page_id=backend.page_id,
        )
    collector = EvidenceCollector(
        scope_id=operation.operation_id, window_started_at_ms=started
    )
    dispatch = backend.dispatch(operation, collector=collector)
    return TypingKeyReceipt(
        operation_id=operation.operation_id,
        key=str(operation.action.key),
        started_at_ms=dispatch.started_at_ms,
        finished_at_ms=dispatch.completed_at_ms,
        dispatched=dispatch.ok,
        failure_kind=dispatch.failure_kind,
        error=dispatch.error,
        evidence=[item.to_dict() for item in collector.signals],
        recovery_attempts=[dict(item) for item in dispatch.recovery_attempts],
        browser_session_id=backend.browser_session_id,
        page_id=backend.page_id,
    )


def dispatch_typing_text(
    backend: PlaywrightBackend,
    operation_id: str,
    text: str,
) -> TypingKeyReceipt:
    """Insert printable text without interpreting it as a keyboard key name."""
    started = monotonic_ms()
    if not backend.is_started:
        return TypingKeyReceipt(
            operation_id=operation_id,
            key=text,
            started_at_ms=started,
            finished_at_ms=monotonic_ms(),
            dispatched=False,
            failure_kind="browser_session_not_active",
            error="host-owned backend must be active before text dispatch",
            evidence=[],
            recovery_attempts=[],
            browser_session_id=backend.browser_session_id,
            page_id=backend.page_id,
        )
    try:
        backend.page.keyboard.insert_text(text)
        finished = monotonic_ms()
        return TypingKeyReceipt(
            operation_id=operation_id,
            key=text,
            started_at_ms=started,
            finished_at_ms=finished,
            dispatched=True,
            failure_kind=None,
            error=None,
            evidence=[
                {
                    "kind": "action_result",
                    "collected_at_ms": finished,
                    "payload": {
                        "ok": True,
                        "type": "insert_text",
                        "character_count": len(text),
                    },
                }
            ],
            recovery_attempts=[],
            browser_session_id=backend.browser_session_id,
            page_id=backend.page_id,
        )
    except Exception as exc:
        finished = monotonic_ms()
        return TypingKeyReceipt(
            operation_id=operation_id,
            key=text,
            started_at_ms=started,
            finished_at_ms=finished,
            dispatched=False,
            failure_kind="action_dispatch_failed",
            error=f"{type(exc).__name__}: {exc}",
            evidence=[],
            recovery_attempts=[],
            browser_session_id=backend.browser_session_id,
            page_id=backend.page_id,
        )


def _control_key_for_character(character: str) -> str | None:
    controls = {
        "\n": "Enter",
        "\t": "Tab",
        "\x1b": "Escape",
        "\b": "Backspace",
        "\x7f": "Delete",
    }
    return controls.get(character)


class TypingSession(ManagedSession):
    """Own focus acquisition, guarded typing, and fail-closed termination."""

    def __init__(
        self,
        config: TypingSessionConfig,
        *,
        backend: PlaywrightBackend,
        browser_config: BrowserConfig | None = None,
    ) -> None:
        super().__init__()
        config.validate()
        if not backend.is_started:
            raise RuntimeError("TypingSession requires an active host-owned backend")
        self.config = config
        self.backend = backend
        self.browser_config = browser_config or backend.browser_config
        if self.browser_config.describe() != backend.browser_config.describe():
            raise ValueError("browser_config does not match the active backend")
        self.receipts: list[Any] = []
        self._pre_acquire_active_element: dict[str, Any] | None = None

    def _operation(self, suffix: str, action: Action) -> Operation:
        return Operation(
            operation_id=f"{self.config.session_id}-{suffix}",
            url=self.config.url,
            action=action,
            timeout_ms=self.config.operation_timeout_ms,
        )

    def _execute(self, suffix: str, action: Action) -> ExecutionReceipt:
        receipt = execute_operation(
            self._operation(suffix, action),
            backend=self.backend,
            browser_config=self.browser_config,
        )
        self.receipts.append(receipt)
        return receipt

    def _dispatch_key(self, index: int, key: str) -> TypingKeyReceipt:
        receipt = dispatch_typing_key(
            self.backend,
            self._operation(
                f"key-{index:04d}",
                Action(
                    type=ActionType.PRESS_KEY,
                    key=key,
                    key_scope=KeyPressScope.ACTIVE_PAGE,
                ),
            ),
        )
        self.receipts.append(receipt)
        return receipt

    def _dispatch_text(self, index: int, text: str) -> TypingKeyReceipt:
        receipt = dispatch_typing_text(
            self.backend,
            f"{self.config.session_id}-text-{index:04d}",
            text,
        )
        self.receipts.append(receipt)
        return receipt

    def _verify_focus(self, phase: SessionPhase, typed: int) -> bool:
        try:
            state = self.backend.read_element_state(self.config.focus_locator)
            page_focus = self.backend.read_page_focus_state()
        except Exception as exc:
            return self.checkpoint(
                phase,
                False,
                typed_characters=typed,
                focus_policy=self.config.focus_policy.value,
                inspection_error=f"{type(exc).__name__}: {exc}",
            )
        if self.config.focus_policy == TypingFocusPolicy.TARGET_FOCUSED:
            passed = (
                state.get("match_count") == 1
                and state.get("visible") is True
                and state.get("focused") is True
                and page_focus.get("focused") is True
            )
        elif self.config.focus_policy == TypingFocusPolicy.PAGE_FOCUSED_TARGET_VISIBLE:
            passed = (
                state.get("match_count") == 1
                and state.get("visible") is True
                and page_focus.get("focused") is True
                and (page_focus.get("active_element") or {}).get("tag")
                not in {"input", "textarea", "select"}
                and (page_focus.get("active_element") or {}).get("contenteditable")
                is not True
            )
        elif self.config.focus_policy == TypingFocusPolicy.TARGET_CONTAINS_FOCUS:
            try:
                focus_contained = self.backend.read_focus_containment(
                    self.config.focus_locator
                )
            except Exception:
                focus_contained = False
            passed = (
                state.get("match_count") == 1
                and state.get("visible") is True
                and page_focus.get("focused") is True
                and focus_contained is True
            )
        elif self.config.focus_policy == TypingFocusPolicy.ACQUIRE_REDIRECTED_FOCUS:
            active = page_focus.get("active_element") or {}
            before = self._pre_acquire_active_element or {}
            identity = {
                key: active.get(key)
                for key in ("tag", "id", "role", "test_id")
            }
            before_identity = {
                key: before.get(key)
                for key in ("tag", "id", "role", "test_id")
            }
            passed = (
                state.get("match_count") == 1
                and state.get("visible") is True
                and page_focus.get("focused") is True
                and active.get("tag") in {"input", "textarea"}
                and identity != before_identity
            )
        else:
            active = page_focus.get("active_element") or {}
            passed = (
                state.get("match_count") == 1
                and state.get("visible") is True
                and page_focus.get("focused") is True
                and active.get("tag") in {"input", "textarea"}
            )
        return self.checkpoint(
            phase,
            passed,
            typed_characters=typed,
            focus_policy=self.config.focus_policy.value,
            target={
                "match_count": state.get("match_count"),
                "visible": state.get("visible"),
                "focused": state.get("focused"),
            },
            page_focus=page_focus,
            focus_contained=(
                focus_contained
                if self.config.focus_policy == TypingFocusPolicy.TARGET_CONTAINS_FOCUS
                else None
            ),
            focus_redirected=(
                passed
                if self.config.focus_policy == TypingFocusPolicy.ACQUIRE_REDIRECTED_FOCUS
                else None
            ),
            keyboard_sink_focused=(
                passed
                if self.config.focus_policy == TypingFocusPolicy.KEYBOARD_SINK_FOCUSED
                else None
            ),
        )

    def _result(
        self,
        *,
        status: SessionStatus,
        started: int,
        typed: int,
        failure_kind: str | None = None,
        error: str | None = None,
        completion_evidence: dict[str, Any] | None = None,
    ) -> TypingSessionResult:
        result = TypingSessionResult(
            session_id=self.config.session_id,
            status=status,
            requested_characters=len(self.config.text),
            typed_characters=typed,
            started_at_ms=started,
            finished_at_ms=monotonic_ms(),
            failure_kind=failure_kind,
            error=error,
            checkpoints=list(self.checkpoints),
            receipts=list(self.receipts),
            completion_evidence=completion_evidence,
        )
        self.finish(status)
        return result

    @staticmethod
    def _completion_facts(observation: Any) -> dict[str, Any]:
        texts = []
        for block in observation.visible_text:
            texts.extend(
                part.strip()
                for part in str(block.get("text") or "").splitlines()
                if part.strip()
            )
        lowered = [item.lower() for item in texts]
        counters = [item for item in texts if "/" in item and all(
            part.isdigit() for part in item.split("/", 1))]
        has_wpm = "wpm" in lowered
        has_accuracy = "acc" in lowered or "accuracy" in lowered
        def value_after(names: set[str], pattern: str) -> str | None:
            for index, item in enumerate(lowered):
                if item not in names:
                    continue
                for candidate in texts[index + 1:index + 4]:
                    match = re.fullmatch(pattern, candidate.strip(), re.I)
                    if match:
                        return match.group(1)
            return None

        wpm = value_after({"wpm"}, r"(\d+(?:\.\d+)?)")
        accuracy = value_after(
            {"acc", "accuracy"}, r"(\d+(?:\.\d+)?)%?"
        )
        character_match = None
        for index, item in enumerate(lowered):
            candidates = [texts[index]]
            if item == "characters":
                candidates.extend(texts[index + 1:index + 4])
            for candidate in candidates:
                match = re.search(
                    r"\b(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\b",
                    candidate,
                )
                if match:
                    character_match = match
                    break
            if character_match:
                break
        character_breakdown = None
        errors = None
        if character_match:
            correct, incorrect, extra, missed = (
                int(value) for value in character_match.groups()
            )
            character_breakdown = {
                "correct": correct,
                "incorrect": incorrect,
                "extra": extra,
                "missed": missed,
                "raw": character_match.group(0),
            }
            errors = incorrect + extra + missed
        explicit_errors = value_after({"errors", "error"}, r"(\d+)")
        if explicit_errors is not None:
            errors = int(explicit_errors)
        results_verified = (
            wpm is not None
            and accuracy is not None
            and errors is not None
            and character_breakdown is not None
        )
        return {
            "observation_id": observation.observation_id,
            "counters": counters,
            "has_wpm": has_wpm,
            "has_accuracy": has_accuracy,
            "results_visible": has_wpm and has_accuracy,
            "results_verified": results_verified,
            "wpm": wpm,
            "accuracy": accuracy,
            "errors": errors,
            "character_breakdown": character_breakdown,
        }

    def run(self) -> TypingSessionResult:
        self.begin()
        with self.backend.exclusive_use(f"typing_session:{self.config.session_id}"):
            try:
                return self._run()
            except Exception:
                self.finish(SessionStatus.FAILED)
                raise

    def _run(self) -> TypingSessionResult:
        started = monotonic_ms()
        typed = 0
        if self.config.focus_policy == TypingFocusPolicy.ACQUIRE_REDIRECTED_FOCUS:
            try:
                self._pre_acquire_active_element = (
                    self.backend.read_page_focus_state().get("active_element") or {}
                )
            except Exception:
                self._pre_acquire_active_element = {}
        acquire = self._execute(
            "acquire-focus",
            Action(
                type=ActionType.CLICK,
                locator=self.config.acquire_locator or self.config.focus_locator,
            ),
        )
        if acquire.execution_error is not None:
            self.checkpoint(
                SessionPhase.ACQUIRE, False, error=acquire.execution_error
            )
            return self._result(
                status=SessionStatus.FAILED,
                started=started,
                typed=typed,
                failure_kind="focus_acquisition_failed",
                error=acquire.execution_error,
            )
        self.checkpoint(SessionPhase.ACQUIRE, True)
        if not self._verify_focus(SessionPhase.VERIFY, typed):
            return self._result(
                status=SessionStatus.STOPPED,
                started=started,
                typed=typed,
                failure_kind="focus_verification_failed",
                error="typing context was not focused after acquisition",
            )

        for index, character in enumerate(self.config.text):
            if typed and typed % self.config.verify_every_characters == 0:
                if not self._verify_focus(SessionPhase.PERFORM, typed):
                    return self._result(
                        status=SessionStatus.STOPPED,
                        started=started,
                        typed=typed,
                        failure_kind="typing_context_lost",
                        error="typing context verification failed",
                    )
            key = _control_key_for_character(character)
            if key is None and not character.isprintable():
                return self._result(
                    status=SessionStatus.FAILED,
                    started=started,
                    typed=typed,
                    failure_kind="unsupported_character",
                    error=f"unsupported typing character: {character!r}",
                )
            is_final_separator = (
                self.config.final_separator_handshake
                and index == len(self.config.text) - 1
                and character == " "
            )
            before_facts = None
            if is_final_separator:
                if not self._verify_focus(SessionPhase.PERFORM, typed):
                    return self._result(
                        status=SessionStatus.STOPPED,
                        started=started,
                        typed=typed,
                        failure_kind="pre_final_separator_focus_failed",
                        error="final separator blocked because typing focus was not proven",
                    )
                before = self.backend.observe_page()
                before_facts = self._completion_facts(before)
                self.checkpoint(
                    SessionPhase.PERFORM,
                    bool(before_facts["counters"]) or before_facts["results_visible"],
                    event="pre_final_separator",
                    **before_facts,
                )
                if not before_facts["counters"] and not before_facts["results_visible"]:
                    return self._result(
                        status=SessionStatus.STOPPED,
                        started=started,
                        typed=typed,
                        failure_kind="pre_final_separator_state_unproven",
                        error="page proved neither an incomplete test nor a results page",
                    )
            receipt = (
                self._dispatch_key(index, key)
                if key is not None
                else self._dispatch_text(index, character)
            )
            if receipt.error is not None:
                return self._result(
                    status=SessionStatus.FAILED,
                    started=started,
                    typed=typed,
                    failure_kind=receipt.failure_kind or "key_dispatch_failed",
                    error=receipt.error,
                )
            typed += 1
            if is_final_separator:
                immediate = self.backend.observe_page()
                immediate_facts = self._completion_facts(immediate)
                accepted = immediate_facts["results_verified"]
                settled_facts = None
                if not accepted and self.config.completion_settle_ms:
                    self.backend.page.wait_for_timeout(
                        self.config.completion_settle_ms
                    )
                    settled = self.backend.observe_page()
                    settled_facts = self._completion_facts(settled)
                    accepted = settled_facts["results_verified"]
                terminal_facts = settled_facts or immediate_facts
                self.checkpoint(
                    SessionPhase.FINISH,
                    accepted,
                    event="post_final_separator_acceptance",
                    final_space_operation_id=receipt.operation_id,
                    immediate=immediate_facts,
                    settled=settled_facts,
                    replacement_delimiter_used=False,
                    terminal_results=terminal_facts,
                )
                if not accepted:
                    return self._result(
                        status=SessionStatus.STOPPED,
                        started=started,
                        typed=typed,
                        failure_kind="completion_not_accepted",
                        error=(
                            "full typing payload dispatched but the fresh results "
                            "observation did not contain all required metrics"
                        ),
                    )
                self.checkpoint(
                    SessionPhase.FINISH,
                    True,
                    event="end_page_handshake",
                    typed_characters=typed,
                    requested_characters=len(self.config.text),
                    **terminal_facts,
                )
                return self._result(
                    status=SessionStatus.COMPLETED,
                    started=started,
                    typed=typed,
                    completion_evidence=terminal_facts,
                )
            if (
                self.config.inter_key_delay_ms
                and typed < len(self.config.text)
            ):
                self.backend.page.wait_for_timeout(
                    self.config.inter_key_delay_ms
                )

        # A successful final key may intentionally replace or remove the typing
        # target (for example, submission or a completed test). There is no next
        # key to guard, so finish attests dispatch completion rather than requiring
        # the old focus target to remain present.
        self.checkpoint(
            SessionPhase.FINISH,
            True,
            typed_characters=typed,
            requested_characters=len(self.config.text),
        )
        return self._result(
            status=SessionStatus.COMPLETED, started=started, typed=typed
        )
