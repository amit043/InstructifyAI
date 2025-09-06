import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str | None) -> None:
    """Set the correlation request id for current context."""
    _request_id.set(request_id)


def get_request_id() -> str | None:
    """Retrieve current correlation request id if set."""
    return _request_id.get()


def new_request_id() -> str:
    return str(uuid.uuid4())
