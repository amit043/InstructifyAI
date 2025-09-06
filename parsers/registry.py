from __future__ import annotations

from typing import Callable, Dict, Iterable, Protocol, Type

from chunking.chunker import Block


class Parser(Protocol):
    @staticmethod
    def parse(data: bytes) -> Iterable[Block]: ...


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: Dict[str, Type[Parser]] = {}

    def register(self, mime: str) -> Callable[[Type[Parser]], Type[Parser]]:
        def decorator(cls: Type[Parser]) -> Type[Parser]:
            self._parsers[mime] = cls
            return cls

        return decorator

    def get(self, mime: str) -> Type[Parser]:
        if mime not in self._parsers:
            raise ValueError(f"No parser registered for {mime}")
        return self._parsers[mime]


registry = ParserRegistry()

__all__ = ["registry", "ParserRegistry", "Parser"]
