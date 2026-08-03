"""Pluggable interpretation of application-specific browser lifecycle evidence."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from urllib.parse import urlsplit
from typing import Any, Callable

from dingdongditch.contract.application_lifecycle import (
    ApplicationLifecycleEvidence,
    ApplicationLifecycleState,
)


class ApplicationLifecycleAdapter(ABC):
    adapter_id = "unknown"

    @abstractmethod
    def begin(self, baseline: Any) -> ApplicationLifecycleEvidence:
        """Record the fresh pre-submission baseline and enter pending."""

    @abstractmethod
    def observe(self, observation: Any, *, fresh: bool = True) -> ApplicationLifecycleEvidence:
        """Classify one immutable browser observation."""

    @abstractmethod
    def record_cancellation(
        self, observation: Any, *, dispatch_verified: bool
    ) -> ApplicationLifecycleEvidence:
        """Bind cancellation only to verified browser dispatch evidence."""


def _visible_text(observation: Any) -> str:
    return "\n".join(
        str(block.get("text") or "").strip()
        for block in observation.visible_text
        if str(block.get("text") or "").strip()
    )


def _signature(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class UnknownApplicationLifecycleAdapter(ApplicationLifecycleAdapter):
    adapter_id = "unknown"

    def _unavailable(self, observation: Any | None, reason: str) -> ApplicationLifecycleEvidence:
        return ApplicationLifecycleEvidence(
            adapter_id=self.adapter_id,
            state=ApplicationLifecycleState.OBSERVATION_UNAVAILABLE,
            observation_id=getattr(observation, "observation_id", None),
            captured_at_ms=getattr(observation, "captured_at_ms", None),
            fresh=False,
            terminal=False,
            evidence={"reason": reason},
        )

    def begin(self, baseline: Any) -> ApplicationLifecycleEvidence:
        return self._unavailable(baseline, "no_application_lifecycle_adapter")

    def observe(self, observation: Any, *, fresh: bool = True) -> ApplicationLifecycleEvidence:
        return self._unavailable(observation, "no_application_lifecycle_adapter")

    def record_cancellation(
        self, observation: Any, *, dispatch_verified: bool
    ) -> ApplicationLifecycleEvidence:
        return self._unavailable(observation, "no_application_lifecycle_adapter")


class GeminiApplicationLifecycleAdapter(ApplicationLifecycleAdapter):
    adapter_id = "gemini"
    _STOP_LABELS = ("stop response", "stop generating", "stop generation")
    _FAILURE_LABELS = (
        "something went wrong",
        "failed to generate",
        "couldn't generate a response",
        "could not generate a response",
    )

    def __init__(self) -> None:
        self._baseline_signature: str | None = None
        self._last_signature: str | None = None
        self._inactive_signature: str | None = None
        self._inactive_stable = 0
        self._begun = False

    @staticmethod
    def supports(url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return host == "gemini.google.com" or host.endswith(".gemini.google.com")

    @staticmethod
    def _labels(observation: Any) -> list[str]:
        labels: list[str] = []
        for element in observation.interactive_elements:
            if not element.get("visible"):
                continue
            labels.append(" ".join(
                str(element.get(key) or "")
                for key in ("accessible_name", "visible_text", "placeholder")
            ).strip().lower())
        for block in observation.visible_text:
            value = str(block.get("text") or "").strip().lower()
            if value:
                labels.append(value)
        return labels

    def _result(
        self, observation: Any, state: ApplicationLifecycleState, *, fresh: bool,
        evidence: dict[str, Any],
    ) -> ApplicationLifecycleEvidence:
        return ApplicationLifecycleEvidence(
            adapter_id=self.adapter_id,
            state=state,
            observation_id=getattr(observation, "observation_id", None),
            captured_at_ms=getattr(observation, "captured_at_ms", None),
            fresh=fresh,
            terminal=state in {
                ApplicationLifecycleState.COMPLETED,
                ApplicationLifecycleState.CANCELLED,
                ApplicationLifecycleState.FAILED,
            },
            evidence=evidence,
        )

    def begin(self, baseline: Any) -> ApplicationLifecycleEvidence:
        if not self.supports(str(getattr(baseline, "url", ""))):
            return self._result(
                baseline, ApplicationLifecycleState.OBSERVATION_UNAVAILABLE,
                fresh=False, evidence={"reason": "application_binding_mismatch"},
            )
        text = _visible_text(baseline)
        self._baseline_signature = _signature(text)
        self._last_signature = self._baseline_signature
        self._inactive_signature = None
        self._inactive_stable = 0
        self._begun = True
        return self._result(
            baseline, ApplicationLifecycleState.PENDING, fresh=True,
            evidence={"baseline_text_hash": self._baseline_signature},
        )

    def observe(self, observation: Any, *, fresh: bool = True) -> ApplicationLifecycleEvidence:
        if not fresh:
            return self._result(
                observation, ApplicationLifecycleState.OBSERVATION_UNAVAILABLE,
                fresh=False, evidence={"reason": "observation_not_fresh"},
            )
        if not self._begun or not self.supports(str(getattr(observation, "url", ""))):
            return self._result(
                observation, ApplicationLifecycleState.OBSERVATION_UNAVAILABLE,
                fresh=False, evidence={"reason": "application_binding_mismatch_or_missing_baseline"},
            )
        text = _visible_text(observation)
        signature = _signature(text)
        labels = self._labels(observation)
        active = any(any(marker in label for marker in self._STOP_LABELS) for label in labels)
        failed = any(any(marker in label for marker in self._FAILURE_LABELS) for label in labels)
        changed = signature != self._baseline_signature
        progressed = signature != self._last_signature
        evidence = {
            "text_hash": signature,
            "text_length": len(text),
            "changed_from_baseline": changed,
            "meaningful_progress": progressed,
            "generation_active": active,
            "failure_indicator_visible": failed,
            "inactive_stable_samples": self._inactive_stable,
        }
        if failed:
            state = ApplicationLifecycleState.FAILED
        elif active:
            self._inactive_signature = None
            self._inactive_stable = 0
            state = (
                ApplicationLifecycleState.ACTIVE
                if progressed else ApplicationLifecycleState.VISUALLY_STABLE
            )
        elif not changed:
            self._inactive_signature = None
            self._inactive_stable = 0
            state = ApplicationLifecycleState.PENDING
        else:
            if signature == self._inactive_signature:
                self._inactive_stable += 1
            else:
                self._inactive_signature = signature
                self._inactive_stable = 1
            evidence["inactive_stable_samples"] = self._inactive_stable
            state = (
                ApplicationLifecycleState.COMPLETED
                if self._inactive_stable >= 2
                else ApplicationLifecycleState.VISUALLY_STABLE
            )
        self._last_signature = signature
        return self._result(observation, state, fresh=True, evidence=evidence)

    def record_cancellation(
        self, observation: Any, *, dispatch_verified: bool
    ) -> ApplicationLifecycleEvidence:
        if not dispatch_verified:
            return self._result(
                observation, ApplicationLifecycleState.OBSERVATION_UNAVAILABLE,
                fresh=False, evidence={"reason": "cancellation_dispatch_not_verified"},
            )
        return self._result(
            observation, ApplicationLifecycleState.CANCELLED, fresh=True,
            evidence={"cancellation_dispatch_verified": True},
        )


class ChatGPTApplicationLifecycleAdapter(GeminiApplicationLifecycleAdapter):
    """Interpret ChatGPT generation state from fresh browser observations."""

    adapter_id = "chatgpt"
    _STOP_LABELS = (
        "stop streaming",
        "stop generating",
        "stop generation",
        "stop response",
    )
    _FAILURE_LABELS = (
        "something went wrong",
        "error generating a response",
        "failed to generate",
        "network error",
    )

    @staticmethod
    def supports(url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return host in {"chatgpt.com", "www.chatgpt.com", "chat.openai.com"}


_ADAPTERS: tuple[tuple[Callable[[str], bool], type[ApplicationLifecycleAdapter]], ...] = (
    (GeminiApplicationLifecycleAdapter.supports, GeminiApplicationLifecycleAdapter),
    (ChatGPTApplicationLifecycleAdapter.supports, ChatGPTApplicationLifecycleAdapter),
)


def select_application_lifecycle_adapter(url: str) -> ApplicationLifecycleAdapter:
    for supports, adapter_type in _ADAPTERS:
        if supports(url):
            return adapter_type()
    return UnknownApplicationLifecycleAdapter()
