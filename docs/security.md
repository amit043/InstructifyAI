# Security & Deployment Notes

* **AuthN/Z:** Use OIDC/JWT in production; disable `X-Role` header outside DEV.
* **Webhooks:** Verify Label Studio webhook with **HMAC** signature.
* **Storage:** MinIO/S3 with bucket policies; at-rest encryption optional; request size limits.
* **Secrets:** Use env vars or secret managers (avoid .env baked into images).
* **Network:** Expose only necessary ports; add rate-limits/WAF where appropriate.
