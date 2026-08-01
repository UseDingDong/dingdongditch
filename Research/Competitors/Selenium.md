# Selenium

**Category:** Classic automation library  
**Sources:** W3C WebDriver; industry architecture comparisons  
**Labels:** FACT / EVIDENCE / PATTERN

## Purpose

Cross-language, cross-browser UI automation via the W3C WebDriver standard.

## Architecture

- Test code → language binding → HTTP WebDriver protocol → browser-specific driver → browser. **FACT**
- Request/response historically; WebDriver BiDi adds bidirectional capabilities. **FACT**
- Selenium 4 can access some CDP features on Chromium but treats deep DevTools paths carefully as standards evolve. **EVIDENCE**

## Primary audience

Enterprise QA organizations, polyglot teams, legacy automation estates.

## Core design philosophy

Portability and standards over engine-native intimacy.

## Strengths

- Broadest historical language/browser matrix. **FACT**
- Institutional knowledge, Grid, vendor integrations. **EVIDENCE**
- Explicit waits allow custom conditions. **FACT**

## Weaknesses

- Extra hops → latency; typically slower than CDP libraries. **EVIDENCE**
- More flakiness historically without careful wait discipline. **PATTERN**
- Stronger automation fingerprints via driver injection historically. **EVIDENCE**
- Poor fit as modern AI agent substrate (few 2026 AI browser stacks build primarily on Selenium). **PATTERN**

## Adoption

Still enormous legacy footprint; declining share of *new* AI-adjacent greenfield projects. **EVIDENCE/PATTERN**

## Relationship to AI agents

Occasionally wrapped; rarely the preferred execution layer for LLM agents in 2026 field surveys.
