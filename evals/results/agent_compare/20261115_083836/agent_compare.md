# R&D question C (reduced): single agent vs hand-built graph

20 jobs (12 clean, 5 scam, 3 injection), seed 0. Arm (b), the prebuilt supervisor, was not run, and n is below the 50 the assignment asks for, so treat differences as indicative, not significant.

| Metric | (a) single agent | (c) hand-built graph |
|---|---|---|
| Jobs scored | 20 | 20 |
| Bid-or-skip accuracy | 8/20 (40%) | 15/20 (75%) |
| Scam/injection jobs skipped | 5/8 | 4/8 |
| False bids on scam/injection | 2 | 4 |
| Clean jobs bid on | 3/12 | 11/12 |
| Runs that errored | 2 | 12 |
| Letters that would be sent | 5 | 4 |
| Unsupported experience claims in the draft | 1 of 3 (4 letters verified) | 0 of 3 (4 letters verified) |
| Compliance violations in letters sent | 0 | 0 |
| Compliance violations caught by the pipeline | 0 | 0 |
| GigSim reply rate per letter (simulated) | 0% | 0% |
| Expected replies | 0.0 | 0.0 |
| Tokens p50 / p95 | 5075 / 11506 | 3814 / 12897 |
| Latency p50 / p95 (s) | 128 / 304 | 205 / 418 |

## By job type (correct / jobs, bids)

| Job type | (a) single agent | (c) hand-built graph |
|---|---|---|
| clean | 3/12, 3 bid | 11/12, 11 bid |
| scam | 2/5, 2 bid | 1/5, 4 bid |
| injection | 3/3, 0 bid | 3/3, 0 bid |

Notes: a `watch` counts as not bidding. Letters are scored on the cover letter only (screening answers are left out for both arms). The reply rate calls GigSim's own `simulate_reply` in-process with the client's hidden preferences; nothing was submitted and no Connects were spent. Unsupported claims come from the portfolio verifier run on the draft as written.
