# PagePrecondition Version 1 vocabulary review

## Status

**Design review only. No implementation or production change.**

This review applies one standard: a Version 1 condition belongs only if removing
it would prevent the host from declaring a major, stable category of page
identity that the remaining conditions cannot safely express.

The recommended Version 1 vocabulary is:

```text
EXACT_URL
ORIGIN_EQUALS
PATH_EQUALS
PATH_STARTS_WITH
QUERY_PARAM_EQUALS
ELEMENT_VISIBLE
```

This reduces the proposal from twelve condition types to six.

## Decision criteria

A condition is:

- **KEEP** when it represents an irreducible page-identity fact needed in the
  initial generic foundation;
- **POSTPONE** when it is deterministic and potentially useful, but Version 1
  remains capability-complete for its primary goal without it;
- **REMOVE** when it duplicates safer composition, weakens contract clarity, or
  creates an extension surface whose maintenance cost exceeds its unique value.

“Expressible by another condition” means semantically and safely expressible,
not merely approximated with a weaker assertion.

## Condition-by-condition review

| Condition | Recommendation | Fundamental? | Safely expressible elsewhere? | Convenience only? | Version placement | Maintenance effect |
|---|---|---|---|---|---|---|
| `EXACT_URL` | **KEEP** | Yes | No | No | Version 1 | Preserves legacy behavior and provides the strongest identity assertion. |
| `ORIGIN_EQUALS` | **KEEP** | Yes | Not safely | No | Version 1 | Gives partial URL compositions an explicit security/identity anchor. |
| `PATH_EQUALS` | **KEEP** | Yes | Not safely | No | Version 1 | Represents stable route identity while excluding transient query state. |
| `PATH_STARTS_WITH` | **KEEP** | Yes | No, when a path suffix is legitimately generated | No | Version 1 | Adds one literal prefix evaluator but covers transient path components generically. |
| `URL_CONTAINS` | **REMOVE** | No | Yes, for maintainable cases, with origin/path/query composition | Yes | Omit | Removes a weak raw-string matching mode and its encoding/canonicalization ambiguities. |
| `QUERY_PARAM_EXISTS` | **POSTPONE** | No for the initial goal | No exact substitute, but hosts can omit transient irrelevant parameters and use equality for stable semantic parameters | Usually | Version 2 candidate | Avoids duplicate-key and valueless/blank-value semantics in the first release. |
| `QUERY_PARAM_EQUALS` | **KEEP** | Yes | No | No | Version 1 | Captures stable semantic query state without coupling to unrelated generated parameters. |
| `TITLE_CONTAINS` | **POSTPONE** | No | Usually by URL structure plus a visible page landmark | Usually | Version 2 candidate | Avoids localization, branding, and asynchronous-title semantics in the initial evaluator. |
| `ELEMENT_EXISTS` | **POSTPONE** | No for Version 1 | Not completely; visibility is stronger but not equivalent | Sometimes | Version 2 candidate | Keeps initial DOM semantics focused on actionable, observable page landmarks. |
| `ELEMENT_VISIBLE` | **KEEP** | Yes | No | No | Version 1 | Supplies one strong DOM identity condition tied to what the user-visible page presents. |
| `ELEMENT_COUNT` | **POSTPONE** | No | Some common cases are covered by fail-closed unique `ELEMENT_VISIBLE`, but exact multi-element counts are unique | Usually | Version 2 candidate | Defers a separate non-selecting count-resolution path and dynamic-list stability concerns. |
| `TYPED_EXPECTATION` | **REMOVE** | No | Its useful cases overlap named URL/DOM conditions | No; it is an extension escape hatch | Omit; require a future architecture review if needed | Prevents the precondition vocabulary from inheriting every expectation type and lifecycle rule. |

## Detailed recommendations

### EXACT_URL — KEEP

`EXACT_URL` is foundational.

Technical reasons:

- It is the current contract expressed explicitly.
- It is the strongest available precondition and the least ambiguous.
- Existing plans must continue to receive exact same-document behavior.
- Stable pages should not be encouraged to use a weaker composition.
- It provides a reference implementation for evidence, failure mapping, and
  backward-compatibility tests.

No other condition safely reproduces complete URL equality. A combination of
origin, path, and selected query conditions intentionally ignores undeclared
components and is therefore not equivalent.

Removing `EXACT_URL` would both break compatibility and weaken the architecture.

### ORIGIN_EQUALS — KEEP

`ORIGIN_EQUALS` is foundational when exact URL is not used.

Path and DOM facts alone can be satisfied on an unintended origin. Requiring
hosts to encode the origin through `URL_CONTAINS` would be weaker and sensitive
to string placement. Requiring `EXACT_URL` would recreate the transient-URL
problem.

The normalized `(scheme, host, effective port)` tuple is small, deterministic,
and standards-based. It allows a host to say “this route and DOM landmark must
belong to this origin” without coupling to volatile path/query suffixes.

Its maintenance cost is low because URL parsing is already necessary for path
and query conditions.

### PATH_EQUALS — KEEP

`PATH_EQUALS` is a core route-identity primitive.

It cannot be replaced safely by:

- `URL_CONTAINS`, which is weaker and raw-string based;
- `EXACT_URL`, which includes irrelevant transient query state;
- `ELEMENT_VISIBLE`, which does not attest the browser route.

Most applications have stable routes even when query parameters vary.
Literal decoded-path equality is deterministic and straightforward to test.

### PATH_STARTS_WITH — KEEP

`PATH_STARTS_WITH` initially appears convenient, but it covers one capability
that the smaller alternatives cannot: a stable route family with a legitimately
generated path suffix.

Generic examples include:

```text
/documents/<generated-id>
/sessions/<generated-id>/summary
/media/<generated-id>
```

Neither `PATH_EQUALS` nor `QUERY_PARAM_EQUALS` can describe those pages.
`URL_CONTAINS` would be a weaker raw-string substitute. A visible element alone
does not attest the route.

The condition remains deterministic because it is a literal prefix, not a
wildcard or pattern. It should be retained with the proposal's strict
validation:

- leading `/` required;
- `?` and `#` forbidden;
- `/` alone rejected;
- case-sensitive decoded-path comparison;
- hosts should compose it with `ORIGIN_EQUALS`;
- segment-boundary-sensitive prefixes should include the trailing `/`.

This is the one “partial” URL condition required for transient path support in
Version 1.

### URL_CONTAINS — REMOVE

`URL_CONTAINS` is not necessary once Version 1 has:

- `ORIGIN_EQUALS`;
- `PATH_EQUALS`;
- `PATH_STARTS_WITH`; and
- `QUERY_PARAM_EQUALS`.

Its unique capability is matching an arbitrary literal across the raw URL. That
capability is broad but not architecturally strong. It introduces questions
that the parsed conditions avoid:

- whether matching occurs before or after percent decoding;
- whether a substring in a query value can impersonate a host/path fact;
- whether case or default-port normalization applies;
- whether the same text in a fragment counts;
- whether parameter ordering affects the intended assertion.

Those questions are answerable, but maintaining the answers adds surface area
for a condition that encourages less precise plans.

Removing it does not sacrifice the target capability: hosts can identify stable
origin, route, route family, and semantic query state explicitly. If some future
use case truly cannot be represented by those facts, it should motivate a
specific typed condition rather than restore arbitrary raw-URL substring
matching.

### QUERY_PARAM_EXISTS — POSTPONE

`QUERY_PARAM_EXISTS` is deterministic and not exactly replaceable by
`QUERY_PARAM_EQUALS`, but it is not necessary for the initial problem.

There are three query categories:

1. Stable semantic key and value: use `QUERY_PARAM_EQUALS`.
2. Transient/session parameter irrelevant to page identity: do not declare it.
3. Key presence semantically matters but its value does not: this is the unique
   `QUERY_PARAM_EXISTS` case.

The third category is valid, but less central. It also forces early decisions
about:

- `?flag` versus `?flag=`;
- one versus repeated occurrences;
- decoded key equality;
- whether a blank value is “present”;
- how duplicate values appear in evidence.

Postponing it leaves Version 1 smaller without preventing the main transient-URL
solution. It is a good Version 2 candidate after real plans demonstrate
presence-only page identity.

It should not be emulated by declaring an empty
`QUERY_PARAM_EQUALS`; blank equality and presence are different semantics.

### QUERY_PARAM_EQUALS — KEEP

`QUERY_PARAM_EQUALS` is foundational.

It lets the host require stable semantic state while omitting unrelated
transient parameters:

```text
path == "/search"
query["q"] == "wireless mouse"
```

Neither path conditions nor DOM visibility attest the query's declared value.
Exact URL is too strong when additional parameters legitimately vary.

The proposed fail-closed semantics should remain:

- exactly one occurrence of the decoded key;
- exact decoded value equality;
- zero or duplicate occurrences fail.

This keeps the evaluator deterministic and avoids implicit OR over duplicates.

### TITLE_CONTAINS — POSTPONE

`TITLE_CONTAINS` is not required in Version 1.

Page titles are observable, but they are often:

- localized;
- prefixed/suffixed by branding;
- asynchronously updated;
- duplicated across routes;
- changed for notifications or unread counts.

Those facts do not make title matching nondeterministic—the declared literal
comparison is deterministic—but they make it a comparatively fragile identity
primitive.

Version 1 already supports URL structure plus one strong visible DOM landmark.
That combination usually expresses the same intent more directly.

Postponement also avoids adding a new page-metadata evidence path before the
core URL/DOM evaluator matures. Title matching can be added in Version 2 with
explicit evidence and case-sensitive literal semantics if actual generic use
cases justify it.

### ELEMENT_EXISTS — POSTPONE

`ELEMENT_VISIBLE` does **not** completely replace `ELEMENT_EXISTS`.

An element can legitimately exist while hidden, offscreen, collapsed, or used
as a nonvisual state carrier. Therefore this review does not recommend claiming
semantic equivalence or permanently removing existence checks.

However, `ELEMENT_EXISTS` is not essential to the first page-identity
foundation. For a pre-dispatch safety gate, a visible page landmark is usually
stronger:

- it confirms unique resolution;
- it confirms user-visible page state;
- it is suitable for an action about to interact with the page;
- it avoids treating hidden templates or inactive carousel panels as identity.

Starting with one DOM primitive reduces documentation and result-mapping
branches. `ELEMENT_EXISTS` should be a Version 2 candidate for proven cases
where nonvisual DOM presence is a legitimate page requirement.

It must not later be implemented as “visible or hidden” fallback behavior;
existence and visibility remain separate typed semantics.

### ELEMENT_VISIBLE — KEEP

`ELEMENT_VISIBLE` is the minimal strong DOM precondition.

URL structure alone may not distinguish:

- route shells before content is ready;
- two application states sharing one route;
- a regional/interstitial page retaining the requested URL;
- an authenticated versus unauthenticated view on the same path.

A host-declared visible element gives evidence of the rendered page state
without inference. Exactly-one resolution remains fail-closed:

- zero matches: fail;
- multiple matches: indeterminate and block;
- one hidden match: fail;
- one visible match: pass.

Keeping this single DOM condition gives Version 1 composable URL + rendered-page
identity without importing the entire expectation vocabulary.

### ELEMENT_COUNT — POSTPONE

Exact element count has unique capability, but it is not foundational to page
identity.

It requires a separate resolver mode that observes a primary match set without
selecting a target or enforcing exactly-one cardinality. It also creates
long-term questions about:

- dynamic virtualized lists;
- detached elements during observation;
- frame scoping;
- whether visible count and total count need separate types;
- evidence size and candidate summaries.

Version 1's `ELEMENT_VISIBLE` deliberately answers the safer question: “does
this declared landmark resolve uniquely and visibly?” Exact list cardinality is
more often business/content verification than page identity.

Postpone it until the core precondition evaluator and evidence schema are
stable. If added, retain exact equality only; do not introduce range operators
implicitly.

### TYPED_EXPECTATION — REMOVE

`TYPED_EXPECTATION` should not be part of the PagePrecondition vocabulary.

Although it is closed over today's `ExpectationType`, it creates a conceptual
escape hatch:

- every future expectation risks becoming a precondition automatically;
- post-action freshness semantics do not necessarily make sense
  pre-dispatch;
- network expectations are already incompatible;
- URL and DOM cases duplicate named precondition conditions;
- validation becomes “all expectations except these,” which grows over time;
- the PagePrecondition contract becomes coupled to a separate feature's
  lifecycle and versioning.

The strongest architecture names each accepted page fact explicitly. If a
future expectation reveals a genuinely fundamental precondition fact, that fact
should receive its own reviewed condition type and semantics.

Removing this condition reduces maintenance without losing Version 1
capability. It should not be reserved as a Version 2 item; any future proposal
should require a new architecture review rather than enabling a generic wrapper.

## Recommended Version 1 vocabulary

```python
class PageConditionType(str, Enum):
    EXACT_URL = "exact_url"
    ORIGIN_EQUALS = "origin_equals"
    PATH_EQUALS = "path_equals"
    PATH_STARTS_WITH = "path_starts_with"
    QUERY_PARAM_EQUALS = "query_param_equals"
    ELEMENT_VISIBLE = "element_visible"
```

### Why these six are sufficient

They cover six irreducible identity facts:

| Fact | Condition |
|---|---|
| Complete stable document identity | `EXACT_URL` |
| Correct scheme/host/port | `ORIGIN_EQUALS` |
| Exact stable route | `PATH_EQUALS` |
| Stable route family with generated suffix | `PATH_STARTS_WITH` |
| Stable semantic query state amid transient parameters | `QUERY_PARAM_EQUALS` |
| Correct uniquely rendered page state | `ELEMENT_VISIBLE` |

The vocabulary supports strong compositions such as:

```text
origin == "https://catalog.example"
AND path == "/search"
AND query["q"] == "wireless mouse"
AND unique visible results landmark
```

and:

```text
origin == "https://media.example"
AND path starts with "/clips/"
AND unique visible player landmark
```

No arbitrary URL matching or generic expectation wrapper is needed.

### Recommended Version 1 guardrails

- Continue legacy implicit exact URL behavior when no explicit precondition is
  present.
- Recommend `ORIGIN_EQUALS` whenever an explicit precondition uses path/query
  conditions.
- Consider a validation requirement—not merely a warning—that explicit
  preconditions containing URL-structural conditions must include either
  `EXACT_URL` or `ORIGIN_EQUALS`.
- Keep AND-only composition.
- Keep one-shot evaluation with no hidden wait.
- Keep exactly-one semantics for `ELEMENT_VISIBLE`.
- Reject empty condition sets and duplicate condition IDs.
- Preserve declaration order and per-condition evidence.

Requiring an origin anchor would make the reduced vocabulary stronger, but that
specific validation policy should be confirmed during the existing architecture
review rather than silently added here.

## Recommended Version 2 candidates

Version 2 should not automatically add every postponed condition. These are
candidates, in priority order, contingent on evidence from real generic plans:

1. **`QUERY_PARAM_EXISTS`**
   - Add only if presence-only semantic query state is common.
   - Specify blank and duplicate-key behavior first.
2. **`ELEMENT_EXISTS`**
   - Add for legitimate nonvisual page landmarks.
   - Keep distinct from visibility.
3. **`TITLE_CONTAINS`**
   - Add only if URL + visible landmark cannot reasonably identify important
     generic page states.
   - Retain literal, case-sensitive semantics.
4. **`ELEMENT_COUNT`**
   - Add after a dedicated non-selecting count evidence path is designed and
     virtualized/dynamic-list semantics are documented.

`URL_CONTAINS` and `TYPED_EXPECTATION` are not Version 2 recommendations.

## Direct answers to the additional review questions

### Is URL_CONTAINS necessary?

No. Origin, exact/prefix path, and exact query-value conditions cover the
maintainable stable URL facts. `URL_CONTAINS` is weaker and introduces raw URL
encoding and placement ambiguity. **REMOVE.**

### Is PATH_STARTS_WITH fundamental?

Yes, if the foundation is intended to handle transient path components as well
as transient query components. It is a literal deterministic primitive, not a
wildcard. Without it, generated path IDs force exact URL coupling or DOM-only
identity. **KEEP.**

### Is QUERY_PARAM_EXISTS needed with QUERY_PARAM_EQUALS?

It has distinct semantics but is not needed for the initial goal. Stable
semantic values use equality; irrelevant transient parameters are omitted.
Presence-only identity can wait for demonstrated demand. **POSTPONE.**

### Can ELEMENT_VISIBLE completely replace ELEMENT_EXISTS?

No. Visibility implies existence, but existence does not imply visibility.
They are not semantically interchangeable. Nevertheless, visible unique
landmarks are the stronger minimal Version 1 page-identity primitive.
**KEEP `ELEMENT_VISIBLE`; POSTPONE `ELEMENT_EXISTS`.**

### Is ELEMENT_COUNT fundamental?

No. It is valuable for exact content/cardinality assertions but adds a distinct
non-selecting resolution path and dynamic-list semantics. **POSTPONE.**

### Should TITLE_CONTAINS exist in Version 1?

No. URL structure plus a unique visible page landmark supplies a stronger and
more stable initial foundation. **POSTPONE.**

### Should TYPED_EXPECTATION be included immediately?

No. It couples preconditions to a broader, evolving post-action expectation
system and acts as an extension escape hatch. Explicit named conditions are
more maintainable. **REMOVE.**

## Maintenance impact

Reducing from twelve to six types removes:

- one raw-string URL evaluator;
- one duplicate/blank query semantic branch;
- one page-title evidence path;
- one hidden-element semantic branch;
- one non-selecting element-count resolver path;
- one cross-contract adapter for general expectations.

It also reduces:

- JSON discriminant combinations;
- validation cases;
- receipt result variants;
- browser integration tests;
- documentation examples;
- future compatibility coupling.

The retained six still require only three observation families:

1. one parsed URL snapshot;
2. the existing exact URL comparator;
3. one exactly-one visible DOM observation.

That is a materially smaller implementation and testing surface.

## Final opinion

The architecture becomes stronger by reducing the initial vocabulary.

The six-condition Version 1 is not merely smaller; it is more coherent:

- exact URL handles stable pages and backward compatibility;
- origin/path/query composition handles transient URL components;
- path prefix covers generated path suffixes without patterns;
- one visible DOM landmark attests rendered page state;
- every condition has a distinct, non-overlapping architectural role.

Removing `URL_CONTAINS` and `TYPED_EXPECTATION` prevents weak or expansive
escape hatches. Postponing presence-only query checks, title checks, hidden
existence, and exact counts avoids committing to secondary semantics before the
core evidence model matures.

Version 1 should therefore launch with:

```text
EXACT_URL
ORIGIN_EQUALS
PATH_EQUALS
PATH_STARTS_WITH
QUERY_PARAM_EQUALS
ELEMENT_VISIBLE
```

Everything else should require later evidence and a focused design review.
