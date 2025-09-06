# Next Parser Optimizations Guide

## Overview
This sprint focuses on throughput, parser quality, governance, and observability improvements in preparation for the next release.

## Scope locks
- Celery-only orchestration
- OCR = text only
- no deep table reconstruction (placeholders/texty OK)
- Local/MinIO only via presigned URLs
- keep RBAC
- idempotent derived writes
- minimal schema churn (prefer meta/manifest)

## Recommended order
- A: N30-01/02/08/13
- B: N30-03/11/09/10
- stretch: N30-04/05/12

## Runbook
- design → code → tests → `make lint test` → `STATUS.md` → PR

## Per-task prompt template
```
Read /docs/sprint_next_parser_optimizations_v1.csv and open the row {TASK_ID}.
Restate AcceptanceCriteria and DoD, propose a brief design, then implement: code, tests, minimal docs.
Keep diffs minimal; follow existing project patterns.
Run `make lint test`; update STATUS.md.
Open PR titled as in the CSV “PR” column, branch feature/{TASK_ID}-short-name.
Start with {TASK_ID} now.
```
