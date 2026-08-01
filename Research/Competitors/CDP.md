# Chrome DevTools Protocol (CDP)

**Category:** Protocol / primitive  
**Sources:** chromedevtools.github.io/devtools-protocol; Chromium docs  
**Labels:** FACT / EVIDENCE / PATTERN

## Purpose

Allow tools to instrument, inspect, debug, and profile Chromium and other Blink-based browsers.

## Architecture

- JSON-RPC messages over WebSocket to a debugging endpoint (`--remote-debugging-port`). **FACT**
- Organized into **domains** (DOM, Network, Page, Runtime, Input, Accessibility, Target, …). Each domain exposes commands and events. **FACT**
- Clients attach to **Targets** (page, iframe, worker, browser) and receive **session IDs**. **FACT**
- Stable vs experimental APIs — experimental surfaces change regularly. **FACT**

## Primary audience

DevTools, automation library authors, performance profilers, AI browser runtime builders.

## Core design philosophy

Expose browser internals as a protocol rather than a product API. Higher-level libraries (Puppeteer, Playwright, Stagehand v3 CDP path, Browser Use CDP path) are opinionated skins.

## Strengths

- Event-driven observability (network, DOM, console). **FACT**
- Fine-grained input injection and DOM inspection. **FACT**
- Shared substrate across nearly all modern Chromium automation. **PATTERN**

## Weaknesses

- Not a user-facing reliability layer — no auto-wait philosophy by itself. **FACT**
- Chromium-centric; Firefox/WebKit need other protocols. **FACT**
- Protocol side effects can be detectable (`Runtime.enable` class tells). **EVIDENCE**
- Verbose; easy to misuse without a higher-level policy for waiting/verification. **PATTERN**

## Adoption

Ubiquitous under the hood. **FACT/PATTERN**

## Relationship to AI agents

**PATTERN:** AI browser stacks either wrap CDP via Playwright/Puppeteer or speak CDP directly. Competing on “who wraps CDP” is not differentiating; competing on **state sync, verification, recovery, and trust boundaries** might be.
