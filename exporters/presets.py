from __future__ import annotations

"""Built-in export presets."""

RAG_TEMPLATE = (
    '{{ {"context": ((chunk.source.section_path | join(" / ")) ~ ": " ~ '
    'chunk.content.text), "answer": ""} | tojson }}'
)

_PRESETS: dict[str, str] = {"rag": RAG_TEMPLATE}


def get_preset(name: str) -> str:
    """Return the Jinja template string for a preset."""
    try:
        return _PRESETS[name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError("unknown preset") from exc


__all__ = ["get_preset", "RAG_TEMPLATE"]
