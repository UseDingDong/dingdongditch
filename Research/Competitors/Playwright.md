# Playwright

**Category:** Classic automation library  
**Sources:** playwright.dev docs; industry comparisons 2025–2026  
**Labels used below:** FACT / EVIDENCE / PATTERN

## Purpose

Reliable cross-browser automation and E2E testing for Chromium, Firefox, and WebKit.

## Architecture

- Client library communicates with browser engines over native debugging protocols (CDP for Chromium; custom bridges for Firefox/WebKit). **FACT**
- **BrowserContext** isolates cookies/storage like an incognito profile; multiple pages/tabs share a context. **FACT**
- **Auto-waiting / actionability:** before click/fill/etc., waits until element is visible, stable, enabled, and receiving events (within timeout). **FACT** (playwright.dev/docs/actionability)
- **Network:** route interception, waitForResponse, HAR, etc. **FACT**
- **Evidence artifacts:** trace viewer (DOM snapshots + network + console timeline), screenshots, video. **FACT**

## Primary audience

QA engineers, application developers, CI/CD pipelines.

## Core design philosophy

Reduce flakiness by making the framework wait for *actionability*, not fixed sleeps; prioritize developer diagnostics (traces) over silent retries alone.

## Strengths

- Multi-browser with unified API. **FACT**
- Auto-wait eliminates large class of Selenium-era sleep flakes. **EVIDENCE/PATTERN**
- Network control and storageState for auth reuse. **FACT**
- Trace-on-retry culture for diagnosing intermittency. **EVIDENCE**

## Weaknesses

- Auto-wait checks DOM actionability, **not** application-level success (e.g., API completed, table refreshed). **FACT/PATTERN**
- Flakes remain from racey route registration, shared storageState mutation, service workers, headed vs headless differences. **EVIDENCE** (Mergify / community guides)
- Designed for scripted tests with known flows — open-ended agent goals are outside original design center. **PATTERN**
- Automation detection / anti-bot still applies. **EVIDENCE**

## Adoption

Widely cited as the default modern E2E framework in 2025–2026 comparisons. Exact star counts change; treat as high-adoption. **EVIDENCE**

## Relationship to AI agents

- Substrate underneath many AI tools (MCP, Stagehand historically, agent wrappers).
- Escape hatch when MCP token cost / flakiness is unacceptable: agents write Playwright scripts directly. **EVIDENCE** (HN discussions)
- Provides verification primitives agents often underuse (assertions, traces). **PATTERN**
