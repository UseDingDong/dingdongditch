"""Backend-independent pointer movement contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PointerOrigin(str, Enum):
    """Coordinate origin used to resolve a pointer movement."""

    VIEWPORT = "viewport"
    ELEMENT_CENTER = "element_center"
    ELEMENT_OFFSET = "element_offset"


MIN_POINTER_STEPS = 1
MAX_POINTER_STEPS = 1_000
MAX_ABSOLUTE_COORDINATE = 1_000_000.0


def _validate_coordinate(value: float | int | None, *, field_name: str) -> None:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be a finite number")
    if abs(float(value)) > MAX_ABSOLUTE_COORDINATE:
        raise ValueError(
            f"{field_name} exceeds maximum absolute coordinate "
            f"{MAX_ABSOLUTE_COORDINATE:g}"
        )


@dataclass(frozen=True)
class PointerMoveRequest:
    """A deterministic pointer movement declaration.

    ``viewport`` coordinates are CSS pixels relative to the main-frame viewport.
    ``element_offset`` coordinates are CSS-pixel offsets from the located
    element's top-left border-box corner.
    """

    origin: PointerOrigin
    x: float | int | None = None
    y: float | int | None = None
    steps: int = 1
    verify_position: bool = True

    def validate(self) -> None:
        if not isinstance(self.origin, PointerOrigin):
            raise ValueError("pointer origin must be a PointerOrigin")
        if isinstance(self.steps, bool) or not isinstance(self.steps, int):
            raise ValueError("pointer steps must be an integer")
        if not MIN_POINTER_STEPS <= self.steps <= MAX_POINTER_STEPS:
            raise ValueError(
                f"pointer steps must be between {MIN_POINTER_STEPS} and "
                f"{MAX_POINTER_STEPS}"
            )
        if not isinstance(self.verify_position, bool):
            raise ValueError("verify_position must be a bool")

        if self.origin == PointerOrigin.ELEMENT_CENTER:
            if self.x is not None or self.y is not None:
                raise ValueError(
                    "element_center pointer movement must not include x or y"
                )
            return

        _validate_coordinate(self.x, field_name="pointer x")
        _validate_coordinate(self.y, field_name="pointer y")
        if self.origin == PointerOrigin.VIEWPORT and (
            float(self.x) < 0 or float(self.y) < 0  # type: ignore[arg-type]
        ):
            raise ValueError("viewport pointer coordinates must be non-negative")

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "origin": self.origin.value,
            "steps": self.steps,
            "verify_position": self.verify_position,
        }
        if self.x is not None:
            data["x"] = self.x
        if self.y is not None:
            data["y"] = self.y
        return data
