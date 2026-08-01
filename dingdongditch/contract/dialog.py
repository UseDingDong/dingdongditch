"""Typed host-declared native browser-dialog contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DialogType(str, Enum):
    ALERT = "alert"
    CONFIRM = "confirm"
    PROMPT = "prompt"
    BEFOREUNLOAD = "beforeunload"


class DialogAction(str, Enum):
    ACCEPT = "accept"
    DISMISS = "dismiss"


class DialogRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True)
class DialogContract:
    """One deterministic dialog policy for one triggering operation."""

    requirement: DialogRequirement = DialogRequirement.FORBIDDEN
    dialog_type: DialogType | None = None
    message: str | None = None
    message_contains: bool = False
    action: DialogAction = DialogAction.DISMISS
    prompt_text: str | None = None
    timeout_ms: int = 1_000
    redact_prompt_text: bool = False

    def validate(self) -> None:
        if self.timeout_ms < 1:
            raise ValueError("dialog timeout_ms must be >= 1")
        if self.requirement != DialogRequirement.FORBIDDEN and self.dialog_type is None:
            raise ValueError("dialog_type is required unless dialogs are forbidden")
        if self.message_contains and self.message is None:
            raise ValueError("message_contains requires message")
        if self.prompt_text is not None and self.dialog_type != DialogType.PROMPT:
            raise ValueError("prompt_text is only valid for prompt dialogs")
        if self.dialog_type == DialogType.PROMPT and self.action == DialogAction.ACCEPT:
            if self.prompt_text is None:
                raise ValueError("accepting a prompt requires prompt_text")

    def describe(self) -> dict[str, Any]:
        self.validate()
        return {
            "requirement": self.requirement.value,
            "dialog_type": self.dialog_type.value if self.dialog_type else None,
            "message": self.message,
            "message_match": "contains" if self.message_contains else "exact",
            "action": self.action.value,
            "prompt_text_supplied": self.prompt_text is not None,
            "prompt_text": "[REDACTED]" if self.redact_prompt_text and self.prompt_text else self.prompt_text,
            "timeout_ms": self.timeout_ms,
        }
