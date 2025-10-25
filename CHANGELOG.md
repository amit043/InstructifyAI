# Changelog

> Historical entries remain in `docs/CHANGELOG.md`. New repo-facing updates land here.

## [Unreleased]

### Added

* Product-first README landing (ICPs, value, demo).
* **Investor/Customer demo**: `make demo-investor` runs doc-scoped, multi-teacher `/gen/ask`.
* API surfacing: OpenAPI export path docs + updated Postman collection.
* Buyer docs: datasheet, security notes, ROI worksheet, competitive comparison, roadmap, case study template.
* Architecture diagram (Mermaid) & deployment footprint.
* `.env.example` updated with `FEATURE_DOC_BINDINGS`.

### Behavior

* Canonical request field **`document_id`**; `doc_id` accepted as **deprecated alias** at the API boundary.

### Compatibility

* Legacy response shape for `/gen/ask` unchanged unless `include_raw=true`.
* All new behavior is additive and flag-controlled.
