# Architecture & Data Flow

Offline pipeline (prepare)
```mermaid
graph LR
  subgraph Ingestion
    A[Ingest docs] --> B[Chunk and metadata]
  end

  subgraph Labeling
    B --> C[Label Studio human in the loop]
    C --> D[Audits and scorecards]
    D --> E[Export JSONL]
  end

  subgraph Training
    E --> F[Train adapters LoRA or QLoRA]
    F --> G[Publish to registry]
  end

  R[Registry]
  G --> R

```
Online Path Serve
```mermaid
graph LR
  H[gen ask route] --> I{Model selection}
  I --> J1[Runner HF]
  I --> J2[Runner llama cpp]
  J1 --> K[Aggregator first vote concat rerank]
  J2 --> K
  K --> L[Answer and raw votes]

  R[Registry]
  I --> R

```
Minimal sequence for the request flow
```mermaid
sequenceDiagram
  actor U as User
  participant API as gen ask
  participant REG as Registry
  participant RUN as Runners
  participant AGG as Aggregator

  U->>API: ask(question, doc ref)
  API->>REG: resolve model refs
  REG-->>API: model refs
  API->>RUN: run(question, refs)
  RUN-->>AGG: candidates
  AGG-->>API: answer and votes
  API-->>U: response

```
**Deployment Footprint**

* Containers: API, Worker, DB, Redis, MinIO, LS, (optional) Generator
* Feature flag: `FEATURE_DOC_BINDINGS` (default: true)
* Note: `document_id` is the canonical field; `doc_id` alias is accepted at API boundary.
