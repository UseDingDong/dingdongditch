# Second Fresh Monkeytype Production Benchmark

Date: 2026-07-29  
Result: **PASS**

## Run03 result

| Metric | Result |
|---|---:|
| WPM | 93 |
| Accuracy | 100% |
| Correct / incorrect / extra / missed | 463 / 0 / 0 / 0 |
| Verified DingDongDitch key operations | 465 |
| Backspaces dispatched | 0 |
| Corrections/backspaces reported by Monkeytype | not reported |
| Words typed | 89 |
| Measured typing interval | 61,077.78 ms |
| End-to-end duration | 72,139.63 ms |
| Sequential key-execution time | 46,486.41 ms |
| Active-word/completion inspection time | 10,984.13 ms |
| Browser launch | 1,793.74 ms |
| Browser cleanup | 757.96 ms |
| Plan receipt files | 99 |
| Verified operation receipts contained in plans | 475 |
| Screenshots | 10 |
| Inspections | 185 |
| Atomic snapshot fallbacks | 0 |
| Remaining owned processes | 0 |

The final Monkeytype screen independently shows time 60, English, 93 WPM,
100% accuracy, and `463/0/0/0` characters.

## Verified key-operation latency

Receipt timestamps for all 465 typed key operations:

| Metric | Latency |
|---|---:|
| Average | 100.02 ms |
| Median | 94 ms |
| P95 | 141 ms |
| P99 | 157 ms |
| Maximum | 188 ms |
| Average backend action portion | 51.78 ms |

## Three-run comparison

| Metric | Historical | Atomic run02 | Atomic run03 |
|---|---:|---:|---:|
| WPM | 104 | 93 | 93 |
| Accuracy | 100% | 100% | 100% |
| Correct characters | not separately supplied | 465 | 463 |
| Verified key operations | 521 | 468 | 465 |
| Incorrect / extra / missed | 0 / — / — | 0 / 0 / 0 | 0 / 0 / 0 |
| Typing interval | not supplied | 61.29 s | 61.08 s |
| Sequential key execution | not supplied | 47.52 s | 46.49 s |
| Active-word/completion inspections | not supplied | 10.34 s | 10.98 s |
| Per-key average | not supplied | 101.56 ms | 100.02 ms |
| Per-key median | not supplied | 94 ms | 94 ms |
| Per-key P95 | not supplied | 141 ms | 141 ms |
| Per-key P99 | not supplied | 172 ms | 157 ms |
| Per-key maximum | not supplied | 516 ms | 188 ms |
| Atomic snapshot fallbacks | not supplied | 0 | 0 |

## Interpretation

### 1. Material difference from run02

There is no material score difference. Both atomic-snapshot runs produced
exactly 93 WPM and 100% accuracy. Run03 produced two fewer correct characters,
three fewer verified key operations, and one fewer word. Those differences are
too small to change Monkeytype's rounded WPM score.

### 2. Per-key runtime latency

Per-key runtime did not regress:

- average improved from 101.56 to 100.02 ms (-1.51%);
- median was unchanged at 94 ms;
- P95 was unchanged at 141 ms;
- P99 improved from 172 to 157 ms;
- maximum improved from 516 to 188 ms.

Run03 spent 1.037 seconds less in sequential key execution. Three fewer key
operations explain only about 0.3 seconds at the measured average; the rest is
consistent with the modestly better average and absence of run02's 516 ms tail
outlier.

### 3. Cause of score variation

The measured run02-to-run03 variation is explained by a combination of:

- **word sequence and character count:** run03 completed 89 words and 465 key
  operations versus 90 and 468 in run02. Average keys per word were nearly
  identical: 5.225 versus 5.200.
- **inspection scheduling:** run03 made two fewer typing inspections but spent
  0.646 seconds more in them because average inspection latency rose from
  57.12 to 61.36 ms.
- **browser/runtime scheduling:** per-key tails were better in run03, while
  inspection calls were slightly slower. These opposing measured changes left
  the typing interval only 0.215 seconds shorter.

Per-key operation latency is not a cause of a lower run03 score: it improved.
Inspection frequency was methodologically identical—one active-word read and
one completion probe per word—with the count changing only because run03 typed
one fewer word.

### 4. Atomic snapshot regression assessment

There is no evidence that the atomic snapshot optimization caused a regression.
Both current runs used zero fallbacks, both achieved 93 WPM with perfect
accuracy, and run03's per-key average and tail latency were equal or better
than run02. Atomic snapshots apply primarily to inspections; their observed
57–61 ms average remains far below the pre-optimization audit's approximately
259 ms inspection average.

### 5. Repeatability of the historical 104 WPM result

The 104 WPM historical result has not been repeatable under the current
evidence policy: two fresh, independent, methodologically identical runs both
produced 93 WPM and perfect accuracy. This does not prove that 104 WPM is
impossible, because the historical run's per-key latency distribution and
inspection timing are unavailable. It does show that 104 WPM is not the
current repeatable central result from the two available atomic-policy runs.

## Remaining bottleneck

Sequential verified key execution remains dominant:

- 46.49 of the 61.08 measured seconds were spent in 465 ordered, receipted key
  operations;
- 10.98 seconds were spent in active-word and completion inspections;
- each key averaged 100.02 ms end to end, of which 51.78 ms was backend action
  time and the remainder covered deterministic pre/post observation,
  verification, receipt, and plan-boundary work.

No batching, speed adjustment, evidence-policy change, JavaScript injection, or
direct Playwright keyboard/mouse call was used.

## Configuration and methodology integrity

- The run03 script is byte-identical to the successful run02 script.
- A new evidence directory and fresh headed bundled Chromium were used.
- Codex submitted typed DingDongDitch ExecutionPlans.
- DingDongDitch performed every browser mutation and key operation.
- Standard 60-second English mode was selected and verified.
- The run succeeded on its first and only attempt; no retry occurred.

## Cleanup

- Backend lifecycle state: `stopped`
- Cleanup errors: none
- Remaining DingDongDitch/Playwright-owned processes: 0

## Evidence locations

- `benchmark_results.json`
- `latency_analysis.json`
- `receipts/`
- `screenshots/`
- `inspections/`
- `logs/run_history.json`
- `terminal_browser.json`
- `run_benchmark.py`

Final result screenshot:

`screenshots/wait_final_results__step-0__wait_final_results__after_success__959c13c6-96ce-443c-b8e9-14ce3f60de98.png`
