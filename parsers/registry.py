from __future__ import annotations

from typing import Callable, Dict, Iterable

from chunking.chunker import Block


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: Dict[str, Callable[[bytes], Iterable[Block]]] = {}

    def register(
        self, source_type: str
    ) -> Callable[
        [Callable[[bytes], Iterable[Block]]], Callable[[bytes], Iterable[Block]]
    ]:
        def decorator(
            func: Callable[[bytes], Iterable[Block]],
        ) -> Callable[[bytes], Iterable[Block]]:
            self._parsers[source_type] = func
            return func

        return decorator

    def get(self, source_type: str) -> Callable[[bytes], Iterable[Block]]:
        if source_type not in self._parsers:
            raise ValueError(f"No parser registered for {source_type}")
        return self._parsers[source_type]


registry = ParserRegistry()

__all__ = ["registry", "ParserRegistry"]
