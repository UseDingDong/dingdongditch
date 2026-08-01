# OpenAI Browser / Computer-Use Tooling

**Category:** Managed browser agent / CUA product lineage  
**Sources:** WorkOS comparison; OpenHermit June 2026; industry summaries  
**Labels:** EVIDENCE / PATTERN / UNKNOWN  
**Caution:** Product packaging changed through 2025–2026 (Operator → ChatGPT Agent). Re-verify details before citing in design docs.

## Purpose

Provide a packaged agentic browsing experience (and related computer-using model capabilities) with hosted runtime and safety/product opinionation — historically contrasting Anthropic’s DIY API.

## Architecture (as reported)

- **Operator era:** cloud virtual browser; human-in-the-loop for sensitive actions like logins; focused on web tasks. **EVIDENCE**
- **2025–2026:** standalone Operator deprecated/merged into broader ChatGPT Agent mode combining visual browser + text browser + terminal (per secondary reports). **EVIDENCE** — exact current public API surface is **UNKNOWN** without checking OpenAI docs at design time
- CUA-class models reason over screenshots and emit GUI actions. **EVIDENCE**

## Primary audience

End users and organizations wanting a managed agent rather than building a control plane.

## Core design philosophy

Productized safety + hosted environment over maximum developer control.

## Strengths

- Lower setup burden. **EVIDENCE**
- Built-in human gates for sensitive steps. **EVIDENCE**
- Strong brand distribution. **PATTERN**

## Weaknesses

- Less hackable / portable as infrastructure. **PATTERN**
- Vendor lock-in; limited as a universal open execution layer. **PATTERN**
- Same category failures: visual ambiguity, latency, hostile pages, injection. **PATTERN**

## Adoption

High awareness; not an open substrate for third-party universal execution layers. **PATTERN**

## Relationship to AI agents

Closed product agent. Useful competitive intelligence for UX/safety patterns; poor template for open universal infrastructure unless OpenAI publishes stable low-level execution APIs (status: track as **UNKNOWN**).
