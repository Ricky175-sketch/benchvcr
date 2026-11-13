"""End-to-end deterministic virtual-instrument demonstration."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .cassette import validate_cassette
from .errors import (
    BenchVCRError,
    CommunicationError,
    DisconnectError,
    TransportTimeoutError,
)
from .session import RecordSession, ReplaySession, use_cassette
from .virtual import IDN_RESPONSE, VirtualPowerSupply


class DemoFailure(BenchVCRError):
    pass


@dataclass(frozen=True)
class Operation:
    kind: str
    command: str
    expected: str | None = None


OPERATIONS = (
    Operation("query", "*IDN?", IDN_RESPONSE),
    Operation("write", "*RST"),
    Operation("write", "VOLT 12"),
    Operation("write", "CURR 0.5"),
    Operation("write", "OUTP ON"),
    Operation("query", "VOLT?", "12.000000"),
    Operation("query", "CURR?", "0.500000"),
    Operation("query", "OUTP?", "1"),
    Operation("query", "MEAS:VOLT?", "5.000000"),
    Operation("query", "MEAS:CURR?", "0.500000"),
    Operation("write", "OUTP OFF"),
    Operation("query", "MEAS:VOLT?", "0.000000"),
    Operation("query", "MEAS:CURR?", "0.000000"),
)


@dataclass(frozen=True)
class FaultCase:
    name: str
    at: int
    rule: dict[str, object]
    expected: str | None = None
    error_type: type[CommunicationError] | None = None


@dataclass(frozen=True)
class DemoResult:
    cassette_path: Path
    sha256: str
    checks: tuple[str, ...]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exercise(
    session: RecordSession | ReplaySession, fault: FaultCase | None = None
) -> None:
    triggered = False
    for seq, operation in enumerate(OPERATIONS):
        expected = operation.expected
        if fault is not None and seq == fault.at:
            expected = fault.expected
        try:
            if operation.kind == "write":
                result = session.write(operation.command)
            else:
                result = session.query(operation.command)
        except CommunicationError as exc:
            if (
                fault is None
                or seq != fault.at
                or fault.error_type is None
                or type(exc) is not fault.error_type
            ):
                raise DemoFailure(
                    f"unexpected communication error at seq {seq}: {exc}"
                ) from exc
            triggered = True
            continue
        if result != expected:
            raise DemoFailure(f"seq {seq} returned {result!r}; expected {expected!r}")
        if fault is not None and seq == fault.at:
            if fault.error_type is not None:
                raise DemoFailure(f"fault {fault.name} did not raise at seq {seq}")
            triggered = True
    if fault is not None and not triggered:
        raise DemoFailure(f"fault {fault.name} did not trigger")


def _fault_cases() -> tuple[FaultCase, ...]:
    return (
        FaultCase(
            "delay",
            8,
            {"operation": "delay", "delay_ms": 1},
            expected="5.000000",
        ),
        FaultCase(
            "timeout", 5, {"operation": "timeout"}, error_type=TransportTimeoutError
        ),
        FaultCase(
            "disconnect",
            10,
            {"operation": "disconnect"},
            error_type=DisconnectError,
        ),
        FaultCase(
            "truncate", 0, {"operation": "truncate", "length": 4}, expected="Benc"
        ),
        FaultCase(
            "response_replace",
            9,
            {"operation": "response_replace", "response": ""},
            expected="",
        ),
    )


def run_demo(
    output_dir: str | Path, *, seed: int = 42, stream: TextIO | None = None
) -> DemoResult:
    """Run record, clean/fault replays, and cassette immutability checks."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stream = sys.stdout if stream is None else stream
    cassette_path = output / "virtual-psu.jsonl"
    checks: list[str] = []

    supply = VirtualPowerSupply()
    try:
        with use_cassette(cassette_path, transport=supply, overwrite=True) as recording:
            _exercise(recording)
    finally:
        supply.close()
    exchange_count = len(validate_cassette(cassette_path).exchanges)
    print(f"PASS record ({exchange_count} exchanges)", file=stream)
    checks.append("record")

    original_hash = _digest(cassette_path)
    with use_cassette(cassette_path, mode="replay") as replay:
        _exercise(replay)
    print("PASS clean replay", file=stream)
    checks.append("clean replay")

    for fault in _fault_cases():
        operation = OPERATIONS[fault.at]
        rule = {
            "at": fault.at,
            "match": {"kind": operation.kind, "command": operation.command},
            **fault.rule,
        }
        plan_path = output / f"fault-{fault.name}.json"
        plan_path.write_text(
            json.dumps(
                {
                    "format": "benchvcr-fault-plan",
                    "schema_version": 1,
                    "seed": seed,
                    "rules": [rule],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with use_cassette(cassette_path, mode="replay", fault_plan=plan_path) as replay:
            _exercise(replay, fault)
        print(f"PASS fault: {fault.name}", file=stream)
        checks.append(f"fault: {fault.name}")
        if _digest(cassette_path) != original_hash:
            raise DemoFailure(f"cassette changed during fault {fault.name}")

    final_hash = _digest(cassette_path)
    if final_hash != original_hash:
        raise DemoFailure("cassette hash changed during demo")
    print(f"PASS cassette hash unchanged ({final_hash})", file=stream)
    checks.append("cassette hash unchanged")
    print(f"Cassette: {cassette_path}", file=stream)
    return DemoResult(cassette_path, final_hash, tuple(checks))
