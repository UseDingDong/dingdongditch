"""Typed evidence-screenshot policies."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any

class ScreenshotPolicy(str, Enum):
    NEVER = "never"
    ON_FAILURE = "on_failure"
    BEFORE_AND_AFTER = "before_and_after"
    AFTER_SUCCESS = "after_success"
    ALWAYS = "always"

@dataclass(frozen=True)
class ScreenshotConfig:
    policy: ScreenshotPolicy = ScreenshotPolicy.ON_FAILURE
    full_page: bool = False
    max_per_operation: int = 4
    max_per_plan: int = 32
    artifact_root: str = "artifacts/evidence_screenshots"
    sensitive_selectors: tuple[str, ...] = ()
    redact_password_inputs: bool = True
    mandatory_redaction: bool = False
    capture_timeout_ms: int = 5_000

    def validate(self) -> None:
        if min(self.max_per_operation, self.max_per_plan) < 0:
            raise ValueError("screenshot limits must be non-negative")
        if self.capture_timeout_ms < 1:
            raise ValueError("capture_timeout_ms must be positive")

    def describe(self) -> dict[str, Any]:
        self.validate()
        return {"policy": self.policy.value, "full_page": self.full_page, "max_per_operation": self.max_per_operation, "max_per_plan": self.max_per_plan, "artifact_root": self.artifact_root, "sensitive_selectors": list(self.sensitive_selectors), "redact_password_inputs": self.redact_password_inputs, "mandatory_redaction": self.mandatory_redaction, "capture_timeout_ms": self.capture_timeout_ms}
