from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.operation import Locator

# Re-export for stable public/test imports.
__all__ = [
    "ExpectationType",
    "Expectation",
    "UrlMatchMode",
    "TextMatchMode",
]


class ExpectationType(str, Enum):
    URL = "url"
    ELEMENT_EXISTS = "element_exists"
    ELEMENT_VISIBLE = "element_visible"
    ELEMENT_IN_VIEWPORT = "element_in_viewport"
    TEXT = "text"
    ATTRIBUTE = "attribute"
    NETWORK = "network"


@dataclass(frozen=True)
class Expectation:
    """Host-declared browser-observable expectation. Never invented by the runtime."""

    type: ExpectationType
    # URL
    url_value: str | None = None
    url_match: UrlMatchMode = UrlMatchMode.EXACT
    # Element / text / attribute
    locator: Locator | None = None
    exists: bool | None = None
    visible: bool | None = None
    in_viewport: bool | None = None
    text_value: str | None = None
    text_match: TextMatchMode = TextMatchMode.CONTAINS
    attribute_name: str | None = None
    attribute_value: str | None = None
    # Network
    network_url_substring: str | None = None
    network_method: str | None = None
    network_status: int | None = None
    expectation_id: str = ""
    # Optional same-page iframe scope for element expectations.
    frame: Locator | None = None

    def validate(self) -> None:
        if self.type == ExpectationType.URL:
            if not self.url_value:
                raise ValueError("url expectation requires url_value")
            if self.frame is not None:
                raise ValueError("url expectation must not include a frame")
        elif self.type == ExpectationType.ELEMENT_EXISTS:
            if self.locator is None or self.exists is None:
                raise ValueError("element_exists requires locator and exists")
            self.locator.validate()
            if self.frame is not None:
                self.frame.validate()
        elif self.type == ExpectationType.ELEMENT_VISIBLE:
            if self.locator is None or self.visible is None:
                raise ValueError("element_visible requires locator and visible")
            self.locator.validate()
            if self.frame is not None:
                self.frame.validate()
        elif self.type == ExpectationType.ELEMENT_IN_VIEWPORT:
            if self.locator is None or self.in_viewport is None:
                raise ValueError("element_in_viewport requires locator and in_viewport")
            self.locator.validate()
            if self.frame is not None:
                self.frame.validate()
        elif self.type == ExpectationType.TEXT:
            if self.locator is None or self.text_value is None:
                raise ValueError("text expectation requires locator and text_value")
            self.locator.validate()
            if self.frame is not None:
                self.frame.validate()
        elif self.type == ExpectationType.ATTRIBUTE:
            if self.locator is None or not self.attribute_name or self.attribute_value is None:
                raise ValueError("attribute expectation requires locator, attribute_name, attribute_value")
            self.locator.validate()
            if self.frame is not None:
                self.frame.validate()
        elif self.type == ExpectationType.NETWORK:
            if not self.network_url_substring:
                raise ValueError("network expectation requires network_url_substring")
            if self.frame is not None:
                raise ValueError("network expectation must not include a frame")

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "expectation_id": self.expectation_id,
            "type": self.type.value,
        }
        if self.frame is not None:
            data["frame"] = self.frame.describe()
        if self.type == ExpectationType.URL:
            data["url_value"] = self.url_value
            data["url_match"] = self.url_match.value
        elif self.type == ExpectationType.ELEMENT_EXISTS:
            data["locator"] = self.locator.describe() if self.locator else None
            data["exists"] = self.exists
        elif self.type == ExpectationType.ELEMENT_VISIBLE:
            data["locator"] = self.locator.describe() if self.locator else None
            data["visible"] = self.visible
        elif self.type == ExpectationType.ELEMENT_IN_VIEWPORT:
            data["locator"] = self.locator.describe() if self.locator else None
            data["in_viewport"] = self.in_viewport
        elif self.type == ExpectationType.TEXT:
            data["locator"] = self.locator.describe() if self.locator else None
            data["text_value"] = self.text_value
            data["text_match"] = self.text_match.value
        elif self.type == ExpectationType.ATTRIBUTE:
            data["locator"] = self.locator.describe() if self.locator else None
            data["attribute_name"] = self.attribute_name
            data["attribute_value"] = self.attribute_value
        elif self.type == ExpectationType.NETWORK:
            data["network_url_substring"] = self.network_url_substring
            data["network_method"] = self.network_method
            data["network_status"] = self.network_status
        return data
