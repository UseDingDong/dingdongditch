# L10 — Benchmarks will lie to you on purpose

## Lesson

Saturated, vendor-tuned, read-oriented benchmarks systematically overstate browser-agent capability relative to live authenticated write tasks.

## Why this lesson exists

Incentive structures reward leaderboard numbers. Independent harder evals collapse scores. Engineering roadmaps that chase WebVoyager-class metrics inherit false confidence.

## Evidence supporting it

- WebVoyager top systems clustered >87–98% with commentary on saturation/benchmaxxing. **EVIDENCE**
- “Illusion of Progress” (COLM 2025) cited: frontier agents ~30% on more realistic prior evals. **EVIDENCE** (secondary citation — read paper when designing evals)
- ClawBench ~33% best frontier on live write tasks (survey citation). **EVIDENCE**
- Skyvern WebBench 64.4% as “harder number.” **EVIDENCE**
- State of Browser Use: treat scores as relative ordering, not absolute capability. **EVIDENCE**

## Projects demonstrating it

Nearly all agent vendors citing WebVoyager; Browser Use Online-Mind2Web claims; ABP Mind2Web claims.

## Mistakes to avoid

- Picking architecture because of a leaderboard
- Using only synthetic sites without auth/CAPTCHA/writes
- Ignoring eval contamination / overfitting

## Engineering implication

Build institutional distrust of single-number capability claims; track eval methodology as carefully as model choice.
