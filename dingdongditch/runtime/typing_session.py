"""Generic declared continuous-input execution.

This module deliberately does not infer focus, choose a keyboard sink, retry,
or interpret application-specific result text.  The caller declares the exact
target, ordered input, and (optionally) final browser expectations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from dingdongditch.backends.playwright_backend import PlaywrightBackend, monotonic_ms
from dingdongditch.contract.browser import BrowserConfig
from dingdongditch.contract.expectation import Expectation
from dingdongditch.contract.operation import Action, ActionType, FreshnessPolicy, KeyPressScope, Locator, Operation
from dingdongditch.contract.observation import freeze
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.evidence.collector import EvidenceCollector
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.session import ManagedSession, SessionStatus
from dingdongditch.runtime.verifier import evaluate_expectations


@dataclass(frozen=True)
class TypingSessionConfig:
    session_id: str
    url: str
    text: str
    target_locator: Locator
    max_text_chunk_characters: int = 32
    operation_timeout_ms: int = 10_000
    inter_key_delay_ms: int = 0
    final_expectations: tuple[Expectation, ...] = ()

    def validate(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("typing session_id is required")
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("typing session url is required")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("typing session text is required")
        self.target_locator.validate()
        if not isinstance(self.max_text_chunk_characters, int) or isinstance(self.max_text_chunk_characters, bool) or not 1 <= self.max_text_chunk_characters <= 1024:
            raise ValueError("max_text_chunk_characters must be between 1 and 1024")
        if not isinstance(self.operation_timeout_ms, int) or self.operation_timeout_ms < 100:
            raise ValueError("operation_timeout_ms must be >= 100")
        if not isinstance(self.inter_key_delay_ms, int) or not 0 <= self.inter_key_delay_ms <= 5_000:
            raise ValueError("inter_key_delay_ms must be between 0 and 5000")
        for expectation in self.final_expectations:
            expectation.validate()


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
    receipts: list[Any] = field(default_factory=list)
    completion_evidence: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipts", freeze(self.receipts))
        object.__setattr__(self, "completion_evidence", freeze(self.completion_evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "requested_characters": self.requested_characters,
            "typed_characters": self.typed_characters,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "duration_ms": max(0, self.finished_at_ms - self.started_at_ms),
            "failure_kind": self.failure_kind,
            "error": self.error,
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


def dispatch_typing_key(backend: PlaywrightBackend, operation: Operation) -> TypingKeyReceipt:
    operation.validate()
    if operation.action.type is not ActionType.PRESS_KEY:
        raise ValueError("typing fast dispatch accepts only PRESS_KEY")
    started = monotonic_ms()
    if not backend.is_started:
        return TypingKeyReceipt(operation.operation_id, str(operation.action.key), started, monotonic_ms(), False, "browser_session_not_active", "host-owned backend must be active before key dispatch", [], [], backend.browser_session_id, backend.page_id)
    collector = EvidenceCollector(scope_id=operation.operation_id, window_started_at_ms=started)
    dispatch = backend.dispatch(operation, collector=collector)
    return TypingKeyReceipt(operation.operation_id, str(operation.action.key), dispatch.started_at_ms, dispatch.completed_at_ms, dispatch.ok, dispatch.failure_kind, dispatch.error, [item.to_dict() for item in collector.signals], [dict(item) for item in dispatch.recovery_attempts], backend.browser_session_id, backend.page_id)


def dispatch_typing_text(backend: PlaywrightBackend, operation_id: str, text: str) -> TypingKeyReceipt:
    started = monotonic_ms()
    if not backend.is_started:
        return TypingKeyReceipt(operation_id, text, started, monotonic_ms(), False, "browser_session_not_active", "host-owned backend must be active before text dispatch", [], [], backend.browser_session_id, backend.page_id)
    try:
        backend.page.keyboard.type(text, delay=0)
        finished = monotonic_ms()
        return TypingKeyReceipt(operation_id, text, started, finished, True, None, None, [{"kind": "action_result", "collected_at_ms": finished, "payload": {"ok": True, "type": "type_text_batch", "character_count": len(text)}}], [], backend.browser_session_id, backend.page_id)
    except Exception as exc:
        return TypingKeyReceipt(operation_id, text, started, monotonic_ms(), False, "action_dispatch_failed", f"{type(exc).__name__}: {exc}", [], [], backend.browser_session_id, backend.page_id)


def _control_key(character: str) -> str | None:
    return {"\n": "Enter", "\t": "Tab", "\x1b": "Escape", "\b": "Backspace", "\x7f": "Delete"}.get(character)


class TypingSession(ManagedSession):
    """Execute one declared target and one ordered input sequence."""

    def __init__(self, config: TypingSessionConfig, *, backend: PlaywrightBackend, browser_config: BrowserConfig | None = None, operation_executor: Callable[[Operation], ExecutionReceipt] | None = None) -> None:
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
        self._operation_executor = operation_executor

    def _operation(self, suffix: str, action: Action, *, expectations: tuple[Expectation, ...] = ()) -> Operation:
        return Operation(operation_id=f"{self.config.session_id}-{suffix}", url=self.config.url, action=action, expectations=expectations, timeout_ms=self.config.operation_timeout_ms)

    def _execute(self, operation: Operation) -> ExecutionReceipt:
        receipt = self._operation_executor(operation) if self._operation_executor is not None else execute_operation(operation, backend=self.backend, browser_config=self.browser_config)
        self.receipts.append(receipt)
        return receipt

    def _dispatch_key(self, index: int, key: str) -> TypingKeyReceipt:
        operation = self._operation(f"key-{index:04d}", Action(type=ActionType.PRESS_KEY, key=key, key_scope=KeyPressScope.ACTIVE_PAGE))
        if self._operation_executor is None:
            receipt = dispatch_typing_key(self.backend, operation)
            self.receipts.append(receipt)
            return receipt
        receipt = self._operation_executor(operation)
        self.receipts.append(receipt)
        return TypingKeyReceipt(operation.operation_id, key, receipt.action_started_at_ms or receipt.started_at_ms, receipt.finished_at_ms, bool(receipt.action_executed_successfully), receipt.failure_kind, receipt.execution_error, [], [], receipt.browser.get("browser_session_id"), receipt.browser.get("page_id"))

    def _dispatch_text(self, index: int, text: str) -> TypingKeyReceipt:
        if self._operation_executor is None:
            receipt = dispatch_typing_text(self.backend, f"{self.config.session_id}-text-{index:04d}", text)
            self.receipts.append(receipt)
            return receipt
        started = monotonic_ms()
        for offset, character in enumerate(text):
            receipt = self._dispatch_key(index + offset, character)
            if receipt.error is not None:
                return receipt
        return TypingKeyReceipt(f"{self.config.session_id}-text-{index:04d}", text, started, monotonic_ms(), True, None, None, [], [], self.backend.browser_session_id, self.backend.page_id)

    def _final_verify(self) -> dict[str, Any] | None:
        if not self.config.final_expectations:
            return None
        started = monotonic_ms()
        observation = self.backend.observe_page()
        collector = EvidenceCollector(scope_id=f"{self.config.session_id}-final", window_started_at_ms=started)
        results = evaluate_expectations(backend=self.backend, expectations=list(self.config.final_expectations), collector=collector, action_started_at_ms=started, verification_completed_at_ms=monotonic_ms(), freshness=FreshnessPolicy(), post_network_payload={"records": []}, post_url=str(self.backend.page.url))
        return {"observation_id": observation.observation_id, "passed": bool(results) and all(item.result == "pass" for item in results), "results": [item.to_dict() for item in results], "evidence": [item.to_dict() for item in collector.signals]}

    def run(self) -> TypingSessionResult:
        self.begin()
        with self.backend.exclusive_use(f"typing_session:{self.config.session_id}"):
            started = monotonic_ms()
            typed = 0
            target = self._execute(self._operation("target", Action(type=ActionType.CLICK, locator=self.config.target_locator)))
            if target.execution_error is not None:
                return self._result(SessionStatus.FAILED, started, typed, "target_dispatch_failed", target.execution_error)
            index = 0
            while index < len(self.config.text):
                character = self.config.text[index]
                key = _control_key(character)
                if key is None and not character.isprintable():
                    return self._result(SessionStatus.FAILED, started, typed, "unsupported_character", f"unsupported typing character: {character!r}")
                if key is not None:
                    receipt = self._dispatch_key(index, key)
                    consumed = 1
                else:
                    end = min(len(self.config.text), index + self.config.max_text_chunk_characters)
                    while end > index and any(_control_key(item) is not None or not item.isprintable() for item in self.config.text[index:end]):
                        end -= 1
                    batch = self.config.text[index:end]
                    if not batch:
                        return self._result(SessionStatus.FAILED, started, typed, "unsupported_character", f"unsupported typing character: {character!r}")
                    receipt = self._dispatch_text(index, batch)
                    consumed = len(batch)
                if receipt.error is not None:
                    return self._result(SessionStatus.FAILED, started, typed, receipt.failure_kind or "input_dispatch_failed", receipt.error)
                typed += consumed
                index += consumed
                if self.config.inter_key_delay_ms and index < len(self.config.text):
                    self.backend.page.wait_for_timeout(self.config.inter_key_delay_ms)
            completion = self._final_verify()
            if completion is not None and not completion["passed"]:
                return self._result(SessionStatus.STOPPED, started, typed, "final_verification_failed", "declared final verification did not pass", completion)
            return self._result(SessionStatus.COMPLETED, started, typed, completion_evidence=completion)

    def _result(self, status: SessionStatus, started: int, typed: int, failure_kind: str | None = None, error: str | None = None, completion_evidence: dict[str, Any] | None = None) -> TypingSessionResult:
        result = TypingSessionResult(self.config.session_id, status, len(self.config.text), typed, started, monotonic_ms(), failure_kind, error, list(self.receipts), completion_evidence)
        self.finish(status)
        return result
