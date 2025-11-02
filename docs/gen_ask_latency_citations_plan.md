## Gen/Ask Latency & Citation Roadmap

### Objectives
- Cut steady-state `/gen/ask` latency to sub-minute P95 without adding new deployments.
- Serve grounded answers that include explicit citations back to chunk metadata.
- Keep the plan within Phase‑1 scope locks (no new UI; reuse existing ingestion + chunk schemas).

### Current Pain Points
- **Adapter reload thrash**: every request re-downloads and unzips adapter artifacts (`scripts/serve_local.py`, `registry/storage.py`), forcing `PeftModel.from_pretrained` even when bindings are unchanged.
- **No evidence surface**: responses return free-form text with no linkage to stored chunks; verifying provenance requires manual log spelunking.

### Proposed Changes

#### 1. Adapter Artifact Caching & Warm Paths
1. Persist adapters under a deterministic on-disk cache (e.g. `.cache/adapters/{adapter_id}`) instead of transient temp dirs. Extend `registry/storage.get_artifact` to first check the cache and return a stable path.
2. Track a per-adapter fingerprint (artifact URI + updated_at) in a small manifest (`json` alongside cached files) so revisions invalidate correctly.
3. Update `ModelService.ensure_loaded` (`scripts/serve_local.py:358-420`) to maintain an in-memory map `{adapter_cache_path: loaded}`. Only call `load_adapter` when the cached path changes.
4. Add a background warm-up hook:
   - Expose `worker/main.py` (or a new `scripts/warm_adapters.py`) task that runs on boot, querying active bindings (`registry.bindings.get_bindings`) and calling `ModelService.ensure_loaded` for each.
   - Register the task to run after migrations in `docker-compose` via `command: bash -lc "python scripts/warm_adapters.py && python scripts/serve_local.py"` (or similar) so the gen service starts hot.

#### 2. Request Pipeline Improvements
1. Avoid serial adapter loads when multiple bindings participate: collect all `BindingPlan` instances, group by cached adapter path, ensure each unique adapter is warmed once, then run generation synchronously.
2. Introduce a simple in-process queue/batcher (e.g. `asyncio.Semaphore`) so back-to-back requests reuse the loaded backend without cross-talk.
3. Emit structured latency metrics (`observability.metrics`) capturing cache hits vs misses to validate improvements.

#### 3. Grounded Answer + Citations
1. Add a retrieval helper (`retrieval/service.py`) that:
   - Looks up parsed chunks for the requested `document_id` (or project scope fallback) from the DB.
   - Uses existing `retrieval.index.VectorIndex` + `retrieval.embeddings.EmbeddingModel` to pull top-k snippets matching the prompt.
   - Returns `[(chunk_id, text, metadata)]` with the normalized text hash to support de-dup.
2. Extend `ModelService.generate` to accept an optional `evidence` list; build a prompt template that enumerates the evidence and instructs the model to cite `chunk_id`s in the answer.
3. Update `/gen/ask` response schema (`scripts/serve_local.py:292-344`) to include:
   ```json
   {
     "answer": "...",
     "citations": [
       {"chunk_id": "UUID", "doc_id": "UUID", "section_path": ["..."], "score": 0.87}
     ]
   }
   ```
   Preserve existing fields (`raw`, `used`, `strategy`) for backward compatibility.
4. Add guardrails: if the answer contains no citation markers, return a `"needs_grounding": true` flag or replace the answer with `"No grounded answer available."` based on configuration.

### Implementation Steps
1. **Caching layer**
   - Modify `registry/storage.py` to introduce adapter cache helpers (`ensure_cached_artifact`, `artifact_cache_path`).
   - Update `scripts/serve_local.py` to call the cache-aware helper and store adapter load state in `ModelService`.
2. **Warm-up hook**
   - Create `scripts/warm_adapters.py` that enumerates active bindings and preloads them via the `ModelService` singleton.
   - Wire the warm-up into the gen service command (`docker-compose.yml`) and add a Make target (`make warm-gen`).
3. **Citations**
   - Add `retrieval/service.py` implementing chunk lookup + vector search.
   - Adjust `/gen/ask` flow to fetch evidence before generation and to build the augmented prompt.
   - Extend response schema + FastAPI Pydantic models (if any) to include `citations` and optional `needs_grounding`.
   - Update tests (`tests/test_gen_routing.py`) to cover citation presence, cache hit behaviour, and backwards compatibility.
4. **Observability**
   - Instrument cache hit/miss counters and generation latency histograms via `observability.metrics`.
   - Document the new metrics in `docs/architecture.md` or `README.md` and update `STATUS.md` after implementation.

### Testing & Validation
- Unit tests mocking the cache to assert that repeated calls avoid reloading adapters and return `citations`.
- Integration test or smoke script that runs `/gen/ask` twice, measuring wall-clock time improvement.
- Regression check ensuring legacy clients (without expecting `citations`) continue to parse the response.

### Risks & Mitigations
- **Cache invalidation**: Mitigate by storing adapter revision metadata in the cache manifest and clearing on mismatch.
- **Citation hallucination**: Enforce prompt instructions + post-validate responses for cited chunk IDs; expose config to fail closed.
- **Memory pressure**: Limit the number of hot adapters using LRU eviction and optional `MAX_ACTIVE_ADAPTERS` setting.

### Next Steps
Once the plan is approved, implement in the order above (cache → warm-up → citations → metrics) and update `STATUS.md` with the execution status per backlog task.
