# New-tab and popup handling implementation report

## Outcome

DingDongDitch now exposes deterministic, host-declared page transitions through
the existing `ExecutionPlan -> runtime -> Playwright backend -> receipt`
boundary. The implementation does not add planning, locator healing, hidden
retries, or autonomous browsing.

The focused deterministic local popup suite passes **10/10** tests. The unit
suite passes **119/119** after updating stale test assertions from receipt
schema `1.6.0` to the runtime's additive page-transition schema `1.7.0`.

The complete repository suite was attempted repeatedly, including two long
outer-window attempts; it remained active beyond the ten-minute allowance and
was terminated by the command harness without a pytest summary. That is
reported as an unresolved suite-run hang, not as a fabricated pass.

## Architecture changes

- `dingdongditch.contract.page` defines typed page-transition policies,
  lifecycle states, and new-page expectations.
- `Operation.page_transition` carries the host declaration for actions that may
  create a page.
- `PlaywrightBackend` owns one session-level page registry and one explicit
  active page. It registers the initial page and every context page with stable
  IDs, opener identity, triggering operation, URL, lifecycle, and timestamps.
- Click dispatch installs the context page listener before dispatch, associates
  pages with the triggering operation, applies a deadline-bounded observation
  window, verifies the declared page, and switches only under an explicit
  policy.
- Runtime-owned shutdown closes all registered pages through the normal
  context/browser lifecycle while retaining terminal page evidence.

## Public typed API

```python
from dingdongditch.contract.page import (
    NewPageExpectation,
    PageTransition,
    PageTransitionPolicy,
)

transition = PageTransition(
    policy=PageTransitionPolicy.EXPECT_NEW_PAGE_AND_SWITCH,
    timeout_ms=2_000,
    new_page_expectations=(
        NewPageExpectation(
            url_value="popup_target.html",
            url_match=UrlMatchMode.CONTAINS,
            visible_locator=Locator(
                strategy=LocatorStrategy.TEST_ID,
                value="popup-heading",
            ),
        ),
    ),
)

Operation(
    operation_id="open-popup",
    url=opener_url,
    action=Action(
        type=ActionType.CLICK,
        locator=Locator(
            strategy=LocatorStrategy.TEST_ID,
            value="popup-button",
        ),
    ),
    page_transition=transition,
)
```

Supported policies are `SAME_PAGE`,
`EXPECT_NEW_PAGE_AND_SWITCH`, `EXPECT_NEW_PAGE_KEEP_CURRENT`, and
`ALLOW_SAME_OR_NEW_PAGE`. The builder and JSON plan loader preserve this typed
contract. Explicit actions include `SWITCH_TO_PAGE`, `SWITCH_TO_OPENER`, and
`CLOSE_PAGE`.

## Page-registry design

Each registry entry contains:

- stable `page_id`;
- `opener_page_id`;
- `triggering_operation_id`;
- current URL;
- `open`/`closed` lifecycle state;
- active-page status;
- creation and close monotonic timestamps.

`list_known_pages()` and `inspect_known_page()` are read-only inspection APIs.
They never switch or dispatch. The original opener remains registered when a
new page is created, including when the new page becomes active.

## Failure classifications

Receipts distinguish:

- `expected_new_page_not_opened`;
- `unexpected_new_page`;
- `multiple_new_pages_opened`;
- `new_page_closed_before_verification`;
- `new_page_verification_failed`;
- `plan_deadline_expired` while waiting for the transition.

Unexpected pages never cause an implicit switch. A failed transition stops the
plan through the existing stop-on-failure semantics.

## Receipt and evidence changes

Operation receipts now retain `page_transition` plus action evidence including
page counts before/after, opener ID, created page IDs, popup-event status,
selected active page, switching status, page registry snapshots, and per-page
verification results. The additive operation receipt schema is `1.7.0`.

Terminal lifecycle identity retains all page entries after cleanup, including
close timestamps, so page evidence is not lost when runtime-owned browser
resources are closed.

## Tests added

`tests/integration/test_page_transitions_e2e.py` uses only the local fixture
server and covers:

- link-created new tab with explicit switch;
- popup while retaining the opener as active;
- switch back to opener;
- close popup and continue on opener;
- expected page missing;
- unexpected popup;
- multiple pages when exactly one is expected;
- page closing before verification;
- redirect before verification;
- deadline expiry while waiting and lifecycle evidence after cleanup.

Focused result: **10 passed**.

## Test results and compatibility concerns

- Focused page-transition suite: **10 passed**.
- Unit suite: **119 passed**.
- Full suite: repeated runs exceeded the ten-minute outer command limit and
  produced no pytest completion summary. The repository therefore does not
  have a verified full-suite-twice result in this environment.
- Initial unit failure was a stale test expectation for `1.6.0`; all five
  affected assertions now expect the additive `1.7.0` operation receipt.
- Initial sandboxed browser attempts failed because Node/Playwright could not
  `lstat` the user profile path; focused tests pass when run with the required
  local-browser permission.

## Recommended next action

Investigate the full-suite hang with per-file isolation or a test timeout
plugin, then repeat the complete suite twice. No production-code change is
warranted by the current evidence: the focused transition behavior and unit
contracts are green, while the remaining issue is suite completion.
