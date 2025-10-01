# Change Log

## 2025-09-20
- Auto-materialize dataset snapshots when training runs are requested so the training runs endpoint no longer fails (commit "feat(training): auto-materialize dataset snapshots") if a curator skips the manual materialize step.
- Training runs now execute via the Celery-backed trainer service (commit pending) so PyTorch stays outside the API container and background jobs run with ML deps. Trainer worker now performs dependency/object-store preflight (API no longer blocks on peft check) and run failure bubbles through Celery.
