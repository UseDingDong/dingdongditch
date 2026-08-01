# L15 — Tool success is a dangerous reward signal

## Lesson

When training, prompting, or looping agents, treating tool-level success as reward causes false progress, premature stopping, or looping on locally successful but globally useless actions.

## Why this lesson exists

Same root as L01, but specifically about **control-loop incentives**. Agents maximize what we measure; we usually measure exceptions thrown, not goals achieved.

## Evidence supporting it

- Recurring false-progress failure class (F10). **PATTERN**
- Need for verify_* tools in Playwright MCP that are optional. **FACT**
- Production advice to verify after consequential actions. **EVIDENCE**
- CAPTCHA loops where clicks “succeed” on widgets without clearing challenges. **EVIDENCE**

## Projects demonstrating it

All tool-calling browser agents; computer-use; MCP browser tools.

## Mistakes to avoid

- Binary success metrics on tool JSON
- No idempotency keys on side-effecting tools
- Missing “unknown / blocked / needs-human” outcomes in the tool vocabulary

## Engineering implication

Execution APIs need richer outcome taxonomies than OK/ERR — including blocked, uncertain, and needs-verification states.
