# Architecture & Data Flow

```mermaid
flowchart LR
  A[Ingest Docs] --> B[Chunk & Metadata]
  B --> C[Label Studio (Human-in-loop)]
  C --> D[Audits / Scorecards]
  D --> E[Export JSONL]
  E --> F[Train Adapters (LoRA/QLoRA)]
  F --> G[Registry (project/document bindings)]
  G --> H[/gen/ask Route]
  H --> I{Model Selection\n doc->project or model_refs}
  I --> J[Runner(s): HF/llama.cpp]
  J --> K[Aggregator: first/vote/concat/rerank*]
  K --> L[Answer + (raw votes)]
```

**Deployment Footprint**

* Containers: API, Worker, DB, Redis, MinIO, LS, (optional) Generator
* Feature flag: `FEATURE_DOC_BINDINGS` (default: true)
* Note: `document_id` is the canonical field; `doc_id` alias is accepted at API boundary.
