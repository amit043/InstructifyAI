import logging
from dataclasses import dataclass


@dataclass
class GuidelineUsage:
    """Record a guideline assistant usage event."""

    user: str
    action: str
    field: str | None = None


def log_guideline_usage(event: GuidelineUsage) -> None:
    """Log a guideline assistant usage event.

    The log is structured so that analytics systems can parse it later.
    """
    logger = logging.getLogger("guidelines")
    logger.info(
        "guideline_usage",
        extra={"user": event.user, "action": event.action, "field": event.field},
    )
