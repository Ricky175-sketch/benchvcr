"""Cassette JSONL v1 parsing and validation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, TypeAlias, TypeGuard

from .errors import (
    ERROR_KINDS,
    CassetteValidationError,
    CommunicationError,
    error_from_dict,
)

CASSETTE_FORMAT = "benchvcr"
SCHEMA_VERSION = 1
PROTOCOL = "text"
Kind: TypeAlias = Literal["write", "query"]
PathLike: TypeAlias = str | Path

_HEADER_FIELDS = {
    "format",
    "schema_version",
    "protocol",
    "library_version",
    "created_at",
}
_EXCHANGE_FIELDS = {
    "seq",
    "kind",
    "command",
    "at_ms",
    "duration_ms",
    "ok",
    "response",
    "error",
}


@dataclass(frozen=True)
class CassetteHeader:
    library_version: str
    created_at: str


@dataclass(frozen=True)
class Exchange:
    seq: int
    kind: Kind
    command: str
    at_ms: float
    duration_ms: float
    ok: bool
    response: str | None
    error: CommunicationError | None

    def as_dict(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "command": self.command,
            "at_ms": self.at_ms,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "response": self.response,
            "error": None if self.error is None else self.error.as_dict(),
        }


@dataclass(frozen=True)
class Cassette:
    header: CassetteHeader
    exchanges: tuple[Exchange, ...]


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON number {value}")


def _parse_json_object(text: str) -> dict[str, object]:
    value = json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _decode_file(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw[: exc.start].count(b"\n") + 1
        raise CassetteValidationError(
            path, line, f"invalid UTF-8: {exc.reason}"
        ) from None


def _fail(path: Path, line: int, reason: str) -> CassetteValidationError:
    return CassetteValidationError(path, line, reason)


def _parse_header(value: dict[str, object], path: Path, line: int) -> CassetteHeader:
    if value.get("format") != CASSETTE_FORMAT:
        raise _fail(path, line, "unsupported cassette format")
    version = value.get("schema_version")
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise _fail(path, line, f"unsupported schema_version {version!r}")
    unknown = set(value) - _HEADER_FIELDS
    missing = _HEADER_FIELDS - set(value)
    if unknown:
        raise _fail(path, line, f"unknown header field(s): {sorted(unknown)}")
    if missing:
        raise _fail(path, line, f"missing header field(s): {sorted(missing)}")
    if value.get("protocol") != PROTOCOL:
        raise _fail(path, line, "unsupported protocol")
    library_version = value["library_version"]
    created_at = value["created_at"]
    if not isinstance(library_version, str) or not library_version:
        raise _fail(path, line, "library_version must be a non-empty string")
    if not isinstance(created_at, str):
        raise _fail(path, line, "created_at must be a UTC timestamp string")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        raise _fail(
            path, line, "created_at is not a valid ISO-8601 timestamp"
        ) from None
    if parsed.utcoffset() != timedelta(0):
        raise _fail(path, line, "created_at must be UTC")
    return CassetteHeader(library_version, created_at)


def _number(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _parse_exchange(
    value: dict[str, object], path: Path, line: int, expected_seq: int
) -> Exchange:
    if "format" in value and "schema_version" in value:
        raise _fail(path, line, "duplicate header; expected an exchange")
    unknown = set(value) - _EXCHANGE_FIELDS
    missing = _EXCHANGE_FIELDS - set(value)
    if unknown:
        raise _fail(path, line, f"unknown exchange field(s): {sorted(unknown)}")
    if missing:
        raise _fail(path, line, f"missing exchange field(s): {sorted(missing)}")

    seq = value["seq"]
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise _fail(path, line, "seq must be a non-negative integer")
    if seq != expected_seq:
        raise _fail(
            path, line, f"non-contiguous seq: expected {expected_seq}, got {seq}"
        )
    kind = value["kind"]
    if kind not in ("write", "query"):
        raise _fail(path, line, "kind must be 'write' or 'query'")
    command = value["command"]
    if (
        not isinstance(command, str)
        or not command
        or "\n" in command
        or "\r" in command
    ):
        raise _fail(path, line, "command must be non-empty and contain no newlines")
    at_ms = value["at_ms"]
    duration_ms = value["duration_ms"]
    if not _number(at_ms) or float(at_ms) < 0:
        raise _fail(path, line, "at_ms must be a finite non-negative number")
    if not _number(duration_ms) or float(duration_ms) < 0:
        raise _fail(path, line, "duration_ms must be a finite non-negative number")
    ok = value["ok"]
    if not isinstance(ok, bool):
        raise _fail(path, line, "ok must be a boolean")
    response = value["response"]
    error_value = value["error"]
    error: CommunicationError | None = None

    if ok:
        if error_value is not None:
            raise _fail(path, line, "successful exchange must have a null error")
        if kind == "write" and response is not None:
            raise _fail(path, line, "successful write must have a null response")
        if kind == "query" and not isinstance(response, str):
            raise _fail(path, line, "successful query response must be a string")
    else:
        if response is not None:
            raise _fail(path, line, "failed exchange must have a null response")
        if not isinstance(error_value, dict):
            raise _fail(path, line, "failed exchange must contain an error object")
        if set(error_value) != {"type", "message"}:
            raise _fail(path, line, "error must contain exactly type and message")
        error_type = error_value["type"]
        message = error_value["message"]
        if not isinstance(error_type, str) or error_type not in ERROR_KINDS:
            raise _fail(path, line, f"unsupported error type {error_type!r}")
        if not isinstance(message, str) or not message:
            raise _fail(path, line, "error message must be a non-empty string")
        error = error_from_dict(error_value)

    return Exchange(
        seq=seq,
        kind=kind,
        command=command,
        at_ms=float(at_ms),
        duration_ms=float(duration_ms),
        ok=ok,
        response=response if isinstance(response, str) else None,
        error=error,
    )


def validate_cassette(path: PathLike) -> Cassette:
    """Read and fully validate a cassette, returning its immutable contents."""

    cassette_path = Path(path)
    text = _decode_file(cassette_path)
    lines = text.splitlines()
    if not lines:
        raise _fail(cassette_path, 1, "empty cassette; expected a header")

    objects: list[dict[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise _fail(cassette_path, line_number, "blank lines are not allowed")
        try:
            objects.append(_parse_json_object(line))
        except (json.JSONDecodeError, _DuplicateKey, ValueError) as exc:
            raise _fail(cassette_path, line_number, f"invalid JSON: {exc}") from None

    header = _parse_header(objects[0], cassette_path, 1)
    exchanges: list[Exchange] = []
    previous_at = 0.0
    for line_number, value in enumerate(objects[1:], start=2):
        exchange = _parse_exchange(
            value, cassette_path, line_number, expected_seq=len(exchanges)
        )
        if exchange.at_ms < previous_at:
            raise _fail(
                cassette_path,
                line_number,
                f"at_ms moved backwards: {exchange.at_ms} < {previous_at}",
            )
        exchanges.append(exchange)
        previous_at = exchange.at_ms
    return Cassette(header=header, exchanges=tuple(exchanges))


def json_line(value: dict[str, object]) -> str:
    """Serialize one canonical JSONL record without non-standard numbers."""

    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    )
