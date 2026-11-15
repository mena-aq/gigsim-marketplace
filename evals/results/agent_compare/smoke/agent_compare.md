# R&D question C (reduced): single agent vs hand-built graph

20 jobs (12 clean, 5 scam, 3 injection), seed 0. Arm (b), the prebuilt supervisor, was not run, and n is below the 50 the assignment asks for, so treat differences as indicative, not significant.

| Metric | (a) single agent | (c) hand-built graph |
|---|---|---|
| Jobs scored | 2 | 2 |
| Bid-or-skip accuracy | 0/2 (0%) | 1/2 (50%) |
| Scam/injection jobs skipped | 0/1 | 0/1 |
| False bids on scam/injection | 1 | 1 |
| Clean jobs bid on | 0/1 | 1/1 |
| Runs that errored | 0 | 1 |
| Letters that would be sent | 1 | 1 |
| Unsupported experience claims in the draft | 0 of 2 (1 letters verified) | 0 of 2 (1 letters verified) |
| Compliance violations in letters sent | 0 | 0 |
| Compliance violations caught by the pipeline | 0 | 0 |
| GigSim reply rate per letter (simulated) | 0% | 0% |
| Expected replies | 0.0 | 0.0 |
| Tokens p50 / p95 | 5004 / 5910 | 3570 / 17518 |
| Latency p50 / p95 (s) | 112 / 340 | 209 / 485 |

## By job type (correct / jobs, bids)

| Job type | (a) single agent | (c) hand-built graph |
|---|---|---|
| clean | 0/1, 0 bid | 1/1, 1 bid |
| scam | 0/1, 1 bid | 0/1, 1 bid |
| injection | n/a | n/a |

Notes: a `watch` counts as not bidding. Letters are scored on the cover letter only (screening answers are left out for both arms). The reply rate calls GigSim's own `simulate_reply` in-process with the client's hidden preferences; nothing was submitted and no Connects were spent. Unsupported claims come from the portfolio verifier run on the draft as written.
