"""Typed, deterministic current-page preconditions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from dingdongditch.contract.operation import Locator


MAX_PAGE_CONDITIONS = 32


class PageConditionType(str, Enum):
    EXACT_URL = "exact_url"
    ORIGIN_EQUALS = "origin_equals"
    PATH_EQUALS = "path_equals"
    PATH_STARTS_WITH = "path_starts_with"
    QUERY_PARAM_EQUALS = "query_param_equals"
    ELEMENT_VISIBLE = "element_visible"


class FragmentPolicy(str, Enum):
    IGNORE = "ignore"
    INCLUDE = "include"


class PageConditionResultValue(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class PageCondition:
    condition_id: str
    type: PageConditionType
    url_value: str | None = None
    fragment_policy: FragmentPolicy = FragmentPolicy.IGNORE
    origin_value: str | None = None
    path_value: str | None = None
    query_name: str | None = None
    query_value: str | None = None
    locator: Locator | None = None
    frame: Locator | None = None

    def validate(self) -> None:
        if not isinstance(self.condition_id, str) or not self.condition_id.strip():
            raise ValueError("page condition_id is required")
        if not isinstance(self.type, PageConditionType):
            raise ValueError("invalid page condition type")
        allowed: dict[PageConditionType, frozenset[str]] = {
            PageConditionType.EXACT_URL: frozenset({"url_value", "fragment_policy"}),
            PageConditionType.ORIGIN_EQUALS: frozenset({"origin_value"}),
            PageConditionType.PATH_EQUALS: frozenset({"path_value"}),
            PageConditionType.PATH_STARTS_WITH: frozenset({"path_value"}),
            PageConditionType.QUERY_PARAM_EQUALS: frozenset(
                {"query_name", "query_value"}
            ),
            PageConditionType.ELEMENT_VISIBLE: frozenset({"locator", "frame"}),
        }
        values = {
            "url_value": self.url_value,
            "origin_value": self.origin_value,
            "path_value": self.path_value,
            "query_name": self.query_name,
            "query_value": self.query_value,
            "locator": self.locator,
            "frame": self.frame,
        }
        permitted = allowed[self.type]
        for name, value in values.items():
            if value is not None and name not in permitted:
                raise ValueError(f"{self.type.value} must not include {name}")
        if self.type != PageConditionType.EXACT_URL and (
            self.fragment_policy != FragmentPolicy.IGNORE
        ):
            raise ValueError(
                f"{self.type.value} must not include non-default fragment_policy"
            )

        if self.type == PageConditionType.EXACT_URL:
            if not isinstance(self.url_value, str) or not self.url_value:
                raise ValueError("exact_url requires url_value")
            parsed = urlsplit(self.url_value)
            if not parsed.scheme:
                raise ValueError("exact_url requires an absolute URL")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("exact_url must not include userinfo")
            if parsed.scheme.lower() in {"http", "https"} and not parsed.hostname:
                raise ValueError("exact_url http(s) URL requires a host")
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("exact_url contains invalid port") from exc
        elif self.type == PageConditionType.ORIGIN_EQUALS:
            normalize_origin(self.origin_value)
        elif self.type in (
            PageConditionType.PATH_EQUALS,
            PageConditionType.PATH_STARTS_WITH,
        ):
            if (
                not isinstance(self.path_value, str)
                or not self.path_value
                or not self.path_value.startswith("/")
            ):
                raise ValueError(f"{self.type.value} requires path_value starting with /")
            if "?" in self.path_value or "#" in self.path_value:
                raise ValueError(f"{self.type.value} path_value must not contain ? or #")
            if (
                self.type == PageConditionType.PATH_STARTS_WITH
                and self.path_value == "/"
            ):
                raise ValueError("path_starts_with rejects / alone")
        elif self.type == PageConditionType.QUERY_PARAM_EQUALS:
            if not isinstance(self.query_name, str) or not self.query_name:
                raise ValueError("query_param_equals requires non-empty query_name")
            if not isinstance(self.query_value, str):
                raise ValueError("query_param_equals requires query_value string")
        elif self.type == PageConditionType.ELEMENT_VISIBLE:
            if not isinstance(self.locator, Locator):
                raise ValueError("element_visible requires locator")
            self.locator.validate()
            if self.frame is not None:
                if not isinstance(self.frame, Locator):
                    raise ValueError("element_visible frame must be a Locator")
                self.frame.validate()

    def describe(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "condition_id": self.condition_id,
            "type": self.type.value,
        }
        if self.type == PageConditionType.EXACT_URL:
            data["url_value"] = self.url_value
            data["fragment_policy"] = self.fragment_policy.value
        elif self.type == PageConditionType.ORIGIN_EQUALS:
            data["origin_value"] = self.origin_value
        elif self.type in (
            PageConditionType.PATH_EQUALS,
            PageConditionType.PATH_STARTS_WITH,
        ):
            data["path_value"] = self.path_value
        elif self.type == PageConditionType.QUERY_PARAM_EQUALS:
            data["query_name"] = self.query_name
            data["query_value"] = self.query_value
        elif self.type == PageConditionType.ELEMENT_VISIBLE:
            data["locator"] = self.locator.describe() if self.locator else None
            if self.frame is not None:
                data["frame"] = self.frame.describe()
        return data


@dataclass(frozen=True)
class PagePrecondition:
    conditions: tuple[PageCondition, ...]
    logic: str = "all"

    def validate(self) -> None:
        if self.logic != "all":
            raise ValueError("page_precondition logic must be all")
        if not self.conditions:
            raise ValueError("page_precondition conditions must not be empty")
        if len(self.conditions) > MAX_PAGE_CONDITIONS:
            raise ValueError(
                f"page_precondition supports at most {MAX_PAGE_CONDITIONS} conditions"
            )
        ids = [condition.condition_id for condition in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("page_precondition condition_id values must be unique")
        for condition in self.conditions:
            condition.validate()

        types = {condition.type for condition in self.conditions}
        structural = {
            PageConditionType.PATH_EQUALS,
            PageConditionType.PATH_STARTS_WITH,
            PageConditionType.QUERY_PARAM_EQUALS,
        }
        if types & structural and not types & {
            PageConditionType.EXACT_URL,
            PageConditionType.ORIGIN_EQUALS,
        }:
            raise ValueError(
                "path/query page conditions require exact_url or origin_equals"
            )
        self._validate_contradictions()

    def _validate_contradictions(self) -> None:
        def unique_values(
            ctype: PageConditionType, attribute: str
        ) -> set[str]:
            return {
                str(getattr(condition, attribute))
                for condition in self.conditions
                if condition.type == ctype
            }

        exact_conditions = [
            condition
            for condition in self.conditions
            if condition.type == PageConditionType.EXACT_URL
        ]
        included_urls = {
            condition.url_value
            for condition in exact_conditions
            if condition.fragment_policy == FragmentPolicy.INCLUDE
        }
        ignored_urls = {
            _without_fragment(condition.url_value)
            for condition in exact_conditions
        }
        if len(included_urls) > 1 or len(ignored_urls) > 1:
            raise ValueError("contradictory exact_url conditions")
        origins = {
            normalize_origin(condition.origin_value)
            for condition in self.conditions
            if condition.type == PageConditionType.ORIGIN_EQUALS
        }
        if len(origins) > 1:
            raise ValueError("contradictory origin_equals conditions")
        exact_paths = unique_values(PageConditionType.PATH_EQUALS, "path_value")
        if len(exact_paths) > 1:
            raise ValueError("contradictory path_equals conditions")
        prefixes = unique_values(PageConditionType.PATH_STARTS_WITH, "path_value")
        if any(
            not (left.startswith(right) or right.startswith(left))
            for left in prefixes
            for right in prefixes
        ):
            raise ValueError("contradictory path_starts_with conditions")
        if exact_paths:
            exact_path = next(iter(exact_paths))
            if any(not exact_path.startswith(prefix) for prefix in prefixes):
                raise ValueError(
                    "path_equals contradicts path_starts_with condition"
                )
        query_values: dict[str, set[str]] = {}
        for condition in self.conditions:
            if condition.type == PageConditionType.QUERY_PARAM_EQUALS:
                assert condition.query_name is not None
                assert condition.query_value is not None
                query_values.setdefault(condition.query_name, set()).add(
                    condition.query_value
                )
        if any(len(values) > 1 for values in query_values.values()):
            raise ValueError("contradictory query_param_equals conditions")

        if exact_conditions:
            exact_url = exact_conditions[0].url_value
            assert exact_url is not None
            parsed = urlsplit(exact_url)
            decoded_path = unquote(parsed.path)
            if origins:
                try:
                    exact_origin = normalize_origin(
                        urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
                    )
                except ValueError as exc:
                    raise ValueError(
                        "exact_url cannot satisfy origin_equals condition"
                    ) from exc
                if exact_origin != next(iter(origins)):
                    raise ValueError(
                        "exact_url contradicts origin_equals condition"
                    )
            if exact_paths and decoded_path != next(iter(exact_paths)):
                raise ValueError("exact_url contradicts path_equals condition")
            if any(not decoded_path.startswith(prefix) for prefix in prefixes):
                raise ValueError(
                    "exact_url contradicts path_starts_with condition"
                )
            decoded_query = parse_qsl(
                parsed.query, keep_blank_values=True, strict_parsing=False
            )
            for name, values in query_values.items():
                occurrences = [
                    value for key, value in decoded_query if key == name
                ]
                if len(occurrences) != 1 or occurrences[0] != next(iter(values)):
                    raise ValueError(
                        "exact_url contradicts query_param_equals condition"
                    )

    def describe(self) -> dict[str, Any]:
        self.validate()
        return {
            "logic": self.logic,
            "conditions": [condition.describe() for condition in self.conditions],
        }


@dataclass(frozen=True)
class PageConditionResult:
    condition_id: str
    condition_type: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    result: PageConditionResultValue
    evidence_refs: tuple[str, ...]
    evaluated_at_ms: int
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "condition_type": self.condition_type,
            "expected": self.expected,
            "observed": self.observed,
            "result": self.result.value,
            "evidence_refs": list(self.evidence_refs),
            "evaluated_at_ms": self.evaluated_at_ms,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class PagePreconditionEvaluation:
    mode: str
    logic: str
    result: PageConditionResultValue
    evaluated_at_ms: int
    actual_url: str
    condition_results: tuple[PageConditionResult, ...]
    expected_url: str | None = None
    fragment_differences_ignored: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "mode": self.mode,
            "logic": self.logic,
            "result": self.result.value,
            "matched": self.result == PageConditionResultValue.PASS,
            "actual_url": self.actual_url,
            "evaluated_at_ms": self.evaluated_at_ms,
            "condition_results": [item.to_dict() for item in self.condition_results],
        }
        if self.expected_url is not None:
            data["expected_url"] = self.expected_url
        if self.fragment_differences_ignored is not None:
            data["fragment_differences_ignored"] = (
                self.fragment_differences_ignored
            )
        return data


def normalize_origin(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("origin_equals requires origin_value")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("origin_value must be an absolute http(s) origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("origin_value must not include userinfo")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("origin_value must not include path, query, or fragment")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("origin_value contains invalid port") from exc
    default = 80 if scheme == "http" else 443
    suffix = "" if port in (None, default) else f":{port}"
    return f"{scheme}://{host}{suffix}"


def _without_fragment(value: str | None) -> str:
    assert value is not None
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
