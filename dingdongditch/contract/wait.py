"""Host-authored wait conditions (model-neutral; no Playwright types)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.operation import Locator, MAX_FRAME_PATH_DEPTH

DEFAULT_WAIT_TIMEOUT_MS = 5_000
MIN_WAIT_TIMEOUT_MS = 100
MAX_WAIT_TIMEOUT_MS = 60_000
WAIT_POLL_INTERVAL_MS = 50


class WaitConditionType(str, Enum):
    ELEMENT_VISIBLE = "element_visible"
    ELEMENT_HIDDEN = "element_hidden"
    TEXT_PRESENT = "text_present"
    URL_MATCHES = "url_matches"
    ATTRIBUTE_EQUALS = "attribute_equals"
    VALUE_EQUALS = "value_equals"
    CHECKED_EQUALS = "checked_equals"
    SELECTED_VALUE_EQUALS = "selected_value_equals"
    ELEMENT_IN_VIEWPORT = "element_in_viewport"
    LOAD_STATE = "load_state"
    VIDEO_ENDED = "video_ended"
    VIDEO_PLAYING = "video_playing"
    VIDEO_COMPLETED_ONCE = "video_completed_once"


class LoadState(str, Enum):
    """Explicit document load states. networkidle is intentionally unsupported."""

    DOMCONTENTLOADED = "domcontentloaded"
    LOAD = "load"


TARGET_BASED_WAIT_CONDITIONS = frozenset(
    {
        WaitConditionType.ELEMENT_VISIBLE,
        WaitConditionType.ELEMENT_HIDDEN,
        WaitConditionType.TEXT_PRESENT,
        WaitConditionType.ATTRIBUTE_EQUALS,
        WaitConditionType.VALUE_EQUALS,
        WaitConditionType.CHECKED_EQUALS,
        WaitConditionType.SELECTED_VALUE_EQUALS,
        WaitConditionType.ELEMENT_IN_VIEWPORT,
        WaitConditionType.VIDEO_ENDED,
        WaitConditionType.VIDEO_PLAYING,
        WaitConditionType.VIDEO_COMPLETED_ONCE,
    }
)


@dataclass(frozen=True)
class WaitCondition:
    """One declared observable condition for wait_for.

    element_hidden policy: a uniquely resolved element that is not visible
    satisfies the condition; zero matches (detached / absent) also satisfy
    hidden. Ambiguous matches fail closed and never count as hidden.

    video_ended observes HTMLMediaElement.ended on a uniquely resolved same-
    document HTML5 ``<video>``. YouTube/Vimeo/iframe/native-control-only
    players are unsupported. When ``frame`` is set, the video must live in that
    declared iframe document (still HTML5 ``<video>``, not embed players).
    """

    type: WaitConditionType
    locator: Locator | None = None
    text_value: str | None = None
    text_match: TextMatchMode = TextMatchMode.CONTAINS
    url_value: str | None = None
    url_match: UrlMatchMode = UrlMatchMode.CONTAINS
    attribute_name: str | None = None
    attribute_value: str | None = None
    value: str | None = None
    checked: bool | None = None
    selected_value: str | None = None
    in_viewport: bool | None = None
    load_state: LoadState | None = None
    # Legacy one-hop scope; frame_path explicitly declares nested hops.
    frame: Locator | None = None
    frame_path: tuple[Locator, ...] = ()

    def validate(self) -> None:
        if self.type in TARGET_BASED_WAIT_CONDITIONS:
            if self.locator is None:
                raise ValueError(f"{self.type.value} wait requires a locator")
            self.locator.validate()
            self._validate_frame_scope()
        else:
            if self.locator is not None:
                raise ValueError(f"{self.type.value} wait must not include a locator")
            if self.frame is not None or self.frame_path:
                raise ValueError(
                    f"{self.type.value} wait is page-scoped and must not include a frame scope"
                )

        extras = {
            "text_value": self.text_value,
            "url_value": self.url_value,
            "attribute_name": self.attribute_name,
            "attribute_value": self.attribute_value,
            "value": self.value,
            "checked": self.checked,
            "selected_value": self.selected_value,
            "in_viewport": self.in_viewport,
            "load_state": self.load_state,
        }

        def only(*allowed: str) -> None:
            for name, val in extras.items():
                if name in allowed:
                    continue
                # Defaults that are always present on the dataclass
                if name == "text_value" and val is None:
                    continue
                if name in (
                    "url_value",
                    "attribute_name",
                    "attribute_value",
                    "value",
                    "checked",
                    "selected_value",
                    "in_viewport",
                    "load_state",
                ) and val is None:
                    continue
                if val is not None and name not in allowed:
                    # text_match / url_match always exist; only flag payload fields
                    raise ValueError(f"{self.type.value} must not include {name}")

        if self.type in (
            WaitConditionType.ELEMENT_VISIBLE,
            WaitConditionType.ELEMENT_HIDDEN,
        ):
            only()
        elif self.type == WaitConditionType.TEXT_PRESENT:
            if self.text_value is None or not isinstance(self.text_value, str):
                raise ValueError("text_present requires text_value string")
            if not isinstance(self.text_match, TextMatchMode):
                raise ValueError("text_match must be a TextMatchMode")
            only("text_value")
        elif self.type == WaitConditionType.URL_MATCHES:
            if not self.url_value:
                raise ValueError("url_matches requires url_value")
            if not isinstance(self.url_match, UrlMatchMode):
                raise ValueError("url_match must be a UrlMatchMode")
            only("url_value")
        elif self.type == WaitConditionType.ATTRIBUTE_EQUALS:
            if not self.attribute_name or self.attribute_value is None:
                raise ValueError(
                    "attribute_equals requires attribute_name and attribute_value"
                )
            only("attribute_name", "attribute_value")
        elif self.type == WaitConditionType.VALUE_EQUALS:
            if self.value is None or not isinstance(self.value, str):
                raise ValueError("value_equals requires value string")
            only("value")
        elif self.type == WaitConditionType.CHECKED_EQUALS:
            if self.checked is None or not isinstance(self.checked, bool):
                raise ValueError("checked_equals requires checked bool")
            only("checked")
        elif self.type == WaitConditionType.SELECTED_VALUE_EQUALS:
            if self.selected_value is None or not isinstance(self.selected_value, str):
                raise ValueError("selected_value_equals requires selected_value string")
            only("selected_value")
        elif self.type == WaitConditionType.ELEMENT_IN_VIEWPORT:
            if self.in_viewport is None or not isinstance(self.in_viewport, bool):
                raise ValueError("element_in_viewport requires in_viewport bool")
            only("in_viewport")
        elif self.type == WaitConditionType.LOAD_STATE:
            if self.load_state is None or not isinstance(self.load_state, LoadState):
                raise ValueError("load_state requires load_state enum")
            only("load_state")
        elif self.type in (
            WaitConditionType.VIDEO_ENDED,
            WaitConditionType.VIDEO_PLAYING,
            WaitConditionType.VIDEO_COMPLETED_ONCE,
        ):
            only()
        else:
            raise ValueError(f"unsupported wait condition: {self.type}")

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type.value}
        if self.locator is not None:
            data["locator"] = self.locator.describe()
        if self.frame is not None:
            data["frame"] = self.frame.describe()
        if self.frame_path:
            data["frame_path"] = [frame.describe() for frame in self.frame_path]
        if self.type == WaitConditionType.TEXT_PRESENT:
            data["text_value"] = self.text_value
            data["text_match"] = self.text_match.value
        elif self.type == WaitConditionType.URL_MATCHES:
            data["url_value"] = self.url_value
            data["url_match"] = self.url_match.value
        elif self.type == WaitConditionType.ATTRIBUTE_EQUALS:
            data["attribute_name"] = self.attribute_name
            data["attribute_value"] = self.attribute_value
        elif self.type == WaitConditionType.VALUE_EQUALS:
            data["value"] = self.value
        elif self.type == WaitConditionType.CHECKED_EQUALS:
            data["checked"] = self.checked
        elif self.type == WaitConditionType.SELECTED_VALUE_EQUALS:
            data["selected_value"] = self.selected_value
        elif self.type == WaitConditionType.ELEMENT_IN_VIEWPORT:
            data["in_viewport"] = self.in_viewport
        elif self.type == WaitConditionType.LOAD_STATE:
            data["load_state"] = self.load_state.value if self.load_state else None
        elif self.type in (
            WaitConditionType.VIDEO_ENDED,
            WaitConditionType.VIDEO_PLAYING,
            WaitConditionType.VIDEO_COMPLETED_ONCE,
        ):
            pass
        return data

    def _validate_frame_scope(self) -> None:
        if self.frame is not None and self.frame_path:
            raise ValueError("frame and frame_path are mutually exclusive")
        if self.frame is not None:
            self.frame.validate()
        if len(self.frame_path) > MAX_FRAME_PATH_DEPTH:
            raise ValueError(
                f"frame_path supports at most {MAX_FRAME_PATH_DEPTH} declared hops"
            )
        for frame in self.frame_path:
            if not isinstance(frame, Locator):
                raise ValueError("frame_path entries must be Locator values")
            frame.validate()

    def resolved_frame_path(self) -> tuple[Locator, ...]:
        if self.frame_path:
            return self.frame_path
        return (self.frame,) if self.frame is not None else ()


def validate_wait_timeout_ms(timeout_ms: int | None) -> int:
    """Resolve default and bound wait timeouts. Returns effective timeout_ms."""
    if timeout_ms is None:
        return DEFAULT_WAIT_TIMEOUT_MS
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        raise ValueError("wait_timeout_ms must be an int")
    if timeout_ms < MIN_WAIT_TIMEOUT_MS:
        raise ValueError(f"wait_timeout_ms must be >= {MIN_WAIT_TIMEOUT_MS}")
    if timeout_ms > MAX_WAIT_TIMEOUT_MS:
        raise ValueError(f"wait_timeout_ms must be <= {MAX_WAIT_TIMEOUT_MS}")
    return timeout_ms
