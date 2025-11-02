## Gen/Ask Response Quality Plan

### Goals
- Warm the gen service so first-call latency stays under 15s by prefetching base models and adapters.
- Improve grounded answer quality by tightening retrieval context and response validation.
- Ensure responses are consistent and aligned with source documents while maintaining sub-minute P95 latency.

### Problems Observed
- First /gen/ask call downloads base model weights on-demand, adding >60s cold start latency.
- Prefetched adapter cache still reloads base model per worker restart; no background warm-up.
- Retrieved evidence may be sparse or irrelevant, leading to generic or incomplete answers even with citations.
- Lack of post-generation checks to enforce factuality or fallback messaging.

### Proposed Enhancements

#### 1. Aggressive Preload & Warm-up
- Extend startup hook (scripts/serve_local.py:_warm_active_adapters) to download base models via model_svc.ensure_loaded() before accepting traffic.
- Add scripts/warm_gen.py CLI to prefetch base model + active adapters; expose make warm-gen target.
- Update Docker build/compose to set HF_PREFETCH=1 and optionally prefetch models into the image when BASE_MODEL is set.
- Monitor warm-up timing with metrics (GEN_WARM_DURATION histogram) to catch regressions.

#### 2. Retrieval Quality & Prompting
- Increase chunk candidate pool and filter by metadata (matching document_id, section relevance, confidence) before embedding.
- Introduce reranking using cosine similarity + heuristic scoring (section match, recent edits) to pick top-k evidence.
- Expand prompt template with structured context (bullet list with section titles, doc IDs) and instructions for concise answers.
- Allow project-level prompt overrides (project_settings.generative_prompt) for domain-specific guidance.

#### 3. Post-generation Validation
- Parse model output for citation markers and unknown claims; if missing, re-run with lower temperature or fallback answer "No grounded answer available."
- Add optional deterministic check (e.g., regex for key phrases) to ensure answer references required metadata fields.
- Log validation failures and include 
eeds_grounding=true with explanation to help curators diagnose issues.

#### 4. Metrics & Observability
- Emit Prometheus counters for warm-up success/failure, evidence hit rates, and validation outcomes.
- Capture response length and latency per outcome to correlate quality with performance.
- Extend /metrics docs to cover new series.

### Implementation Steps
1. **Warm-up tooling**: implement warm_gen.py, extend startup hook, add Make target.
2. **Model prefetch build path**: set HF_PREFETCH=1 during compose build and document env knobs.
3. **Retrieval tuning**: adjust etrieval/service.py to score/filter evidence; update prompt construction in serve_local.py.
4. **Validation layer**: add post-response validator ensuring citations present; re-run or produce fallback message.
5. **Metrics**: instrument new counters/histograms and update docs.
6. **Testing**: create integration tests verifying warm start time <15s (mocking downloads), retrieval selection accuracy, and validator behavior.
7. **Docs**: update README and STATUS with warm-up command, quality guarantees, and configuration.

### Risks & Mitigations
- **Longer startup time**: mitigate with async warm-up, progress logs, and optional skipping via env flag.
- **GPU memory pressure**: limit concurrent warm adapters, use eviction LRU when exceeding MAX_ACTIVE_ADAPTERS.
- **Prompt overfitting**: keep default prompt balanced; allow project overrides for custom tone.

### Next Steps
- Review and approve plan.
- Implement in phases (warm-up -> retrieval -> validation) with test coverage after each stage.
