# RAG comparison protocol

This is an exploratory development comparison, not a preregistered study. Smoke
queries and CPU-budget tuning preceded the final run. The final table references
one run with a fixed configuration/code/index fingerprint; interrupted diagnostic
runs are not pooled into its aggregate.

Working hypotheses: requirement decomposition may help multi-requirement queries;
hybrid retrieval may recover exact tool names; cross-encoder reranking may improve
nDCG; grading/correction may improve no-evidence abstention at a latency cost.
No outcome or winning variant is assumed. The user chooses the shipped variant.

The development set is agent-authored from the current synthetic case studies:
30 queries, ten per persona (four direct, three multi-requirement, two paraphrase,
one no-evidence). Positive labels are intentionally reviewable but not exhaustive;
unjudged historical proposals/CVs/reviews count as nonrelevant. These provisional
labels can understate retrieval quality. No human gold-label or judge-calibration
claim is made. The 12 claim examples are also provisional and not Cohen's kappa
calibration. Synthetic portfolio numbers are evidence within the simulator only.

All variants use the same 200-token chunks with 40-token overlap, user namespaces,
embedding digest and cosine vectors. V0 is whole-query dense; V1 uses at most six
source-quoted requirements; V2 fuses BM25/dense ranks; V3 reranks 20 candidates;
V8 grades the best five unique candidates and can re-query once. V8 may return
fewer than ten results; this is reflected in nDCG@10 rather than padded with
unsupported evidence. Absent/partial support is preserved in diagnostics.

Timing covers retrieval-library calls, not MCP serialization/audit or a full
proposal workflow. Verification examples use supplied gold-source chunks, not
end-to-end generated proposals; their keep/removal rates are sentence-example
metrics, not calibrated atomic-claim accuracy. Supported retention and unsafe
removal must be considered together; dropping everything is not success.

Record Recall@5, MRR, nDCG@10 on positive queries; report correct abstention
separately on empty-label queries. Retrieval failures count as zero quality and
never count as successful abstention. Timing includes model loading when incurred;
there is no explicit warmup. Runs are sequential on a shared development CPU,
not dedicated benchmarking hardware. Token totals use Ollama-reported values;
failed requests without usage reports cannot be assigned invented token counts.
Local hardware cost is unknown, paid API cost is zero. No proposal reply/hire rate
is measured in this milestone.

Claim verification extracts source-quoted claims, validates supplied evidence IDs,
and excludes sentences with anything less than fully supported experience. A
conservative literal-number guard also rejects numerical details absent from cited
text; equivalent formats (for example 1.2M versus 1,200,000) require review rather
than guessed conversion. Invalid/unavailable judgments mark affected text
unverified and excluded. This is not a guarantee that a small model never makes
semantic grading mistakes. The retained-claim unsupported rate is null if no
sentences survive, never a fabricated perfect score.

## Quick R&D question B: a fixed hypothesis

Hypothesis: **Adding cross-encoder reranking to hybrid retrieval improves mean
nDCG@10.** V3 is the candidate for this experiment; this does not select the
production retriever. This is exploratory analysis of existing development data,
not a preregistered or held-out confirmation.

Run the offline paired analysis yourself:

```bash
uv run python -m evals.runners.rag_rd_b \
  --run evals/results/rag_20261113_155449.jsonl
```

Use the exact JSONL file you want to analyze. Every dataset query must have exactly
one V2 and one V3 observation, with one shared retrieval fingerprint and matching
persona/type metadata. Duplicate/missing observations and mismatched environment
sidecars are rejected. The script re-scores rankings against the supplied labels,
rather than trusting previously saved metric values. It requires no live services,
models, or database connection.

Primary endpoint: mean paired nDCG@10 difference, V3 minus V2, on positive-label
queries. Empty-label queries are excluded from ranking metrics and have a separate
abstention metric. Failures count as zero quality and never successful abstention.
The percentile bootstrap uses 10,000 samples, seed 42, resampling paired differences
within persona. An interval above zero is an observed improvement; below zero is
an observed decrease; overlapping zero is inconclusive. Equal scores are reported
as no observed difference. These development-data intervals do not establish
population-wide significance or higher reply rate. Secondary endpoints are
Recall@5, MRR, failures, and recorded latency; do not pick a different primary
endpoint after seeing the result.

Historical observations store query IDs, not query text. Preserve the original
query text for those IDs. Labels can be reviewed and re-scored; changed query text
requires a fresh run/new IDs. The analysis saves the actual scoring dataset and
its hash, the source run/hash/fingerprint, and per-query pairs. Per-persona/type
deltas and full summaries are in rag_rd_b.json; the Markdown file gives a short
finding and comparison table. No model inference is needed for this script.

## Quick one-component-at-a-time ablation

```bash
uv run python -m evals.runners.rag_ablation
```

This measures three configurations fresh on the same development queries:

| Configuration | Dense | BM25 | Cross-encoder |
| --- | --- | --- | --- |
| full_v3 | yes | yes | yes |
| without_reranker | yes | yes | no |
| without_bm25 | yes | no | yes |

These are experiment wrappers, not new registered RAG variants. The dense
backbone remains in place. All arms use the same candidate limit (20 chunks by
default) and return at most ten unique items after final ranking. Removing BM25
uses the raw dense chunk pool before reranking, not already-deduplicated V0 output.
Removing the reranker calls the existing V2 implementation unchanged.

The dataset is evaluated sequentially, rotating configuration order per query to
reduce fixed order/cache bias. Each arm has a fresh pipeline context; there is no
explicit warmup and model loading is included. Qwen/decomposition/grading/claim
verification is never invoked: an explicit no-generation guard rejects such calls.
Ollama embeddings, Chroma, the existing indexes, and provisioned user mappings
must be available. No models are downloaded and the active variant is unchanged.

Queries/configurations are flushed to a timestamped JSONL as they complete. A
changed/stale index or missing model stops the run; transient retrieval failures
are recorded as zero quality. Completed reports contain per-query evidence,
per-persona/type summaries, and paired full-minus-ablated effects. Positive effects
mean that the removed component helped on this dataset. Latency comes from this
fresh run; do not pool it with cached timings from the hypothesis analysis.

The default output directory is evals/results. Both scripts accept --dataset and
--output-dir for separate review/experiments. Completed outputs are:

- rag_rd_b.json / .csv / .md, plus rag_rd_b_queries.jsonl and rag_rd_b_dataset.json.
- rag_ablation.json / .csv / .md, plus a timestamped raw run, consolidated query
  evidence, and the exact scoring-dataset snapshot.

A new execution overwrites the corresponding derived summaries; use a separate
--output-dir if you want to retain several analysis reports. Source run files are
not changed. Partial ablation runs are not treated as completed summaries.
