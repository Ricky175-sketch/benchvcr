"""The minimal synchronous transport contract used by BenchVCR."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class TextTransport(Protocol):
    """One synchronous text connection with at most one outstanding operation."""

    def write(self, command: str) -> None:
        """Send a command that has no response."""
        ...

    def query(self, command: str) -> str:
        """Send a command and return its complete text response."""
        ...

    def close(self) -> None:
        """Close resources owned by this transport."""
        ...
