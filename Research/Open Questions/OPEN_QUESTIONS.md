# Open Questions

Track explicitly. Do not silently convert into assumptions.

## Protocol & runtime

| ID | Question | Why it matters | How to resolve |
|----|----------|----------------|----------------|
| Q1 | What is Stagehand v3’s exact relationship to Playwright today (complete CDP rewrite vs hybrid)? | Competitor architecture accuracy | Read current Stagehand source + changelog |
| Q2 | What is Browser Use’s current default driver (Playwright vs CDP) and watchdog design? | Same | Read upstream repo + recent releases |
| Q3 | How complete is WebDriver BiDi as an AI substrate vs CDP in 2026? | Future-proofing | Spec + Selenium/Playwright BiDi support matrix |
| Q4 | Is Obscura’s CDP compatibility and stealth claim durable on real sites? | Runtime economics | Independent harness tests |
| Q5 | Do page-freeze protocols (ABP) break sites that require continuous timers/WebSockets? | Sync strategy viability | Controlled experiments |

## Product surfaces

| ID | Question | Why it matters | How to resolve |
|----|----------|----------------|----------------|
| Q6 | What is OpenAI’s current public developer API for browser/computer use post-Operator merge? | Competitive boundaries | Official OpenAI docs snapshot |
| Q7 | How stable are Playwright MCP tool schemas month-to-month? | Adapter churn | Track releases |
| Q8 | Exact GitHub stars/forks/download metrics as of design kickoff | Adoption claims | `gh api` when available |

## Reliability science

| ID | Question | Why it matters | How to resolve |
|----|----------|----------------|----------------|
| Q9 | What fraction of agent failures are stale-state vs grounding vs planning vs auth? | Prioritize gaps | Labeled failure taxonomy study |
| Q10 | Independent replication of ABP Mind2Web / Browser Use Online-Mind2Web numbers? | Avoid vendor theater | Third-party eval |
| Q11 | How often do a11y snapshots miss the actionable control on top N enterprise SaaS apps? | Observation channel limits | Corpus study |
| Q12 | Cache invalidation false-positive/negative rates for Stagehand-like action caches? | Determinism spectrum | Measure drift |

## Security & policy

| ID | Question | Why it matters | How to resolve |
|----|----------|----------------|----------------|
| Q13 | Which programmatic isolation patterns actually reduce IDPI success rates? | L11 | Security lit + red teams |
| Q14 | Legal/ToS landscape for CAPTCHA solving in automation products? | L05 constraints | Counsel + policy research |
| Q15 | User-local browser with agent control vs remote browser: threat model differences? | L14 | Threat model workshop |

## Mission alignment

| ID | Question | Why it matters | How to resolve |
|----|----------|----------------|----------------|
| Q16 | Which execution semantics must be stable across AI hosts to qualify as a “universal execution layer”? | Core mission | Phase 2A proposed a **candidate**: attestation verdict/expectation/epoch/evidence semantics — see `Engineering/Phase 2/PHASE_2A_RECOMMENDATION.md` and `SUCCESS_SEMANTICS.md`. Not validated; not an architecture. |
| Q17 | Is the underserved layer verification/recovery/sync rather than another grounding method? | Gap focus | Phase 2A **INTERPRETATION**: verification/attestation primary; sync as freshness constraint; recovery statuses not loop ownership; grounding left to automation libs. Invalidate via experiments in the recommendation doc. |

## Research process debts from this pass

- No direct `gh` star fetch
- Did not clone/read Stagehand or Browser Use source trees
- Did not exhaustively mine GitHub issue trackers (sampled)
- Reddit evidence mostly via secondary surveys — primary Reddit scrape not performed
- Academic papers cited via secondary mention — need primary reads for L10 public claims
