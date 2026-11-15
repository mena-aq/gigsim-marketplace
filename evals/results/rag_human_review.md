# Human review

Give ONE integer score (1–5), considering relevance, specificity, grounding and clarity together. 1: irrelevant/fabricated; 2: weak/vague/unsupported; 3: adequate; 4: clear, relevant and grounded; 5: excellent fit with compelling evidence and approach.

Fill only human_score in rag_human_review.csv. Do not inspect rag_calibration_key.json before scoring. No comments or sub-scores required.

Sampling: six scored proposals per variant, aiming for two per persona. Sparse cells are filled from other personas within the same variant. This pack represents judge-scored outputs; failed and empty outputs are excluded.
