"""Host-authored browser operations and actions (model-neutral)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from dingdongditch.contract.target import (
    CardinalityPolicy,
    NameMatchMode,
    TargetConstraint,
    compile_name_regex,
    validate_constraint_list,
)


class LocatorStrategy(str, Enum):
    TEST_ID = "test_id"
    ROLE_NAME = "role_name"
    PLACEHOLDER = "placeholder"
    EXACT_TEXT = "exact_text"
    CSS = "css"


@dataclass(frozen=True)
class Locator:
    """Host-declared element target. No healing or inference.

    Optional ``constraints`` narrow the primary match set in declaration order.
    For ``role_name``, ``name_match`` defaults to ``contains`` to preserve the
    Playwright substring behavior; hosts must set ``exact`` or
    ``regex`` explicitly when that is intended.
    """

    strategy: LocatorStrategy
    value: str = ""
    role: str | None = None
    name: str | None = None
    name_match: NameMatchMode | None = None
    constraints: tuple[TargetConstraint, ...] = ()

    def validate(
        self,
        *,
        within_depth: int = 0,
        seen_ids: frozenset[int] | None = None,
    ) -> None:
        my_id = id(self)
        seen = set(seen_ids or ())
        if my_id in seen:
            raise ValueError("circular within target definition")
        seen.add(my_id)

        if self.strategy == LocatorStrategy.ROLE_NAME:
            if not self.role or not self.name:
                raise ValueError("role_name locator requires role and name")
            mode = self.name_match if self.name_match is not None else NameMatchMode.CONTAINS
            if mode == NameMatchMode.REGEX:
                compile_name_regex(self.name)
        elif self.strategy in (
            LocatorStrategy.TEST_ID,
            LocatorStrategy.PLACEHOLDER,
            LocatorStrategy.EXACT_TEXT,
            LocatorStrategy.CSS,
        ):
            if not self.value:
                raise ValueError(f"{self.strategy.value} locator requires value")
            if self.name_match is not None:
                raise ValueError("name_match is only valid for role_name locators")
            if self.role is not None or self.name is not None:
                raise ValueError(
                    f"{self.strategy.value} locator must not include role/name fields"
                )
        else:
            raise ValueError(f"unsupported locator strategy: {self.strategy}")

        validate_constraint_list(
            self.constraints,
            within_depth=within_depth,
            seen_ids=frozenset(seen),
        )

    def resolved_name_match(self) -> NameMatchMode | None:
        if self.strategy != LocatorStrategy.ROLE_NAME:
            return None
        return self.name_match if self.name_match is not None else NameMatchMode.CONTAINS

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {"strategy": self.strategy.value}
        if self.strategy == LocatorStrategy.ROLE_NAME:
            data["role"] = self.role
            data["name"] = self.name
            data["name_match"] = self.resolved_name_match().value  # type: ignore[union-attr]
        else:
            data["value"] = self.value
        if self.constraints:
            data["constraints"] = [c.describe() for c in self.constraints]
        return data


from dingdongditch.contract.wait import (  # noqa: E402
    TARGET_BASED_WAIT_CONDITIONS,
    WaitCondition,
    validate_wait_timeout_ms,
)


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    PRESS_KEY = "press_key"
    SELECT_OPTION = "select_option"
    SET_CHECKED = "set_checked"
    HOVER = "hover"
    SCROLL_TO_TARGET = "scroll_to_target"
    POINTER_MOVE = "pointer_move"
    WAIT_FOR = "wait_for"
    SWITCH_TO_PAGE = "switch_to_page"
    CLOSE_PAGE = "close_page"
    SWITCH_TO_OPENER = "switch_to_opener"
    DOWNLOAD = "download"


class KeyPressScope(str, Enum):
    """Where press_key dispatches. Default safer form is target."""

    TARGET = "target"
    ACTIVE_PAGE = "active_page"


class SelectMode(str, Enum):
    """How select_option identifies the option. Index is intentionally unsupported."""

    VALUE = "value"
    LABEL = "label"
    VALUES = "values"


# Named keys accepted for press_key (Playwright key names). Chords use '+'.
_NAMED_KEYS = frozenset(
    {
        "Enter",
        "Tab",
        "Escape",
        "Backspace",
        "Delete",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Space",
        "Control",
        "Alt",
        "Shift",
        "Meta",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
        "F7",
        "F8",
        "F9",
        "F10",
        "F11",
        "F12",
    }
)
_SINGLE_CHAR = re.compile(r"^\S$")


def validate_key_string(key: str) -> None:
    """Reject empty/malformed keys. Does not rewrite Control↔Meta."""
    if not key or not str(key).strip():
        raise ValueError("press_key requires a non-empty key")
    if key != key.strip():
        raise ValueError("press_key key must not have leading/trailing whitespace")
    if " " in key:
        raise ValueError("press_key key must not contain spaces; use '+' for chords")
    parts = key.split("+")
    if any(not p for p in parts):
        raise ValueError("malformed key chord")
    for part in parts:
        if part in _NAMED_KEYS:
            continue
        if _SINGLE_CHAR.match(part):
            continue
        raise ValueError(f"unsupported or malformed key token: {part!r}")


TARGET_BASED_ACTIONS = frozenset(
    {
        ActionType.CLICK,
        ActionType.FILL,
        ActionType.SELECT_OPTION,
        ActionType.SET_CHECKED,
        ActionType.HOVER,
        ActionType.SCROLL_TO_TARGET,
    }
)


# Actions that may declare an optional same-page iframe scope.
FRAME_SCOPED_ACTIONS = frozenset(
    {
        ActionType.CLICK,
        ActionType.FILL,
        ActionType.PRESS_KEY,
        ActionType.SELECT_OPTION,
        ActionType.SET_CHECKED,
        ActionType.HOVER,
        ActionType.SCROLL_TO_TARGET,
        ActionType.POINTER_MOVE,
    }
)


@dataclass(frozen=True)
class Action:
    """Host-declared browser action. Engine-neutral; no Playwright types."""

    type: ActionType
    locator: Locator | None = None
    text: str | None = None
    # press_key
    key: str | None = None
    key_scope: KeyPressScope | None = None
    # select_option — exactly one of option_value / option_label / option_values
    option_value: str | None = None
    option_label: str | None = None
    option_values: tuple[str, ...] | None = None
    # set_checked
    checked: bool | None = None
    # wait_for
    wait_condition: WaitCondition | None = None
    wait_timeout_ms: int | None = None
    # Optional same-page iframe element (main document). Nested frames unsupported.
    frame: Locator | None = None
    # Explicit page-management actions.
    page_id: str | None = None
    download_request: Any | None = None
    pointer_request: Any | None = None

    def validate(self) -> None:
        if self.type != ActionType.DOWNLOAD and self.download_request is not None:
            raise ValueError(f"{self.type.value} must not include download_request")
        if self.type != ActionType.POINTER_MOVE and self.pointer_request is not None:
            raise ValueError(f"{self.type.value} must not include pointer_request")
        if self.type == ActionType.NAVIGATE:
            self._forbid_locator_text_key_select_checked()
            self._forbid_wait_fields()
            self._forbid_frame()
            if self.locator is not None:
                raise ValueError("navigate action must not include a locator")
            if self.text is not None:
                raise ValueError("navigate action must not include text")
        elif self.type == ActionType.CLICK:
            self._require_locator()
            self._forbid_text_key_select_checked()
            self._forbid_wait_fields()
            self._validate_optional_frame()
            if self.text is not None:
                raise ValueError("click action must not include text")
        elif self.type == ActionType.FILL:
            self._require_locator()
            self._forbid_key_select_checked()
            self._forbid_wait_fields()
            self._validate_optional_frame()
            if self.text is None:
                raise ValueError("fill action requires text")
        elif self.type == ActionType.PRESS_KEY:
            self._forbid_text_select_checked()
            self._forbid_wait_fields()
            if self.key is None:
                raise ValueError("press_key requires key")
            validate_key_string(self.key)
            scope = self.key_scope if self.key_scope is not None else KeyPressScope.TARGET
            if scope == KeyPressScope.TARGET:
                if self.locator is None:
                    raise ValueError("press_key with scope=target requires a locator")
                self.locator.validate()
                self._validate_optional_frame()
            elif scope == KeyPressScope.ACTIVE_PAGE:
                if self.locator is not None:
                    raise ValueError(
                        "press_key with scope=active_page must not include a locator"
                    )
                self._forbid_frame()
            else:
                raise ValueError(f"invalid key_scope: {scope!r}")
        elif self.type == ActionType.SELECT_OPTION:
            self._require_locator()
            self._forbid_text_key_checked()
            self._forbid_wait_fields()
            self._validate_optional_frame()
            has_value = self.option_value is not None
            has_label = self.option_label is not None
            has_values = self.option_values is not None
            modes = sum(1 for flag in (has_value, has_label, has_values) if flag)
            if modes != 1:
                raise ValueError(
                    "select_option requires exactly one of "
                    "option_value, option_label, or option_values"
                )
            if has_value and (
                not isinstance(self.option_value, str) or not self.option_value
            ):
                raise ValueError("option_value must be a non-empty string")
            if has_label and (
                not isinstance(self.option_label, str) or not self.option_label
            ):
                raise ValueError("option_label must be a non-empty string")
            if has_values:
                if not isinstance(self.option_values, (list, tuple)):
                    raise ValueError("option_values must be a list of strings")
                if len(self.option_values) == 0:
                    raise ValueError("option_values must be a non-empty list")
                for item in self.option_values:
                    if not isinstance(item, str) or not item:
                        raise ValueError(
                            "option_values entries must be non-empty strings"
                        )
        elif self.type == ActionType.SET_CHECKED:
            self._require_locator()
            self._forbid_text_key_select()
            self._forbid_wait_fields()
            self._validate_optional_frame()
            if self.checked is None:
                raise ValueError("set_checked requires checked boolean")
            if not isinstance(self.checked, bool):
                raise ValueError("set_checked checked must be a bool")
        elif self.type == ActionType.HOVER:
            self._require_locator()
            self._forbid_text_key_select_checked()
            self._forbid_wait_fields()
            self._validate_optional_frame()
        elif self.type == ActionType.SCROLL_TO_TARGET:
            self._require_locator()
            self._forbid_text_key_select_checked()
            self._forbid_wait_fields()
            self._validate_optional_frame()
        elif self.type == ActionType.POINTER_MOVE:
            from dingdongditch.contract.pointer import PointerMoveRequest, PointerOrigin

            if not isinstance(self.pointer_request, PointerMoveRequest):
                raise ValueError("pointer_move action requires a PointerMoveRequest")
            self.pointer_request.validate()
            self._forbid_text_key_select_checked()
            self._forbid_wait_fields()
            if self.page_id is not None:
                raise ValueError("pointer_move must not include page_id")
            if self.pointer_request.origin == PointerOrigin.VIEWPORT:
                if self.locator is not None:
                    raise ValueError(
                        "viewport pointer_move must not include a locator"
                    )
                self._forbid_frame()
            else:
                self._require_locator()
                self._validate_optional_frame()
        elif self.type == ActionType.WAIT_FOR:
            self._forbid_text_key_select_checked_key_scope()
            if self.locator is not None:
                raise ValueError(
                    "wait_for must declare the target on wait_condition, not action.locator"
                )
            if self.frame is not None:
                raise ValueError(
                    "wait_for must declare frame on wait_condition, not action.frame"
                )
            if self.wait_condition is None:
                raise ValueError("wait_for requires wait_condition")
            self.wait_condition.validate()
            validate_wait_timeout_ms(self.wait_timeout_ms)
            # Target-based waits use wait_condition.locator (+ optional frame).
        elif self.type in (ActionType.SWITCH_TO_PAGE, ActionType.CLOSE_PAGE):
            self._forbid_text_key_select_checked_key_scope()
            self._forbid_wait_fields()
            self._forbid_frame()
            if self.locator is not None:
                raise ValueError(f"{self.type.value} must not include a locator")
            if not self.page_id:
                raise ValueError(f"{self.type.value} requires page_id")
        elif self.type == ActionType.SWITCH_TO_OPENER:
            self._forbid_text_key_select_checked_key_scope()
            self._forbid_wait_fields()
            self._forbid_frame()
            if self.locator is not None or self.page_id is not None:
                raise ValueError("switch_to_opener must not include locator or page_id")
        elif self.type == ActionType.DOWNLOAD:
            from dingdongditch.contract.download import DownloadRequest
            if not isinstance(self.download_request, DownloadRequest):
                raise ValueError("download action requires a DownloadRequest")
            self.download_request.validate()
            self._require_locator()
            self._forbid_frame()
            if self.text is not None or self.checked is not None:
                raise ValueError("download action must not include text or checked")
            if any(v is not None for v in (self.key, self.key_scope, self.option_value, self.option_label, self.option_values, self.wait_condition, self.wait_timeout_ms, self.page_id)):
                raise ValueError("download trigger details must be declared on download_request")
        else:
            raise ValueError(f"unsupported action: {self.type}")

    def resolved_wait_timeout_ms(self) -> int:
        return validate_wait_timeout_ms(self.wait_timeout_ms)

    def resolved_key_scope(self) -> KeyPressScope:
        if self.key_scope is not None:
            return self.key_scope
        return KeyPressScope.TARGET

    def select_mode(self) -> SelectMode:
        if self.option_values is not None:
            return SelectMode.VALUES
        if self.option_value is not None:
            return SelectMode.VALUE
        return SelectMode.LABEL

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type.value}
        if self.locator is not None:
            data["locator"] = self.locator.describe()
        if self.frame is not None:
            data["frame"] = self.frame.describe()
        if self.text is not None:
            data["text"] = self.text
        if self.type == ActionType.PRESS_KEY:
            data["key"] = self.key
            data["key_scope"] = self.resolved_key_scope().value
        if self.type == ActionType.SELECT_OPTION:
            data["select_mode"] = self.select_mode().value
            if self.option_value is not None:
                data["option_value"] = self.option_value
            if self.option_label is not None:
                data["option_label"] = self.option_label
            if self.option_values is not None:
                data["option_values"] = list(self.option_values)
        if self.type == ActionType.SET_CHECKED:
            data["checked"] = self.checked
        if self.type == ActionType.WAIT_FOR:
            data["wait_condition"] = (
                self.wait_condition.describe() if self.wait_condition else None
            )
            data["wait_timeout_ms"] = self.resolved_wait_timeout_ms()
        if self.type in (ActionType.SWITCH_TO_PAGE, ActionType.CLOSE_PAGE):
            data["page_id"] = self.page_id
        if self.type == ActionType.DOWNLOAD:
            data["download_request"] = self.download_request.describe()
        if self.type == ActionType.POINTER_MOVE:
            data["pointer_request"] = self.pointer_request.describe()
        return data

    def _require_locator(self) -> None:
        if self.locator is None:
            raise ValueError(f"{self.type.value} action requires a locator")
        self.locator.validate()

    def _validate_optional_frame(self) -> None:
        if self.frame is not None:
            self.frame.validate()

    def _forbid_frame(self) -> None:
        if self.frame is not None:
            raise ValueError(f"{self.type.value} must not include a frame target")

    def _forbid_wait_fields(self) -> None:
        if self.wait_condition is not None or self.wait_timeout_ms is not None:
            raise ValueError(f"{self.type.value} must not include wait_for fields")

    def _forbid_text_key_select_checked_key_scope(self) -> None:
        self._forbid_text_key_select_checked()
        if self.key_scope is not None:
            raise ValueError(f"{self.type.value} must not include key_scope")

    def _forbid_key_select_checked(self) -> None:
        if self.key is not None or self.key_scope is not None:
            raise ValueError(f"{self.type.value} must not include key fields")
        if self.option_value is not None or self.option_label is not None or self.option_values is not None:
            raise ValueError(f"{self.type.value} must not include select option fields")
        if self.checked is not None:
            raise ValueError(f"{self.type.value} must not include checked")

    def _forbid_text_key_select_checked(self) -> None:
        if self.text is not None:
            raise ValueError(f"{self.type.value} must not include text")
        self._forbid_key_select_checked()

    def _forbid_text_key_select(self) -> None:
        if self.text is not None:
            raise ValueError(f"{self.type.value} must not include text")
        if self.key is not None or self.key_scope is not None:
            raise ValueError(f"{self.type.value} must not include key fields")
        if self.option_value is not None or self.option_label is not None or self.option_values is not None:
            raise ValueError(f"{self.type.value} must not include select option fields")

    def _forbid_text_key_checked(self) -> None:
        if self.text is not None:
            raise ValueError(f"{self.type.value} must not include text")
        if self.key is not None or self.key_scope is not None:
            raise ValueError(f"{self.type.value} must not include key fields")
        if self.checked is not None:
            raise ValueError(f"{self.type.value} must not include checked")

    def _forbid_text_select_checked(self) -> None:
        if self.text is not None:
            raise ValueError(f"{self.type.value} must not include text")
        if self.option_value is not None or self.option_label is not None or self.option_values is not None:
            raise ValueError(f"{self.type.value} must not include select option fields")
        if self.checked is not None:
            raise ValueError(f"{self.type.value} must not include checked")

    def _forbid_locator_text_key_select_checked(self) -> None:
        self._forbid_key_select_checked()


@dataclass(frozen=True)
class FreshnessPolicy:
    """Post-action evidence must be at/after action start; max_age_ms vs verify time."""

    max_age_ms: int = 5_000

    def validate(self) -> None:
        if self.max_age_ms < 1:
            raise ValueError("freshness.max_age_ms must be >= 1")


@dataclass(frozen=True)
class TargetPreparation:
    """Host permission for deterministic, nonessential target preparation."""

    dismiss_overlay_locators: tuple[Locator, ...] = ()

    def validate(self) -> None:
        for locator in self.dismiss_overlay_locators:
            locator.validate()

    def describe(self) -> dict[str, Any]:
        return {
            "dismiss_overlay_locators": [
                locator.describe() for locator in self.dismiss_overlay_locators
            ]
        }


@dataclass
class Operation:
    """Externally planned single browser operation."""

    operation_id: str
    url: str
    action: Action
    expectations: list[Any] = field(default_factory=list)
    timeout_ms: int = 10_000
    freshness: FreshnessPolicy = field(default_factory=FreshnessPolicy)
    require_unique_target: bool = True
    locate_retry_ms: int = 1_000
    cardinality: CardinalityPolicy = CardinalityPolicy.EXACTLY_ONE
    page_transition: Any | None = None
    dialog_contract: Any | None = None
    screenshot_config: Any | None = None
    page_precondition: Any | None = None
    target_preparation: TargetPreparation = field(default_factory=TargetPreparation)

    def validate(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id is required")
        if not self.url:
            raise ValueError("url is required")
        if self.timeout_ms < 100:
            raise ValueError("timeout_ms must be >= 100")
        if self.locate_retry_ms < 0:
            raise ValueError("locate_retry_ms must be >= 0")
        if self.cardinality != CardinalityPolicy.EXACTLY_ONE:
            raise ValueError(
                "only cardinality exactly_one is supported"
            )
        needs_unique = self.action.type in TARGET_BASED_ACTIONS or (
            self.action.type == ActionType.PRESS_KEY
            and self.action.resolved_key_scope() == KeyPressScope.TARGET
        ) or (
            self.action.type == ActionType.WAIT_FOR
            and self.action.wait_condition is not None
            and self.action.wait_condition.type in TARGET_BASED_WAIT_CONDITIONS
        ) or (
            self.action.type == ActionType.POINTER_MOVE
            and self.action.locator is not None
        )
        if needs_unique:
            if not self.require_unique_target:
                raise ValueError(
                    f"{self.action.type.value} requires require_unique_target=True"
                )
            if self.cardinality != CardinalityPolicy.EXACTLY_ONE:
                raise ValueError(
                    f"{self.action.type.value} requires cardinality exactly_one"
                )
        self.freshness.validate()
        self.target_preparation.validate()
        self.action.validate()
        from dingdongditch.contract.page import PageTransition, PageTransitionPolicy

        transition = self.page_transition or PageTransition()
        if not isinstance(transition, PageTransition):
            raise ValueError("page_transition must be a PageTransition")
        transition.validate()
        from dingdongditch.contract.dialog import DialogContract
        dialog = self.dialog_contract or DialogContract()
        if not isinstance(dialog, DialogContract):
            raise ValueError("dialog_contract must be a DialogContract")
        dialog.validate()
        from dingdongditch.contract.screenshot import ScreenshotConfig
        screenshot = self.screenshot_config or ScreenshotConfig()
        if not isinstance(screenshot, ScreenshotConfig):
            raise ValueError("screenshot_config must be a ScreenshotConfig")
        screenshot.validate()
        if self.page_precondition is not None:
            from dingdongditch.contract.page_precondition import PagePrecondition

            if not isinstance(self.page_precondition, PagePrecondition):
                raise ValueError("page_precondition must be a PagePrecondition")
            if self.action.type == ActionType.NAVIGATE:
                raise ValueError("navigate operations must not declare page_precondition")
            self.page_precondition.validate()
        if (
            transition.policy != PageTransitionPolicy.SAME_PAGE
            and self.action.type != ActionType.CLICK
        ):
            raise ValueError("new-page transitions are currently valid only for click")
        for expectation in self.expectations:
            expectation.validate()

    def to_public_dict(self) -> dict[str, Any]:
        from dingdongditch.contract.dialog import DialogContract
        from dingdongditch.contract.page import PageTransition
        from dingdongditch.contract.screenshot import ScreenshotConfig

        transition = self.page_transition or PageTransition()
        dialog = self.dialog_contract or DialogContract()
        screenshot = self.screenshot_config or ScreenshotConfig()
        return {
            "operation_id": self.operation_id,
            "url": self.url,
            "action": self.action.describe(),
            "timeout_ms": self.timeout_ms,
            "freshness": asdict(self.freshness),
            "require_unique_target": self.require_unique_target,
            "locate_retry_ms": self.locate_retry_ms,
            "cardinality": self.cardinality.value,
            "page_transition": transition.describe(),
            "dialog_contract": dialog.describe(),
            "screenshot_config": screenshot.describe(),
            "page_precondition": (
                self.page_precondition.describe()
                if self.page_precondition is not None
                else None
            ),
            "target_preparation": self.target_preparation.describe(),
        }
