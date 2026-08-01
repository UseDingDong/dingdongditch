"""Typed page-transition and page-registry contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from dingdongditch.contract.modes import TextMatchMode, UrlMatchMode
from dingdongditch.contract.operation import Locator


class PageTransitionPolicy(str, Enum):
    SAME_PAGE = "same_page"
    EXPECT_NEW_PAGE_AND_SWITCH = "expect_new_page_and_switch"
    EXPECT_NEW_PAGE_KEEP_CURRENT = "expect_new_page_keep_current"
    ALLOW_SAME_OR_NEW_PAGE = "allow_same_or_new_page"


class PageLifecycleState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class NewPageExpectation:
    """Browser-observable conditions for one newly-created page."""

    url_value: str | None = None
    url_match: UrlMatchMode = UrlMatchMode.EXACT
    title_value: str | None = None
    title_match: TextMatchMode = TextMatchMode.EXACT
    visible_locator: Locator | None = None

    def validate(self) -> None:
        if not any((self.url_value, self.title_value, self.visible_locator)):
            raise ValueError("new-page expectation requires url, title, or visible_locator")
        if self.visible_locator is not None:
            self.visible_locator.validate()

    def describe(self) -> dict[str, Any]:
        return {
            "url_value": self.url_value,
            "url_match": self.url_match.value,
            "title_value": self.title_value,
            "title_match": self.title_match.value,
            "visible_locator": (
                self.visible_locator.describe() if self.visible_locator else None
            ),
        }


@dataclass(frozen=True)
class PageTransition:
    policy: PageTransitionPolicy = PageTransitionPolicy.SAME_PAGE
    new_page_expectations: tuple[NewPageExpectation, ...] = ()
    timeout_ms: int = 250
    activate_new_page_when_allowed: bool = False

    def validate(self) -> None:
        if self.timeout_ms < 100:
            raise ValueError("page-transition timeout_ms must be >= 100")
        expects = self.policy in {
            PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH,
            PageTransitionPolicy.EXPECT_NEW_PAGE_KEEP_CURRENT,
        }
        if self.new_page_expectations and not (
            expects or self.policy == PageTransitionPolicy.ALLOW_SAME_OR_NEW_PAGE
        ):
            raise ValueError("SAME_PAGE must not declare new-page expectations")
        if expects and not self.new_page_expectations:
            raise ValueError("expected new page requires at least one expectation")
        for expectation in self.new_page_expectations:
            expectation.validate()
        if (
            self.activate_new_page_when_allowed
            and self.policy != PageTransitionPolicy.ALLOW_SAME_OR_NEW_PAGE
        ):
            raise ValueError(
                "activate_new_page_when_allowed is only valid for ALLOW_SAME_OR_NEW_PAGE"
            )

    def describe(self) -> dict[str, Any]:
        return {
            "policy": self.policy.value,
            "timeout_ms": self.timeout_ms,
            "activate_new_page_when_allowed": self.activate_new_page_when_allowed,
            "new_page_expectations": [
                expectation.describe() for expectation in self.new_page_expectations
            ],
        }
