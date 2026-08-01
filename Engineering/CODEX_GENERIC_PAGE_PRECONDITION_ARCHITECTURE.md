# Generic deterministic page-precondition architecture

## Status

**Proposal only — review required before implementation.**

This document redesigns DingDongDitch's generic current-page precondition. It
does not implement code, alter production behavior, or introduce any
site-specific rule.

## Executive decision

Add an explicit typed `PagePrecondition` to `Operation`. It contains a
declaration-ordered tuple of closed-union `PageCondition` values and has only
one composition mode: **all conditions must pass**.

For a non-navigation operation:

- if `page_precondition` is absent, execute the existing exact same-document
  comparison against `Operation.url` unchanged;
- if `page_precondition` is present, evaluate exactly the declared typed
  conditions once before dispatch;
- never derive, add, reorder, relax, or retry a condition;
- dispatch only when every condition has evidence-backed `pass`;
- fail closed on `fail`, ambiguity, unavailable observations, unsupported
  condition types, or evaluator errors.

This preserves every existing exact-URL plan byte-for-byte while letting new
plans describe stable page identity independently of transient URL components.

## Problem statement

Today, every non-`navigate` operation performs:

```text
actual_url = backend.page.url
matched = _same_document_url(actual_url, operation.url)
```

`_same_document_url` ignores fragment differences but otherwise requires the
same full URL. This is deterministic and fail-closed, but it makes stable
execution depend on volatile query parameters, generated path identifiers, and
session-specific navigation state.

Post-action URL expectations do not solve this. An operation can verify that a
new URL contains a stable marker, but the following operation must still know
the complete generated URL before its own dispatch.

The missing abstraction is not looser URL matching. It is a typed declaration
of the stable, observable facts that identify the required current page.

## Design principles

1. **The host declares all required facts.** The runtime never decides what
   constitutes the page.
2. **Closed typed vocabulary.** No free-form predicate strings, callbacks,
   JavaScript, regex, wildcard, or AI interpretation.
3. **AND only.** No implicit OR, fallback, scoring, or “best match.”
4. **One-shot pre-dispatch evaluation.** No hidden polling or retry. A host that
   needs readiness first declares a separate typed `wait_for` operation.
5. **Fail closed.** Only `pass` permits dispatch. Both `fail` and
   `indeterminate` stop before the action.
6. **Evidence for every condition.** Expected value, observed value,
   timestamp, result, and evidence reference are recorded.
7. **Exact URL remains strongest.** It remains available explicitly and is the
   automatic legacy behavior.
8. **Site independence.** Conditions operate only on URL structure, title, and
   declared DOM targets.

## Proposed contract

The names below are recommended. Exact spelling can change during review
without changing the architecture.

### Core composition types

```python
class PageConditionType(str, Enum):
    EXACT_URL = "exact_url"
    ORIGIN_EQUALS = "origin_equals"
    PATH_EQUALS = "path_equals"
    PATH_STARTS_WITH = "path_starts_with"
    URL_CONTAINS = "url_contains"
    QUERY_PARAM_EXISTS = "query_param_exists"
    QUERY_PARAM_EQUALS = "query_param_equals"
    TITLE_CONTAINS = "title_contains"
    ELEMENT_EXISTS = "element_exists"
    ELEMENT_VISIBLE = "element_visible"
    ELEMENT_COUNT = "element_count"
    TYPED_EXPECTATION = "typed_expectation"


class FragmentPolicy(str, Enum):
    IGNORE = "ignore"
    INCLUDE = "include"


@dataclass(frozen=True)
class PagePrecondition:
    conditions: tuple["PageCondition", ...]
    # Deliberately fixed today; included in describe/JSON for future schema
    # clarity, but validation rejects any value except ALL.
    logic: Literal["all"] = "all"


@dataclass(frozen=True)
class PageCondition:
    condition_id: str
    type: PageConditionType

    # exact_url
    url_value: str | None = None
    fragment_policy: FragmentPolicy = FragmentPolicy.IGNORE

    # origin_equals
    origin_value: str | None = None

    # path_equals / path_starts_with
    path_value: str | None = None

    # url_contains
    substring: str | None = None

    # query conditions
    query_name: str | None = None
    query_value: str | None = None

    # title_contains
    title_value: str | None = None

    # element conditions
    locator: Locator | None = None
    expected_count: int | None = None
    frame: Locator | None = None

    # reuse of an existing closed typed expectation
    expectation: Expectation | None = None
```

`PageCondition` is shown as one dataclass to match the repository's current
contract style. Separate frozen dataclasses in a discriminated union are also
acceptable and may provide stronger static typing:

```python
PageCondition = (
    ExactUrlCondition
    | OriginEqualsCondition
    | PathEqualsCondition
    | PathStartsWithCondition
    | UrlContainsCondition
    | QueryParamExistsCondition
    | QueryParamEqualsCondition
    | TitleContainsCondition
    | ElementExistsCondition
    | ElementVisibleCondition
    | ElementCountCondition
    | TypedExpectationCondition
)
```

The discriminated-union form is preferred if the JSON adapter can retain its
current strict unknown-field rejection.

### Operation integration

```python
@dataclass
class Operation:
    operation_id: str
    url: str
    action: Action
    page_precondition: PagePrecondition | None = None
    # existing fields unchanged...
```

Transitional semantics:

| Action | `page_precondition` | Behavior |
|---|---|---|
| `navigate` | absent | `url` remains the navigation destination |
| `navigate` | present | invalid plan; pre-navigation requirements are out of scope |
| non-navigation | absent | legacy exact same-document check against `url` |
| non-navigation | present | explicit conditions replace only the implicit legacy exact check |

For an explicit precondition, `Operation.url` remains a required canonical page
reference during the compatibility period and remains available as
`target_url` in receipts. It is not silently added as another condition. This
precedence must be documented prominently and surfaced by `describe()`:

```json
{
  "page_precondition_mode": "explicit_conditions",
  "legacy_url_precondition_applied": false
}
```

Longer term, a major schema revision can split `url` into
`navigation_destination` for navigation actions and `page_precondition` for
non-navigation actions. That cleanup is not required for the additive first
release.

## Condition semantics

All string comparisons are case-sensitive except where URL standards require
normalization. There is no Unicode fuzzy matching, case folding, regex, or
wildcard interpretation.

### URL parsing and normalization

Parse the current URL once with the standard URL parser. Record both the raw URL
and parsed components as precondition evidence.

Normalization rules:

- scheme and host are ASCII-lowercased;
- default ports are normalized (`:80` for HTTP, `:443` for HTTPS);
- percent-decoding follows the standard library exactly once;
- path is not slash-normalized, dot-segment-rewritten, or case-folded;
- query parsing preserves blank values and duplicate keys;
- `+` in query values follows standard form-query decoding to a space;
- fragments are excluded except when an explicit exact condition selects
  `fragment_policy=include`;
- userinfo in an HTTP(S) URL is invalid for a page condition;
- malformed URLs produce `indeterminate` and block dispatch.

### Exact URL

`exact_url` compares the normalized current and expected URL. With the default
`fragment_policy=ignore`, it must be behaviorally identical to the current
`_same_document_url` rule.

It is the strongest condition and can be the only condition.

### Origin equals

`origin_equals` requires the normalized `(scheme, host, effective_port)` tuple
to equal the declared origin. Paths and queries are ignored.

This condition is recommended alongside path/query conditions when the plan
must prevent dispatch on another origin with an identical path.

### Path equals

`path_equals` requires the decoded path to equal the declared path exactly.
Query and fragment are ignored.

Validation requires a leading `/` and forbids `?` and `#`.

### Path starts with

`path_starts_with` performs a literal prefix comparison on the decoded path.
It does not interpret path segments, globs, or regex.

Validation requires a leading `/`, forbids `?` and `#`, and rejects `/` as a
prefix because it carries almost no identifying information.

### URL contains

`url_contains` performs a literal substring check against the raw current URL.
It is intentionally simple and weaker than parsed conditions.

Validation rejects empty strings and control characters. Documentation should
recommend parsed origin/path/query conditions when possible.

### Required query parameter

`query_param_exists` passes only when the decoded query contains the declared
key at least once.

It says nothing about the value. Duplicate occurrences are recorded in
evidence.

### Required query parameter value

`query_param_equals` is fail-closed:

- exactly one decoded occurrence of the key must exist; and
- its decoded value must equal the declared value exactly.

Zero or multiple occurrences fail. This avoids an implicit “any duplicate value
may match” OR rule. A future duplicate-aware condition would need an explicit
typed multiplicity contract and separate review.

### Page title contains

`title_contains` performs a case-sensitive literal substring comparison against
the browser-observed title. Empty values are invalid.

### Element exists

`element_exists` uses the existing typed `Locator`, optional one-level `frame`,
target resolver, and evidence format.

It passes only when exactly one element resolves. Zero is `fail`; multiple is
`indeterminate`/ambiguous and blocks dispatch. Hosts that intentionally expect
multiple elements must use `element_count`.

### Element visible

`element_visible` passes only when exactly one declared element resolves and
that element is visible. Zero fails; ambiguity is indeterminate.

### Element count

`element_count` compares the exact resolved primary match count to a declared
non-negative integer. It does not apply exactly-one cardinality and does not
select or dispatch to any member.

Only exact equality is included initially. Greater-than/range comparisons can
be proposed later as separately named typed conditions; they must not be
smuggled in as generic operators.

### Custom typed expectation

`typed_expectation` wraps an existing `Expectation`, but only a reviewed
pre-dispatch-safe subset:

- URL
- element exists
- element visible
- element in viewport
- text
- attribute

`NETWORK` is invalid because the precondition evaluates current page state
before the new action and has no post-action freshness window.

This is not an arbitrary extension callback. The runtime switches on the closed
`ExpectationType` enum and uses built-in evaluators. New expectation types
still require normal contract, adapter, evaluator, evidence, and test changes.

## AND composition

Conditions are evaluated in declaration order. The result is:

```text
pass          if every condition is pass
fail          if at least one condition is fail and none is indeterminate
indeterminate if any condition cannot be observed or is ambiguous
```

Dispatch requires aggregate `pass`.

Recommended evaluator behavior is to evaluate every condition even after a
failure, up to a small validated maximum (for example 32 conditions), so the
receipt contains a complete page-identity assessment. This is not a retry:
every condition is observed once.

If review prioritizes minimal DOM exposure or latency, fail-fast evaluation is
acceptable, but the receipt must mark later conditions `not_evaluated` rather
than implying they passed.

No OR groups, nesting, negation, optional conditions, fallback sets, or weights
are included in the initial contract.

## Validation rules

Validation occurs before browser launch as part of `Operation.validate()` and
again in the JSON adapter's strict construction path.

### Precondition-level validation

- `conditions` must be a non-empty tuple/list.
- Maximum condition count is bounded (recommended: 32).
- `logic` must be exactly `all`.
- `condition_id` must be non-empty and unique within the precondition.
- Each entry must be a recognized typed condition.
- A `navigate` action must not carry `page_precondition`.

### Discriminant validation

Each condition accepts only fields appropriate to its type. Unknown or
extraneous fields are rejected, matching the repository's current fail-closed
JSON policy.

Examples:

- `path_equals` requires only `condition_id`, `type`, and `path_value`;
- `query_param_equals` requires `query_name` and `query_value`;
- `element_count` requires a locator and integer `expected_count >= 0`;
- `typed_expectation` requires exactly one supported expectation and rejects
  network;
- locator/frame validation reuses current depth, cardinality, and constraint
  validation.

### Contradiction validation

Reject contradictions that are provable without opening a browser:

- two different `exact_url` values;
- two different `origin_equals` values;
- two different `path_equals` values;
- `path_equals` not beginning with a declared `path_starts_with`;
- duplicate `query_param_equals` conditions for one key with different values;
- `element_count == 0` combined with `element_exists` or `element_visible` for
  the structurally identical locator/frame.

Do not attempt general logical theorem proving. Conditions not proven
contradictory are evaluated normally and fail closed at runtime.

### Recommended identity-strength warning

Do not reject weak but explicit declarations automatically. Instead, expose a
non-fatal plan-description warning when an explicit precondition contains only
`url_contains` or only title/DOM facts without an origin condition.

Warnings must never add conditions or affect execution.

## Execution-flow changes

Current flow:

```text
validate operation
→ ensure backend active
→ compare actual URL with Operation.url
→ dispatch action
→ collect post-action evidence
→ evaluate expectations
→ receipt
```

Proposed flow:

```text
validate operation and page-precondition types
→ ensure backend active
→ resolve effective precondition:
     explicit PagePrecondition, or
     synthetic legacy ExactUrl(Operation.url)
→ begin a precondition evidence window
→ snapshot raw URL and parsed URL components once
→ evaluate each declared condition once, in order
→ emit per-condition evidence and aggregate result
→ if aggregate != pass:
     do not dispatch
     return fail-closed receipt
→ dispatch existing action unchanged
→ collect existing post-action evidence
→ evaluate existing post-action expectations unchanged
→ receipt
```

Navigation actions continue to skip current-page preconditions and navigate to
`Operation.url`, exactly as today.

### Evaluator boundary

Add a focused runtime module, for example:

```text
dingdongditch/runtime/page_preconditions.py
```

Recommended pure/core API:

```python
def evaluate_page_precondition(
    *,
    backend: PlaywrightBackend,
    precondition: PagePrecondition,
    collector: EvidenceCollector,
) -> PagePreconditionEvaluation:
    ...
```

The evaluator:

- cannot dispatch actions;
- cannot navigate;
- cannot mutate the page;
- cannot retry;
- cannot synthesize conditions;
- may only read URL, title, and declared DOM facts;
- returns typed results rather than deciding the operation verdict.

The executor remains responsible for stopping before dispatch and constructing
the receipt.

## Evidence and receipt design

Introduce typed result models:

```python
class PageConditionResultValue(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class PageConditionResult:
    condition_id: str
    condition_type: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    result: PageConditionResultValue
    evidence_refs: tuple[str, ...]
    evaluated_at_ms: int | None
    explanation: str


@dataclass(frozen=True)
class PagePreconditionEvaluation:
    mode: Literal["legacy_exact_url", "explicit_conditions"]
    logic: Literal["all"]
    result: PageConditionResultValue
    evaluated_at_ms: int
    actual_url: str
    parsed_url: dict[str, Any] | None
    condition_results: tuple[PageConditionResult, ...]
```

Example receipt fragment:

```json
{
  "page_precondition": {
    "mode": "explicit_conditions",
    "logic": "all",
    "result": "pass",
    "evaluated_at_ms": 420010,
    "actual_url": "https://shop.example/search?q=wireless+mouse&session=abc",
    "parsed_url": {
      "origin": "https://shop.example",
      "path": "/search",
      "query_keys": ["q", "session"]
    },
    "condition_results": [
      {
        "condition_id": "origin",
        "condition_type": "origin_equals",
        "expected": {"origin_value": "https://shop.example"},
        "observed": {"origin": "https://shop.example"},
        "result": "pass",
        "evidence_refs": ["op-sig-1"],
        "evaluated_at_ms": 420010,
        "explanation": "origin matched"
      },
      {
        "condition_id": "query",
        "condition_type": "query_param_equals",
        "expected": {"query_name": "q", "query_value": "wireless mouse"},
        "observed": {
          "occurrence_count": 1,
          "values": ["wireless mouse"]
        },
        "result": "pass",
        "evidence_refs": ["op-sig-1"],
        "evaluated_at_ms": 420010,
        "explanation": "exactly one query value matched"
      }
    ]
  }
}
```

URL-derived conditions may share one URL evidence signal. DOM conditions each
emit a `DOM_STATE` signal. Title can use a new `PAGE_METADATA` signal or an
existing URL/page observation signal expanded in a schema-versioned way.

### Failure mapping

- At least one condition `fail`, none indeterminate:
  `execution_status=page_precondition_failed`,
  `failure_kind=page_precondition_mismatch`,
  operation verdict `EXECUTION_FAILED`.
- Any condition indeterminate:
  `execution_status=page_precondition_failed`,
  recommended new `failure_kind=page_precondition_indeterminate`,
  operation verdict `EXECUTION_FAILED`.
- Invalid contract:
  existing validation-failure path before dispatch/browser action.

Keeping `page_precondition_mismatch` for ordinary failures preserves callers
that already understand the existing failure kind.

No action timestamp is set and `action_executed_successfully=false`, as today.

## JSON contract

Add `page_precondition` to the strict allowed operation fields.

Generic example:

```json
{
  "operation_id": "open-result",
  "url": "https://catalog.example/search",
  "page_precondition": {
    "logic": "all",
    "conditions": [
      {
        "condition_id": "origin",
        "type": "origin_equals",
        "origin_value": "https://catalog.example"
      },
      {
        "condition_id": "path",
        "type": "path_equals",
        "path_value": "/search"
      },
      {
        "condition_id": "query",
        "type": "query_param_equals",
        "query_name": "q",
        "query_value": "wireless mouse"
      },
      {
        "condition_id": "results",
        "type": "element_exists",
        "locator": {
          "strategy": "css",
          "value": "[data-testid='search-results']"
        }
      }
    ]
  },
  "action": {
    "type": "click",
    "locator": {
      "strategy": "test_id",
      "value": "result-wireless-mouse-standard"
    }
  },
  "expectations": [
    {
      "type": "url",
      "url_value": "/products/",
      "url_match": "contains"
    }
  ]
}
```

The transient `session` parameter may be present, absent, or different. The
runtime does not ignore it heuristically; the host simply did not declare it as
a required page fact.

### Exact legacy-equivalent example

```json
{
  "operation_id": "submit",
  "url": "https://forms.example/profile?mode=edit",
  "page_precondition": {
    "conditions": [
      {
        "condition_id": "exact",
        "type": "exact_url",
        "url_value": "https://forms.example/profile?mode=edit",
        "fragment_policy": "ignore"
      }
    ]
  },
  "action": {
    "type": "click",
    "locator": {"strategy": "test_id", "value": "save"}
  }
}
```

Omitting `page_precondition` produces the same exact behavior automatically, so
existing plans do not need this verbose form.

### Title and element-count example

```json
{
  "operation_id": "inspect-dashboard",
  "url": "https://portal.example/dashboard",
  "page_precondition": {
    "conditions": [
      {
        "condition_id": "origin",
        "type": "origin_equals",
        "origin_value": "https://portal.example"
      },
      {
        "condition_id": "path",
        "type": "path_starts_with",
        "path_value": "/dashboard/"
      },
      {
        "condition_id": "title",
        "type": "title_contains",
        "title_value": "Account dashboard"
      },
      {
        "condition_id": "one-primary-panel",
        "type": "element_count",
        "locator": {
          "strategy": "css",
          "value": "main [data-panel='primary']"
        },
        "expected_count": 1
      }
    ]
  },
  "action": {
    "type": "press_key",
    "key": "Escape",
    "key_scope": "active_page"
  },
  "expectations": [
    {
      "type": "element_visible",
      "locator": {"strategy": "test_id", "value": "dashboard-heading"},
      "visible": true
    }
  ]
}
```

## Backwards compatibility

### Python API

All existing constructors remain valid:

```python
Operation(operation_id="click", url=url, action=action)
```

Because `page_precondition` defaults to `None`, behavior remains the current
exact same-document check. Positional constructor compatibility should be
preserved by adding the new optional field after existing required fields and
preferably after current optional fields, or by making new construction
keyword-only in a scheduled major version.

### JSON plans

Existing JSON is unchanged. Unknown-field rejection remains. The adapter only
gains parsing for a new optional known field.

### PlanBuilder

Existing builder methods keep emitting legacy operations. Add explicit new
overloads or methods, for example:

```python
.click(..., page_precondition=precondition)
.wait_for(..., page_precondition=precondition)
```

The builder must not generate conditions automatically from locators or URLs.

### Receipts

Legacy receipt consumers often read:

```json
{
  "expected_url": "...",
  "actual_url": "...",
  "matched": true,
  "fragment_differences_ignored": true
}
```

For legacy mode, retain these fields exactly and add the new fields
additively. For explicit mode:

- keep `actual_url` and aggregate `matched`;
- set `expected_url` to `null` unless an `exact_url` condition exists;
- add `mode`, `logic`, and `condition_results`;
- never fabricate one expected URL from partial conditions.

Increment `ExecutionReceipt` schema from `1.7.0` to an additive minor version
if repository versioning policy allows; otherwise use the next documented
schema version. Plan receipt serialization embeds operation receipts and needs
corresponding fixture updates.

### Behavioral compatibility matrix

| Existing/new plan | Expected behavior |
|---|---|
| Existing navigate operation | unchanged |
| Existing non-navigate, exact URL matches | unchanged dispatch |
| Existing non-navigate, exact URL mismatches | unchanged fail-closed result |
| Existing fragment-only difference | unchanged match |
| New explicit exact condition | equivalent to legacy exact behavior |
| New explicit all conditions pass | dispatch |
| New explicit one condition fails | no dispatch |
| New explicit ambiguous DOM condition | no dispatch, indeterminate evidence |
| New explicit malformed/unknown condition | validation failure before dispatch |

## Migration strategy

### Phase 0 — architecture review

- Review condition vocabulary and exact semantics.
- Resolve transitional meaning of `Operation.url` when explicit conditions are
  present.
- Approve receipt schema changes and failure-kind policy.
- Do not change runtime code until approval.

### Phase 1 — additive contracts and pure evaluators

- Add typed condition/result models.
- Add strict validation and JSON parsing.
- Implement URL parsing/comparison as pure functions.
- Add unit tests without wiring them into dispatch.

### Phase 2 — executor integration behind explicit presence

- Preserve the existing branch when `page_precondition is None`.
- Invoke the new evaluator only when explicitly declared.
- Add evidence/receipt serialization.
- Prove no action dispatch on fail or indeterminate.

### Phase 3 — builders, examples, and opt-in migration

- Add builder parameters without changing defaults.
- Migrate one deterministic fixture plan as a demonstration.
- Leave all existing plans on legacy exact mode.
- Document when origin/path/query/DOM combinations are appropriate.

### Phase 4 — broader voluntary adoption

- Update plans affected by transient URLs only after their stable page facts are
  explicitly identified.
- Do not bulk-convert exact plans.
- Keep exact URL as the recommended default when URLs are stable.

### Future major cleanup

After adoption data and a separate review, consider splitting navigation
destination from non-navigation page identity. This must not be bundled into
the additive foundation.

## Implementation plan

No implementation is performed now. After review, the recommended sequence is:

1. Add `dingdongditch/contract/page_precondition.py` with frozen condition,
   composition, and result types.
2. Add `page_precondition` to `Operation`, validation, and `describe()`.
3. Add strict JSON adapter parsing with per-type allowed-field sets.
4. Add pure URL parsing and condition comparison helpers.
5. Add backend read-only primitives:
   - page title snapshot;
   - exact primary element count without target selection;
   - reuse current element-state resolution for exactly-one DOM conditions.
6. Add `runtime/page_preconditions.py`.
7. Integrate an explicit-mode branch before action dispatch, retaining the
   legacy branch verbatim.
8. Extend evidence models and receipt serialization.
9. Add builder support and generic examples.
10. Run focused unit tests, integration tests across Chromium/Firefox/WebKit,
    then the complete suite with the measured outer timeout.

## Test and acceptance plan

### Contract/unit tests

- every condition's valid and invalid field combinations;
- unknown fields and enums fail closed;
- empty/duplicate IDs and condition count bound;
- all contradiction checks;
- query decoding, blank values, duplicate-key failure;
- origin normalization and default ports;
- path equality/prefix literal semantics;
- fragment include/ignore behavior;
- no regex/wildcard syntax receives special interpretation;
- typed expectation subset rejects network;
- navigate plus explicit precondition is invalid.

### Evaluator tests

- all-pass AND result;
- one fail blocks dispatch;
- ambiguous element produces indeterminate and blocks dispatch;
- unavailable title/DOM observation blocks dispatch;
- every result has evidence references and timestamps;
- condition order is preserved;
- primary count observation never selects an element;
- evaluator performs no navigation, action dispatch, retry, or mutation.

### Backwards-compatibility tests

- retain the existing mismatch test:
  `test_non_navigation_page_mismatch_never_dispatches_or_navigates`;
- exact match, mismatch, and fragment tests remain byte-for-byte behavioral
  equivalents;
- old JSON samples load unchanged;
- old Python constructors work unchanged;
- legacy receipt fields retain their meanings;
- existing plan builder output remains legacy exact mode.

### Integration tests

Use deterministic local generic fixtures only:

- transient query token varies while required stable query value passes;
- missing required query key blocks dispatch;
- duplicate required query key is fail-closed;
- path prefix and origin both required;
- title plus visible element AND composition;
- exact element count;
- DOM ambiguity and zero-match cases;
- same behavior in Chromium, Firefox, and WebKit;
- no operation starts when any precondition does not pass.

### Acceptance criteria

The architecture is complete only if:

- all existing exact URL tests pass unchanged;
- explicit conditions are the sole source of page identity in explicit mode;
- no runtime inference or condition synthesis exists;
- all conditions are AND-composed;
- every condition result is evidence-backed;
- fail/indeterminate never dispatch;
- transient undeclared URL components do not affect declared stable
  requirements;
- exact URL remains available and strongest;
- no website-specific code or tests are introduced.

## Review questions

1. Is explicit `page_precondition` overriding the legacy exact check acceptable
   during the additive compatibility period, with `Operation.url` retained as a
   canonical receipt reference?
2. Should all conditions be evaluated for complete evidence, or should the
   evaluator fail fast and mark remaining conditions `not_evaluated`?
3. Should `page_precondition_indeterminate` be a new failure kind, or should all
   non-pass outcomes retain `page_precondition_mismatch` for compatibility?
4. Is `url_contains` necessary in the first release, given the safer parsed
   conditions, or should it be included because it is explicit and already
   familiar from post-action URL expectations?
5. Should title comparisons remain strictly case-sensitive as proposed?
6. Is exact duplicate-query-key failure the desired initial semantics?
7. Should the initial maximum be 32 conditions?

These decisions should be resolved in architecture review before production
implementation begins.
