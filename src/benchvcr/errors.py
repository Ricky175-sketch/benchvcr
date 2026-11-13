"""Public exception hierarchy and stable communication error representation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar


class BenchVCRError(Exception):
    """Base class for expected BenchVCR failures."""


class ConfigurationError(BenchVCRError):
    """A public API argument or fault plan is invalid."""


class SessionStateError(BenchVCRError):
    """A session is used outside its active context."""


class CassetteError(BenchVCRError):
    """Base class for cassette failures."""


class CassetteValidationError(CassetteError):
    """A cassette violates the JSONL schema."""

    def __init__(self, path: str | Path, line: int | None, reason: str) -> None:
        self.path = Path(path)
        self.line = line
        self.reason = reason
        location = str(self.path) if line is None else f"{self.path}:{line}"
        super().__init__(f"{location}: {reason}")


class CassetteMismatchError(CassetteError):
    """A replay call does not match the next recorded exchange."""

    def __init__(
        self,
        seq: int,
        expected_kind: str | None,
        expected_command: str | None,
        actual_kind: str,
        actual_command: str,
    ) -> None:
        self.seq = seq
        self.expected_kind = expected_kind
        self.expected_command = expected_command
        self.actual_kind = actual_kind
        self.actual_command = actual_command
        expected = (
            "end of cassette"
            if expected_kind is None
            else f"{expected_kind} {expected_command!r}"
        )
        super().__init__(
            f"cassette exchange {seq}: expected {expected}, "
            f"got {actual_kind} {actual_command!r}"
        )


class UnplayedInteractionsError(CassetteError):
    """A replay context exited normally before consuming every exchange."""

    def __init__(self, remaining: int, next_seq: int) -> None:
        self.remaining = remaining
        self.next_seq = next_seq
        super().__init__(
            f"{remaining} unplayed cassette exchange(s); next seq is {next_seq}"
        )


class CommunicationError(BenchVCRError):
    """Base class for errors safe to store in and replay from a cassette."""

    kind: ClassVar[str] = "transport"

    def as_dict(self) -> dict[str, str]:
        return {"type": self.kind, "message": str(self)}


class TransportTimeoutError(CommunicationError):
    kind = "timeout"


class DisconnectError(CommunicationError):
    kind = "disconnect"


class ProtocolError(CommunicationError):
    kind = "protocol"


class TransportError(CommunicationError):
    kind = "transport"


_ERROR_TYPES: dict[str, type[CommunicationError]] = {
    "timeout": TransportTimeoutError,
    "disconnect": DisconnectError,
    "protocol": ProtocolError,
    "transport": TransportError,
}
ERROR_KINDS = frozenset(_ERROR_TYPES)


def error_from_dict(value: Mapping[str, object]) -> CommunicationError:
    """Create a communication error from an already validated error object."""

    error_type = _ERROR_TYPES[str(value["type"])]
    return error_type(str(value["message"]))
