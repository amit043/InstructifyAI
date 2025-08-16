from __future__ import annotations

from fastapi import HTTPException
from jinja2.sandbox import SandboxedEnvironment  # type: ignore[import-not-found]

from .helpers import iso8601, join_section_path

env = SandboxedEnvironment(autoescape=False)
env.policies["json.dumps_kwargs"] = {"sort_keys": False}
env.globals.update(
    join_section_path=join_section_path,
    iso8601=iso8601,
)


def compile_template(template: str):
    """Compile a Jinja2 template in a sandbox.

    Raises:
        HTTPException: if the template cannot be parsed.
    """
    try:
        return env.from_string(template)
    except Exception as exc:  # pragma: no cover - jinja2 error messages vary
        raise HTTPException(status_code=400, detail=f"invalid template: {exc}") from exc


__all__ = ["env", "compile_template"]
