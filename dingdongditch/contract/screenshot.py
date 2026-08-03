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
class DesktopRedactionRegion:
    """Caller-declared rectangle in captured desktop-image pixel coordinates."""

    region_id: str
    x: int
    y: int
    width: int
    height: int

    def validate(self) -> None:
        if not isinstance(self.region_id, str) or not self.region_id.strip():
            raise ValueError("desktop redaction region_id must be non-empty")
        values = (self.x, self.y, self.width, self.height)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("desktop redaction coordinates must be integer pixels")
        if self.x < 0 or self.y < 0:
            raise ValueError("desktop redaction x and y must be non-negative")
        if self.width < 1 or self.height < 1:
            raise ValueError("desktop redaction width and height must be positive")

    def describe(self) -> dict[str, Any]:
        self.validate()
        return {"region_id": self.region_id, "x": self.x, "y": self.y, "width": self.width, "height": self.height}


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
    desktop_redaction_regions: tuple[DesktopRedactionRegion, ...] = ()
    capture_timeout_ms: int = 5_000

    def validate(self) -> None:
        if min(self.max_per_operation, self.max_per_plan) < 0:
            raise ValueError("screenshot limits must be non-negative")
        if self.capture_timeout_ms < 1:
            raise ValueError("capture_timeout_ms must be positive")
        if not isinstance(self.redact_password_inputs, bool) or not isinstance(
            self.mandatory_redaction, bool
        ):
            raise ValueError("screenshot redaction flags must be bool values")
        if not isinstance(self.sensitive_selectors, tuple) or any(
            not isinstance(selector, str) or not selector.strip()
            for selector in self.sensitive_selectors
        ):
            raise ValueError("sensitive_selectors must contain non-empty CSS selectors")
        if not isinstance(self.desktop_redaction_regions, tuple) or any(
            not isinstance(region, DesktopRedactionRegion)
            for region in self.desktop_redaction_regions
        ):
            raise ValueError("desktop_redaction_regions must contain DesktopRedactionRegion values")
        for region in self.desktop_redaction_regions:
            region.validate()
        region_ids = [region.region_id for region in self.desktop_redaction_regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("desktop redaction region_id values must be unique")
        if self.mandatory_redaction and not (
            self.redact_password_inputs or self.sensitive_selectors or self.desktop_redaction_regions
        ):
            raise ValueError(
                "mandatory_redaction requires password, selector, or desktop region redaction"
            )

    def describe(self) -> dict[str, Any]:
        self.validate()
        return {"policy": self.policy.value, "full_page": self.full_page, "max_per_operation": self.max_per_operation, "max_per_plan": self.max_per_plan, "artifact_root": self.artifact_root, "sensitive_selectors": list(self.sensitive_selectors), "redact_password_inputs": self.redact_password_inputs, "mandatory_redaction": self.mandatory_redaction, "desktop_redaction_regions": [region.describe() for region in self.desktop_redaction_regions], "capture_timeout_ms": self.capture_timeout_ms}
