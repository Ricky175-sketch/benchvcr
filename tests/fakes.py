"""Test-only fakes and cassette construction helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Step:
    kind: str
    command: str
    response: Any = None
    error: Exception | None = None


class FakeTransport:
    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def _call(self, kind: str, command: str) -> Any:
        assert not self.closed
        self.calls.append((kind, command))
        assert self.steps, f"unexpected {kind} {command!r}"
        step = self.steps.pop(0)
        assert (kind, command) == (step.kind, step.command)
        if step.error is not None:
            raise step.error
        return step.response

    def write(self, command: str) -> None:
        self._call("write", command)

    def query(self, command: str) -> str:
        return self._call("query", command)

    def close(self) -> None:
        self.closed = True


def header(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "format": "benchvcr",
        "schema_version": 1,
        "protocol": "text",
        "library_version": "0.1.0",
        "created_at": "2026-01-02T03:04:05Z",
    }
    value.update(changes)
    return value


def exchange(
    seq: int,
    kind: str = "query",
    command: str = "MEAS?",
    response: Any = None,
    *,
    at_ms: float | None = None,
    duration_ms: float = 0.25,
    ok: bool = True,
    error: dict[str, str] | None = None,
    **changes: Any,
) -> dict[str, Any]:
    if response is None and ok and kind == "query":
        response = "response"
    value = {
        "seq": seq,
        "kind": kind,
        "command": command,
        "at_ms": float(seq) if at_ms is None else at_ms,
        "duration_ms": duration_ms,
        "ok": ok,
        "response": response,
        "error": error,
    }
    value.update(changes)
    return value


def cassette_text(
    exchanges: list[dict[str, Any]], header_value: dict[str, Any] | None = None
) -> str:
    records = [header() if header_value is None else header_value, *exchanges]
    return "".join(
        json.dumps(record, separators=(",", ":")) + "\n" for record in records
    )


def write_cassette(path: Path, exchanges: list[dict[str, Any]]) -> Path:
    path.write_text(cassette_text(exchanges), encoding="utf-8")
    return path


def write_fault_plan(
    path: Path, rules: list[dict[str, Any]], *, seed: int = 42
) -> Path:
    path.write_text(
        json.dumps(
            {
                "format": "benchvcr-fault-plan",
                "schema_version": 1,
                "seed": seed,
                "rules": rules,
            }
        ),
        encoding="utf-8",
    )
    return path
