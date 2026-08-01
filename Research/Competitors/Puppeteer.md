# Puppeteer

**Category:** Classic automation library  
**Sources:** Puppeteer docs; Firecrawl/ByteTunnels comparisons 2026  
**Labels:** FACT / EVIDENCE / PATTERN

## Purpose

Node.js library to control Chrome/Chromium via the Chrome DevTools Protocol.

## Architecture

- Direct CDP over WebSocket — no WebDriver middleman. **FACT**
- Chromium-first (Firefox support historically secondary/limited vs Playwright). **FACT/EVIDENCE**
- Locator API with waiting behaviors improved over early Puppeteer eras. **EVIDENCE**

## Primary audience

Node developers automating Chrome for testing, scraping, PDF/screenshot generation, performance tooling.

## Core design philosophy

Stay close to Chrome’s native debugging protocol; thin high-level API over CDP domains.

## Strengths

- Low latency vs WebDriver. **EVIDENCE**
- Deep Chromium capabilities (coverage, tracing, network). **FACT**
- Same protocol family that AI stacks eventually need. **PATTERN**

## Weaknesses

- Not multi-browser first-class like Playwright. **FACT**
- Still scripted automation — no AI perception loop. **FACT**
- Detection surface of CDP-based automation remains. **EVIDENCE**

## Adoption

Long-standing Google/Chrome ecosystem standard; large installed base. **EVIDENCE**

## Relationship to AI agents

Often appears under Chrome DevTools MCP / agent Chrome control. Less often chosen as the named “browser agent framework.”
