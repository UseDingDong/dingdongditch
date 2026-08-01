# Milestone 1 — Target Resolution Hardening

**Status:** Complete (hardening pass; not Milestone 2)  
**Date:** 2026-07-26  
**Related:** Constrained semantic targets; fail-closed uniqueness

## Problem

A preferred semantic locator such as role `button` + accessible name `Search`
often matches **multiple** live controls on the same page (primary search,
clear, voice search, related actions, etc.).

Milestone 1 correctly returned `EXECUTION_FAILED` rather than choosing an
arbitrary match. Hosts sometimes fall back to an explicit CSS locator after
read-only inspection. That is honest for a one-off host plan, but forcing
site-specific CSS whenever semantic names collide is not an adequate long-term
host contract — hence constrained locators.

## Why semantic names may remain ambiguous

Modern pages reuse accessible names across regions and related controls.
Substring name matching (Playwright’s default) widens collisions further.
Semantic correctness of a name does not imply uniqueness.

## Why silent first-match selection is prohibited

Choosing the first DOM match, the visually nearest control, or a heuristic
“best” candidate would:

- invent host intent the operation did not declare  
- hide ambiguity inside a false success  
- violate fail-closed uniqueness (EP-01 / EP-02 spirit; NG-04 / no healing)

DingDongDitch may return a rich failure receipt. The **host** may submit a new
explicit operation. That is external replanning, not runtime recovery.

## Constrained-target contract

A target is:

1. a **primary** locator (`test_id` | `role_name` | `css`)  
2. zero or more **host-declared** narrowing constraints (declaration order)  
3. a **cardinality** policy (actions: `exactly_one` only in this pass)

Conceptual example:

```text
Find role=button name=Search (exact),
within test_id=search-region,
excluding accessible names {Clear search query, Search with your voice},
require exactly one final match.
```

The runtime applies **only** declared constraints. It does not invent, rank,
heal, or drop constraints.

## Supported constraints

| Constraint | Meaning |
|------------|---------|
| `within` | Keep candidates that are descendants of a uniquely resolved container locator |
| `attribute` | Filter by attribute `equals` / `exists` / `not_equals` |
| `visible` | Require live visible or hidden state (only when declared) |
| `enabled` | Require live enabled or disabled state (only when declared) |
| `exclude` | Remove candidates by exact/contains accessible name, attribute equality, or CSS match |

### Accessible-name match modes (`role_name` only)

| Mode | Behavior |
|------|----------|
| `contains` | **Default** — preserves Milestone 1 Playwright substring matching |
| `exact` | Exact accessible name |
| `regex` | Deterministic `re` pattern; invalid patterns fail validation before browser work |

Defaults are explicit in `Locator.describe()` (`name_match` is always recorded for
`role_name`).

### Attribute vs live state

- Constraint / expectation **attribute** checks use HTML attributes via
  `get_attribute`, except input **`value`**, which uses Playwright
  `input_value()` (live IDL property) when reading element state.  
- `visible` / `enabled` constraints use Playwright live state APIs.

## Constraint application order

```text
Primary semantic/CSS/test_id locator
    → constraints in host declaration order
    → candidate count evaluation
    → exactly_one required for click/fill dispatch
```

Action dispatch is permitted only when the final set satisfies `exactly_one`.

## Cardinality semantics

- Public field: `Operation.cardinality` (default `exactly_one`)  
- `require_unique_target=True` remains required for click/fill  
- `require_unique_target=False` is **rejected** for click/fill (no multi-match
  dispatch; no first-match fallback)  
- `zero_or_one` / `one_or_more` are not supported for actions in this pass

Failure kinds (structured on the resolution trace):

- `zero_after_primary`  
- `zero_after_constraints`  
- `multiple_after_primary`  
- `multiple_after_constraints`  
- `ambiguous_container` / `missing_container`  
- `invalid_constraint`

Top-level verdict remains `EXECUTION_FAILED` when dispatch is denied.

## Target-resolution trace

Receipt field: `target_resolution` (JSON-serializable). Includes:

- primary locator parameters  
- stages with candidate counts before/after each step  
- final candidate count  
- cardinality policy / pass / dispatch permitted  
- failure reason / kind  
- backend identity  
- compact candidate summaries when uniqueness fails (no full DOM dumps)

Receipt schema version: `1.1.0`.

## Neutral examples

```python
Locator(
    strategy=LocatorStrategy.ROLE_NAME,
    role="button",
    name="Execute",
    name_match=NameMatchMode.EXACT,
    constraints=(
        TargetConstraint(
            type=ConstraintType.WITHIN,
            within=Locator(strategy=LocatorStrategy.TEST_ID, value="region-alpha"),
        ),
    ),
)
```

```python
Locator(
    strategy=LocatorStrategy.ROLE_NAME,
    role="button",
    name="Run task",
    name_match=NameMatchMode.CONTAINS,
    constraints=(
        TargetConstraint(
            type=ConstraintType.EXCLUDE,
            exclude_names_exact=("Run task later", "Cancel task"),
        ),
    ),
)
```

## Playwright translation boundary

- Public contract: `dingdongditch/contract/operation.py`, `target.py`  
- Playwright composition/filtering: `dingdongditch/backends/target_resolver.py`  
- Adapter: `dingdongditch/backends/playwright_backend.py`  

No Playwright `Page` / `Locator` types appear in public receipts.

## Backward compatibility

- Locators without constraints remain valid  
- Omitted `constraints` defaults to empty  
- Omitted `name_match` defaults to `contains` for `role_name`  
- Existing CSS and unique locators still work  
- Click/fill still fail closed on ambiguity  
- Verdict vocabulary unchanged  

Intentional evolution: receipts may include `target_resolution`; schema `1.1.0`.

## Rejected features (this pass)

| Feature | Decision |
|---------|----------|
| Positional `index` / nth | **Rejected** — DOM order is unstable; would encode unsafe first-match |
| XPath | Deferred |
| Natural-language locators | Forbidden (NG / non-goals) |
| Image / coordinate locators | Forbidden |
| AI / heuristic ranking | Forbidden |
| Automatic alternate strategies | Forbidden |
| Bulk multi-element actions | Forbidden |
| Silent exact→contains coercion | Forbidden |

## Security and privacy

- Resolution traces avoid large DOM / page-content dumps by default  
- Candidate summaries are short tag/name/testid snippets  
- Regex patterns are compiled with Python `re` only (no executable host code)  
- Constraints cannot inject browser-side scripts beyond Playwright’s locator APIs  

## Limitations

- Constraints only help when the live page exposes usable semantics  
- Some sites may still require explicit CSS after inspection  
- No autonomous locator healing or cross-run learning  
- No visual / geometry disambiguation  
- `within` nesting depth capped (`MAX_WITHIN_DEPTH = 2`)  
- Public production sites are not CI gates  

## Governance links

- Principles: EP-01, EP-02, EP-04, EP-07, EP-08, EP-11, EP-13, EP-14  
- Non-goals: NG-01, NG-02, NG-03, NG-04, NG-05, NG-09  
- Phase 2: `RESPONSIBILITY_BOUNDARIES.md`, `SUCCESS_SEMANTICS.md`  
- Milestone 1 notes / limitations (updated for this pass)
