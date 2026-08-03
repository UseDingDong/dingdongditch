# Security Policy

## Supported versions

DingDongDitch is pre-1.0 software. Security fixes are provided only on the
latest revision of the default branch. Older versions and unreleased forks are
not supported.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include secrets,
credentials, private browsing data, or exploit details in public discussions.

Use **Security > Report a vulnerability** in this GitHub repository to submit
a private report. Include the affected revision, environment, impact, minimal
reproduction steps, and any suggested mitigation. If private vulnerability
reporting is unavailable, contact a maintainer privately through their GitHub
profile before disclosing details.

Maintainers will acknowledge reports when capacity permits, investigate them,
and coordinate disclosure with the reporter. Because this project is currently
maintained on a best-effort basis, no response or remediation deadline is
guaranteed.

## Security model

DingDongDitch executes host-authored plans in real browsers. Plans and URLs
must be treated as untrusted input. Persistent browser profiles can expose
authenticated sessions and browser-local data; they are not security
sandboxes. Use the fresh `benchmark` profile unless persistent state is
explicitly required, restrict download artifact locations, and never commit
credentials or captured private data.
