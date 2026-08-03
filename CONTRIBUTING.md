# Contributing to DingDongDitch

Thank you for considering a contribution. DingDongDitch is an early-stage,
plan-consuming browser execution runtime. It is not a planner, AI assistant,
workflow authoring system, browser, or Playwright replacement.

## Before you start

- Search existing issues and discussions before proposing work.
- Use an issue for reproducible defects and narrowly scoped enhancements.
- Discuss substantial behavior, contract, dependency, or architecture changes
  before implementation.
- Read `Engineering/ENGINEERING_PRINCIPLES.md` and
  `Engineering/NON_GOALS.md`. Changes must preserve the host/runtime boundary.

Please do not submit secrets, credentials, private browser data, or production
session artifacts. Report vulnerabilities according to `SECURITY.md`.

## Development setup

DingDongDitch requires Python 3.11 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m playwright install chromium firefox webkit
python -m pytest tests -v
```

Browser installation and integration tests may require platform-specific
system dependencies. The optional Windows desktop backend additionally uses
the `windows-desktop` extra.

## Pull requests

Keep changes focused and include tests for observable behavior changes. Update
public documentation and `CHANGELOG.md` when users are affected. Preserve
backward compatibility when practical; call out contract changes explicitly.

Before submitting, run the relevant tests and state exactly what was run. Do
not commit generated browser profiles, credentials, downloads, screenshots, or
experiment output unless they are intentional, reviewed fixtures.

By contributing, you agree that your contribution is licensed under the MIT
License and that you will follow the Code of Conduct.
