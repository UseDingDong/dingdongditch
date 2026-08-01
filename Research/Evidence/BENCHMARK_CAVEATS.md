# Benchmark Caveats

## Established facts

- Multiple public leaderboards exist for web agents (WebVoyager and others).
- Vendor blogs publish high success percentages.

## Evidence

- May 2026 field survey reports WebVoyager top-10 all above ~87%, top systems ~98%.
- Same survey reports much lower numbers on harder live-write suites (ClawBench ~33%, WebBench mid-60s for leader cited).
- Academic work (“Illusion of Progress”) is cited as showing prior benchmarks overstated capability.

## Observed patterns

- Easier benchmarks → more impressive marketing numbers.
- Authenticated, write-oriented, multi-tab, CAPTCHA-bearing tasks collapse performance across vendors.
- Once a benchmark saturates, incentives shift toward overfitting.

## Speculation

- Some claimed “97%” results may reflect heavy prompt/search optimization against the eval harness rather than general competence.

## Unknowns

- Exact reproducibility of each cited number without running the harness.
- Whether any current open framework dominates on a fixed, adversarial, write-oriented private suite.

**Rule for this archive:** Never use a single benchmark number as architectural justification.
