# L09 — Evidence must outrank screenshots alone

## Lesson

Postmortems and online verification need bundled signals (DOM/a11y, network, console, dialogs, downloads, timestamps) — screenshots alone are insufficient archaeology.

## Why this lesson exists

Computer-use and many agents default to pixels for both control and debug. Meanwhile Playwright’s trace viewer and Chrome DevTools MCP exist because humans already learned screenshots aren’t enough for flaky UI systems.

## Evidence supporting it

- Playwright trace viewer: DOM + network + console timeline. **FACT**
- Chrome DevTools for agents positioning. **FACT**
- ABP bundles notable events (navigation, file pickers, permissions, alerts, downloads) with state. **EVIDENCE**
- CAPTCHA debugging guides demand widget state + network + storage, not only screenshots. **EVIDENCE**

## Projects demonstrating it

Playwright; Chrome DevTools MCP; ABP; Browserbase session recordings; computer-use (negative example when screenshot-only).

## Mistakes to avoid

- Equating “we recorded the screen” with “we can explain the failure”
- Dropping network/console to save cost without a replacement evidence channel

## Engineering implication

Evidence collection is part of the execution contract, not an optional debug flag.
