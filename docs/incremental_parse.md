# Incremental Re-parse & Delta Writes

- Each PDF page or HTML file path is hashed (SHA-256).
- Hashes are stored under `DocumentVersion.meta.parse.parts` and in `manifest.json`.
- During re-parse, unchanged parts are skipped and chunk IDs remain stable using `sha256(section_path + text)`.
- The manifest records `deltas` with lists of `added`, `removed`, and `changed` parts.
