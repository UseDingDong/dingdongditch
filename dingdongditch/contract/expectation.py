from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.network import NetworkUrlMatchMode
from dingdongditch.contract.operation import Locator, MAX_FRAME_PATH_DEPTH

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
    UPLOAD_FILE_NAMES = "upload_file_names"
    UPLOAD_FILE_COUNT = "upload_file_count"


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
    # ``network_url_substring`` keeps the existing contains semantics.  The
    # additional fields make request/response evidence explicit without
    # allowing arbitrary predicates or URL-query inspection.
    network_url_match: NetworkUrlMatchMode = NetworkUrlMatchMode.CONTAINS
    network_request_observed: bool = True
    network_response_observed: bool | None = None
    network_max_elapsed_ms: int | None = None
    file_names: tuple[str, ...] | None = None
    file_count: int | None = None
    expectation_id: str = ""
    # Legacy one-hop scope; frame_path is the explicit nested replacement.
    frame: Locator | None = None
    frame_path: tuple[Locator, ...] = ()

    def validate(self) -> None:
        target_scoped = {
            ExpectationType.ELEMENT_EXISTS,
            ExpectationType.ELEMENT_VISIBLE,
            ExpectationType.ELEMENT_IN_VIEWPORT,
            ExpectationType.TEXT,
            ExpectationType.ATTRIBUTE,
            ExpectationType.UPLOAD_FILE_NAMES,
            ExpectationType.UPLOAD_FILE_COUNT,
        }
        if self.type in target_scoped:
            self._validate_frame_scope()
        elif self.frame is not None or self.frame_path:
            raise ValueError(f"{self.type.value} expectation must not include a frame scope")
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
            if not isinstance(self.network_url_match, NetworkUrlMatchMode):
                raise ValueError("network_url_match must be a NetworkUrlMatchMode")
            if "?" in self.network_url_substring or "#" in self.network_url_substring:
                raise ValueError(
                    "network URL matching must not include query strings or fragments"
                )
            if not isinstance(self.network_request_observed, bool):
                raise ValueError("network_request_observed must be a bool")
            if self.network_response_observed is not None and not isinstance(
                self.network_response_observed, bool
            ):
                raise ValueError("network_response_observed must be a bool or None")
            if self.network_status is not None:
                if (
                    not isinstance(self.network_status, int)
                    or isinstance(self.network_status, bool)
                    or not 100 <= self.network_status <= 599
                ):
                    raise ValueError("network_status must be an HTTP status from 100 through 599")
            if self.network_method is not None:
                if not self.network_method.isalpha() or self.network_method != self.network_method.upper():
                    raise ValueError("network_method must be an uppercase HTTP method")
            if self.network_max_elapsed_ms is not None:
                if (
                    not isinstance(self.network_max_elapsed_ms, int)
                    or isinstance(self.network_max_elapsed_ms, bool)
                    or not 0 <= self.network_max_elapsed_ms <= 300_000
                ):
                    raise ValueError("network_max_elapsed_ms must be between 0 and 300000")
                if self.network_response_observed is False:
                    raise ValueError("network timing requires a response observation")
            if self.network_status is not None and self.network_response_observed is False:
                raise ValueError("network_status requires a response observation")
            if not self.network_request_observed and self.network_response_observed is not True:
                raise ValueError("network expectation must require a request or response observation")
            if self.frame is not None:
                raise ValueError("network expectation must not include a frame")
        elif self.type == ExpectationType.UPLOAD_FILE_NAMES:
            if self.locator is None or not self.file_names:
                raise ValueError("upload_file_names requires locator and non-empty file_names")
            if any(not isinstance(item, str) or not item for item in self.file_names):
                raise ValueError("upload_file_names entries must be non-empty strings")
            self.locator.validate()
            if self.frame is not None:
                self.frame.validate()
        elif self.type == ExpectationType.UPLOAD_FILE_COUNT:
            if self.locator is None or not isinstance(self.file_count, int) or isinstance(self.file_count, bool) or self.file_count < 0:
                raise ValueError("upload_file_count requires locator and non-negative file_count")
            self.locator.validate()
            if self.frame is not None:
                self.frame.validate()

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "expectation_id": self.expectation_id,
            "type": self.type.value,
        }
        if self.frame is not None:
            data["frame"] = self.frame.describe()
        if self.frame_path:
            data["frame_path"] = [frame.describe() for frame in self.frame_path]
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
            data["network_url_match"] = self.network_url_match.value
            data["network_request_observed"] = self.network_request_observed
            data["network_response_observed"] = self.network_response_observed
            data["network_max_elapsed_ms"] = self.network_max_elapsed_ms
        elif self.type == ExpectationType.UPLOAD_FILE_NAMES:
            data["locator"] = self.locator.describe() if self.locator else None
            data["file_names"] = list(self.file_names or ())
        elif self.type == ExpectationType.UPLOAD_FILE_COUNT:
            data["locator"] = self.locator.describe() if self.locator else None
            data["file_count"] = self.file_count
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
