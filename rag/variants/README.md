# Retrieval variants

Exactly five variants are implemented:

| ID | Behavior |
| --- | --- |
| V0 | Fixed-size chunks, whole-query dense cosine retrieval |
| V1 | Qwen extracts up to six source-quoted requirements; dense searches merged by reciprocal rank fusion |
| V2 | BM25 + dense candidates merged by reciprocal rank fusion |
| V3 | CPU ONNX cross-encoder reranks V2's top 20 candidates |
| V8 | LangGraph grades the best five unique V3 candidates; at most one grounded corrective re-query and final grade |

`rag.retriever.get_retriever()` accepts only v0/v1/v2/v3/v8. Portfolio MCP uses
`rag.active_variant` in `agent/config.yaml`. V0 remains the development baseline;
the user will choose the final variant after reviewing measured comparisons.
No V4/V5/V6/V7/V9 implementation or automatic winner selection is included.

Rank chunks first, then retain the strongest chunk per unique source item. Item
IDs stay compatible with Portfolio resources; chunk IDs bind exact source content,
user namespace, and offsets. V0 has no relevance refusal threshold: an unrelated
query can still return nearest neighbours. Retrieval `complete` means the search
completed; it is not proof of claim support. V8 additionally reports adequate,
weak, or none; partial support is never silently converted into complete support.

The CPU budget grades five candidates, so V8 can return fewer than ten results.
This deliberate constraint is recorded in config and reflected in nDCG@10.
Evidence aliases in model input are resolved only to the supplied chunk IDs.
Invented references fail; unanchored suggested query terms are discarded and
never searched. Correction is bounded by graph structure and recursion limit.
