"""Concise builders for host-declared plans.

These helpers reduce dataclass boilerplate only. They never choose URLs,
targets, actions, waits, expectations, or recovery behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dingdongditch.contract.browser import BrowserConfig, default_browser_config
from dingdongditch.contract.expectation import Expectation
from dingdongditch.contract.operation import Action, ActionType, Locator, Operation
from dingdongditch.contract.plan import ExecutionPlan
from dingdongditch.contract.page import PageTransition
from dingdongditch.contract.wait import WaitCondition
from dingdongditch.contract.screenshot import ScreenshotConfig
from dingdongditch.contract.download import DownloadRequest
from dingdongditch.contract.pointer import PointerMoveRequest, PointerOrigin


@dataclass
class PlanBuilder:
    plan_id: str
    browser_config: BrowserConfig = field(default_factory=default_browser_config)
    default_timeout_ms: int = 10_000
    operations: list[Operation] = field(default_factory=list)

    def _add(
        self,
        operation_id: str,
        url: str,
        action: Action,
        expectations: list[Expectation] | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> PlanBuilder:
        self.operations.append(
            Operation(
                operation_id=operation_id,
                url=url,
                action=action,
                expectations=list(expectations or []),
                timeout_ms=timeout_ms or self.default_timeout_ms,
            )
        )
        return self

    def navigate(
        self, operation_id: str, url: str, expectations: list[Expectation] | None = None
    ) -> PlanBuilder:
        return self._add(
            operation_id, url, Action(type=ActionType.NAVIGATE), expectations
        )

    def click(
        self,
        operation_id: str,
        url: str,
        locator: Locator,
        expectations: list[Expectation] | None = None,
        *,
        frame: Locator | None = None,
        page_transition: PageTransition | None = None,
    ) -> PlanBuilder:
        self.operations.append(
            Operation(
                operation_id=operation_id,
                url=url,
                action=Action(type=ActionType.CLICK, locator=locator, frame=frame),
                expectations=list(expectations or []),
                timeout_ms=self.default_timeout_ms,
                page_transition=page_transition,
            )
        )
        return self

    def switch_to_page(self, operation_id: str, url: str, page_id: str) -> PlanBuilder:
        return self._add(
            operation_id,
            url,
            Action(type=ActionType.SWITCH_TO_PAGE, page_id=page_id),
        )

    def close_page(self, operation_id: str, url: str, page_id: str) -> PlanBuilder:
        return self._add(
            operation_id,
            url,
            Action(type=ActionType.CLOSE_PAGE, page_id=page_id),
        )

    def download(
        self,
        operation_id: str,
        url: str,
        locator: Locator,
        request: DownloadRequest,
        expectations: list[Expectation] | None = None,
    ) -> PlanBuilder:
        return self._add(
            operation_id,
            url,
            Action(
                type=ActionType.DOWNLOAD,
                locator=locator,
                download_request=request,
            ),
            expectations,
            timeout_ms=request.timeout_ms,
        )

    def switch_to_opener(self, operation_id: str, url: str) -> PlanBuilder:
        return self._add(
            operation_id,
            url,
            Action(type=ActionType.SWITCH_TO_OPENER),
        )

    def fill(
        self,
        operation_id: str,
        url: str,
        locator: Locator,
        text: str,
        expectations: list[Expectation] | None = None,
        *,
        frame: Locator | None = None,
    ) -> PlanBuilder:
        return self._add(
            operation_id,
            url,
            Action(type=ActionType.FILL, locator=locator, text=text, frame=frame),
            expectations,
        )

    def select(
        self,
        operation_id: str,
        url: str,
        locator: Locator,
        *,
        value: str | None = None,
        label: str | None = None,
        values: tuple[str, ...] | None = None,
        expectations: list[Expectation] | None = None,
        frame: Locator | None = None,
    ) -> PlanBuilder:
        return self._add(
            operation_id,
            url,
            Action(
                type=ActionType.SELECT_OPTION,
                locator=locator,
                option_value=value,
                option_label=label,
                option_values=values,
                frame=frame,
            ),
            expectations,
        )

    def wait(
        self,
        operation_id: str,
        url: str,
        condition: WaitCondition,
        *,
        timeout_ms: int | None = None,
        expectations: list[Expectation] | None = None,
    ) -> PlanBuilder:
        return self._add(
            operation_id,
            url,
            Action(
                type=ActionType.WAIT_FOR,
                wait_condition=condition,
                wait_timeout_ms=timeout_ms,
            ),
            expectations,
            timeout_ms=timeout_ms,
        )

    def pointer_move(
        self,
        operation_id: str,
        url: str,
        request: PointerMoveRequest,
        locator: Locator | None = None,
        expectations: list[Expectation] | None = None,
        *,
        frame: Locator | None = None,
    ) -> PlanBuilder:
        if request.origin != PointerOrigin.VIEWPORT and locator is None:
            raise ValueError("element-relative pointer movement requires a locator")
        return self._add(
            operation_id,
            url,
            Action(
                type=ActionType.POINTER_MOVE,
                locator=locator,
                frame=frame,
                pointer_request=request,
            ),
            expectations,
        )

    def build(
        self,
        *,
        initial_plan_timeout_ms: int | None = None,
        adaptive_timeout_enabled: bool = False,
        max_plan_timeout_ms: int | None = None,
        screenshot_config: ScreenshotConfig | None = None,
    ) -> ExecutionPlan:
        plan = ExecutionPlan(
            plan_id=self.plan_id,
            operations=list(self.operations),
            browser_config=self.browser_config,
            initial_plan_timeout_ms=initial_plan_timeout_ms,
            adaptive_timeout_enabled=adaptive_timeout_enabled,
            max_plan_timeout_ms=max_plan_timeout_ms,
            screenshot_config=screenshot_config,
        )
        plan.validate()
        return plan
