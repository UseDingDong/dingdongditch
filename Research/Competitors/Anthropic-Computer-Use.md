# Anthropic Computer Use

**Category:** Computer-use API primitive (desktop + browser via GUI)  
**Sources:** Anthropic announcement; platform.claude.com computer-use-tool docs; WorkOS comparison  
**Labels:** FACT / EVIDENCE / PATTERN

## Purpose

Allow Claude to use a computer the way humans do: see screenshots, move cursor, click, type — via an API tool, with the developer owning the environment and agent loop.

## Architecture

- Model emits tool_use actions (screenshot, mouse, keyboard, etc.). **FACT**
- Developer must provide: virtual display (Xvfb), desktop environment, applications, tool implementations mapping actions → OS events, and the agent loop. **FACT**
- Coordinate systems interact with image scaling/downscaling rules — misuse causes mis-clicks. **FACT** (docs warn about scale factors)
- Recommended sandboxed containers; Anthropic acknowledges experimental error-prone nature. **FACT**

## Primary audience

Developers building custom agent systems needing GUI control beyond web DOM APIs.

## Core design philosophy

Pixels as the universal interface; generality over web-specific structure.

## Strengths

- Works across desktop apps, not only browsers. **FACT**
- Developer owns orchestration, logging, isolation. **FACT**
- Explicit vendor honesty about limitations (scrolling, dragging, zooming). **FACT**

## Weaknesses

- High latency per observe–act cycle (often cited multi-second). **EVIDENCE**
- Screenshot token cost. **EVIDENCE**
- Visual ambiguity; poor for precise structured extraction vs DOM. **PATTERN**
- Safety: prompt injection + privileged session is severe. **FACT/PATTERN**
- Execution success (clicked) ≠ task success. **PATTERN**

## Adoption

Influential primitive; many higher-level agents compose it or imitate its loop. **PATTERN**

## Relationship to AI agents

Provides **perception + action vocabulary**, not a browser reliability layer. The gap between “can click” and “reliably completed web workflow” remains the integrator’s problem.
