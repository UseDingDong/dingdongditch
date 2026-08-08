# Changelog

All notable changes to DingDongDitch are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Pre-1.0 releases may include
breaking changes.

## [Unreleased]

## [0.4.0] - 2026-08-08

### Added

- `StatefulSessionRuntime`, a host-owned incremental
  `open -> observe -> execute -> verify -> close` session facade that keeps the
  existing deterministic executor and does not expose Playwright objects.
- Fail-closed `upload_file` actions with explicit file/root authorization,
  path-redacted receipts, and fresh post-upload verification that can recognize
  legitimate input replacement or attachment UI changes.
- Deterministic `select_combobox_option` support for explicitly associated
  custom combobox/autocomplete options; typing or pressing Enter alone is not
  accepted as a selection.
- Rich bounded guarded branches, including an explicit `otherwise` branch;
  ambiguous branch matches are indeterminate rather than chosen arbitrarily.
- Explicit bounded nested iframe `frame_path` targeting for actions, waits,
  expectations, preconditions, inspection, and JSON plans.
- Bounded failed-verification evidence, standard per-operation timing, and the
  formal three-layer Core Receipt / Bounded Evidence / Artifact architecture.
- Expanded deterministic network assertions for request/response observation,
  method, query-free URL/path matching, response status, and observable timing.
  Optional sanitized network traces are external artifacts rather than receipt
  payloads.
- Portable browser-state schema v2 with validation, safe origin association,
  sensitive localStorage exclusion, and opt-in IndexedDB export/import for the
  documented new-context boundary.
- Isolated persistent profiles for Chromium, Firefox, and WebKit where
  Playwright supports them, with engine-specific data directories and profile
  capability information in receipts.
- Generic `SecretProvider` / `SecretReference` execution-time secret injection
  and bounded, host-controlled WebAuthn participation transports.

### Changed

- Execution receipt schema is now **1.8.0**. `to_core_dict()`,
  `to_bounded_evidence_dict()`, and `to_layered_dict()` expose the layered
  receipt representation; legacy `to_dict()` remains available with additive
  fields.
- Public contracts add `GuardBranch`, `UploadAuthorization`,
  `ComboboxSelection`, network artifact/match types, portable-state types,
  secret-resolution types, WebAuthn transport types, and stateful-session APIs.
- `execute_operation()` and `execute_plan()` accept optional host authentication
  capability injection. Existing text-based fills and legacy secret providers
  remain supported.

### Limitations and security boundaries

- Per-operation HAR capture is not supported; only explicitly requested,
  bounded sanitized network traces are available.
- DingDongDitch has no native WebAuthn authenticator control, virtual
  authenticator, private-key extraction, or authentication-bypass behavior.
- Secret providers are host-owned; the runtime is not a credential vault and
  does not persist or log resolved values.
- There is no browser-engine fallback and no migration of an existing user
  profile between Chromium, Firefox, or WebKit. Chromium's existing `default`
  profile is only partially supported; Firefox/WebKit existing-user profiles
  are unsupported.
- IndexedDB can be imported only while creating a new ephemeral context; it is
  not injected into an active context. Session storage, password managers,
  passkeys, browser-profile internals, extensions, caches, and history are not
  portable state.
- Uploads support explicitly authorized HTML file inputs only. Directory
  uploads, native file dialogs, programmatic file-chooser trigger buttons, and
  wildcard/discovery paths are unsupported.

## [0.3.0] - 2026-08-05

### Added

- Production authentication callbacks, named persistent profiles and sessions,
  and deterministic guarded optional target actions.

## [0.1.0] - 2026-08-03

### Added

- Initial public release.
