# Skyvern

**Category:** Autonomous / workflow browser agent (APA / RPA replacement)  
**Sources:** Skyvern blogs; AgentsCamp; State of Browser Use May 2026  
**Labels:** EVIDENCE / PATTERN

## Purpose

Automate multi-step business portal workflows using vision + LLM reasoning, including unglamorous requirements (CAPTCHA, 2FA/TOTP, proxies), with self-host or cloud.

## Architecture

- Vision-first grounding when DOM is hostile. **EVIDENCE**
- Workflow definitions via chat/SOP/recordings. **EVIDENCE**
- Code-gen mode: emit Playwright to reduce ongoing vision cost. **EVIDENCE**
- MCP server wraps execution for Claude/Cursor/etc. **EVIDENCE**
- License: AGPL + commercial. **EVIDENCE**

## Primary audience

Operations teams replacing brittle RPA; procurement/portal automation.

## Core design philosophy

Real portals break selector automation; include auth friction and visual understanding in the product scope rather than pretending login is free.

## Strengths

- Explicit CAPTCHA/2FA story uncommon in pure DOM agents. **EVIDENCE**
- Self-hostable for sensitive workflows. **EVIDENCE**
- Harder internal benchmarks (WebBench) cited vs saturated WebVoyager. **EVIDENCE**

## Weaknesses

- Vision cost and latency. **PATTERN**
- AGPL may constrain some commercial embeddings. **EVIDENCE**
- Still far from human reliability on live write tasks (category-wide). **EVIDENCE**
- MCP mode offloads work to Skyvern’s engine — different trust/control model than local Playwright MCP. **PATTERN**

## Adoption

~20k+ stars cited; Reddit consensus for hard multi-tab/2FA flows often names Skyvern. **EVIDENCE**

## Relationship to AI agents

Browser agent + platform; also an MCP *execution engine* (agent calls Skyvern, not low-level clicks).
