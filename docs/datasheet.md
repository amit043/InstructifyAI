# InstructifyAI — Product Datasheet (1-pager)

**What:** Private curation + mini-LLM adapters for your documents.
**Why:** Faster/better answers on domain policy, with auditability and on-prem control.

**Key Capabilities**

* Human-in-the-loop curation (Label Studio) with audits & scorecards
* Document-scoped adapters; multi-teacher aggregation (`first|vote|concat|rerank*`)
* Local serving (CPU/GPU), resource-aware backend (HF + optional llama.cpp)

**Security**

* On-premise or VPC deployment
* OIDC/JWT in production; disable DEV headers
* HMAC verification for Label Studio webhooks
* S3/MinIO policies; optional at-rest encryption

**Deployment Footprint**

* Docker/Podman compose for local eval
* Optional GPU node for training/serve
* Prometheus metrics; Grafana dashboards (latency, queue depth, webhook errors)

**Outcomes**

* Time-to-first-answer in hours, not weeks
* Higher accuracy on your internal policy docs
* Transparent model votes & audit trails
