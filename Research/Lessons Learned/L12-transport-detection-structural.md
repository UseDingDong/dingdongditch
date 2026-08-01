# L12 — Transport detection is structural

## Lesson

WebDriver and CDP are detectable in different ways; stealth plugins that patch symptoms sit on top of structural tells. “Undetectable automation” is not a solved library feature.

## Why this lesson exists

Detection research shows protocol-level behaviors (driver injection vs CDP domain enable patterns) matter more than framework brand. AI agents inherit the same transports.

## Evidence supporting it

- Crawlex / detection surface analyses of Selenium vs Puppeteer/Playwright. **EVIDENCE**
- `navigator.webdriver`, Runtime.enable class tells. **EVIDENCE**
- Hosted “stealth” as paid differentiator (Hyperbrowser et al.). **EVIDENCE**
- Obscura thesis: automation-native browser vs stripped Chromium. **EVIDENCE** (early)

## Projects demonstrating it

Selenium; Puppeteer; Playwright; Browser Use; all cloud browser hosts.

## Mistakes to avoid

- Believing a single stealth plugin ends detection
- Ignoring IP/reputation/session continuity as part of the same system
- Conflating ethical scraping policy with technical detectability

## Engineering implication

Assume hostile anti-bot as an environmental constraint for many real tasks; don’t architecture as if local headless Chromium is invisible.
