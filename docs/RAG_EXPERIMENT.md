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
