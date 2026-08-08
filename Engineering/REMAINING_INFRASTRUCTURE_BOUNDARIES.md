# Remaining Infrastructure Boundaries

This document records the deliberately narrow contracts added after the
three-layer receipt architecture. They extend the existing operation pipeline;
none introduces planning, retries, heuristic locator repair, or workflow
control flow.

## Network evidence and artifacts

`ExpectationType.NETWORK` observes bounded request/response metadata only.
Assertions may require a method, query-free URL/path matcher, request
observation, response observation, response status, and a measured
request-to-response duration. A matching assertion must have exactly one
post-action record. Zero records is `NOT_VERIFIED`; more than one is
`INDETERMINATE` rather than arbitrarily choosing one.

Network headers and request/response bodies are never collected into
evidence. URLs in published evidence omit query strings and fragments. The
core receipt contains only the expectation outcome. Bounded evidence contains
at most four sanitized candidates. `NetworkArtifactRequest` is an explicit
Layer-3 request for a bounded sanitized JSON trace. Its receipt entry contains
only an ID, filename, checksum, and count; never an absolute path. Per-
operation HAR is intentionally unsupported because Playwright HAR recording is
context-wide and can collect unrelated traffic and headers.

## Portable browser state

`AuthenticationCapability.export_session()` writes portable-state schema v2
and returns a `PortableStateReceipt`. It can explicitly include cookies,
localStorage, and (when the backend supports `storage_state(indexed_db=True)`)
IndexedDB. localStorage entries with sensitive key names or token-shaped values
are omitted. Cookies are portable browser state only when an export is
explicitly requested; callers must protect the exported file as sensitive
session material. DingDongDitch does not retain the file or treat it as a
credential vault.

Import validates the entire document before mutating a context. It rejects
malformed data, duplicate/unsafe origins, oversize state, stale or
clock-ambiguous v2 documents, and unsupported IndexedDB import. Active-context
import supports cookies and localStorage. `prepare_session_import()` supports
validated IndexedDB only at new ephemeral-context creation, using Playwright's
storage-state input; it never writes IndexedDB through evaluated page code.

Portable:

- Explicitly exported cookies
- Sanitized localStorage for explicit HTTP(S) origins
- Opt-in IndexedDB only for a newly created ephemeral Playwright context

Not portable:

- sessionStorage
- Password managers, browser credential vaults, passkeys, private keys
- Browser profile internals, extensions, service workers, caches, history,
  permissions, downloads, or arbitrary browser preferences
- Existing-user Firefox/WebKit profiles and arbitrary on-disk browser profiles

Legacy schema v1 cookie/localStorage files remain importable for compatibility;
their receipt says `completed_legacy` because a v1 file has no staleness
timestamp.

## Persistent profile capability matrix

| Engine | Isolated named/DingDong profile | Existing `default` profile | Notes |
| --- | --- | --- | --- |
| Chromium | SUPPORTED | PARTIALLY_SUPPORTED | `default` means existing Chrome Default only; treat it as sensitive user state. |
| Firefox | SUPPORTED | UNSUPPORTED | No mapping to an existing user profile is attempted. |
| WebKit | SUPPORTED | UNSUPPORTED | Only an isolated Playwright persistent directory is used. |

All isolated profiles use `launch_persistent_context` for their selected engine,
with no engine fallback. Named profile data is engine-isolated. A process lease
remains exclusive across the named profile and clean shutdown releases it.
Receipts include the selected engine and its profile capability classification.

## Secrets

`SecretProvider` is a host-owned adapter. A plan carries only a validated
`SecretReference`; an `Action(FILL, secret_reference=...)` resolves it at
execution time with a bounded timeout. Values must be returned as an ephemeral
`SecretValue`, are cleared after the one browser fill, and never appear in a
receipt, action description, log payload, or serialized plan. Provider timeout,
missing reference, invalid wrapper, and provider failure have structured
failure kinds. `MappingSecretProvider` is an in-memory development/test helper,
not a persistent secret store.

## WebAuthn/passkeys

`WebAuthnParticipationRequest` is explicit per operation and contains only an
opaque request ID and timeout. `WebAuthnTransport` is host controlled. The
runtime sends metadata (engine and HTTP(S) page origin) to the host and receives
only a bounded status: completed, rejected, unsupported, timed out, or
indeterminate.

The runtime never creates a virtual authenticator, extracts private keys,
persists credentials, supplies challenges/assertions, or bypasses browser or
native authenticator security. Runtime native-authenticator control is
UNSUPPORTED for Chromium, Firefox, and WebKit. A completed host callback is not
browser verification: without independent post-action expectations the
operation remains `INDETERMINATE`; it can be `VERIFIED` only when those normal
browser expectations pass.
