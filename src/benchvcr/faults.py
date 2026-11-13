"""Deterministic, stateless fault plans for cassette replay."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard, cast

from .cassette import Exchange, Kind, PathLike, _parse_json_object
from .errors import (
    ConfigurationError,
    DisconnectError,
    TransportTimeoutError,
)

FAULT_PLAN_FORMAT = "benchvcr-fault-plan"
_OPERATIONS = {
    "delay",
    "timeout",
    "disconnect",
    "truncate",
    "response_replace",
}
_COMMON_RULE_FIELDS = {"at", "match", "operation", "probability"}
_OPERATION_FIELDS = {
    "delay": {"delay_ms"},
    "timeout": set(),
    "disconnect": set(),
    "truncate": {"length"},
    "response_replace": {"response"},
}


@dataclass(frozen=True)
class FaultMatch:
    kind: Kind | None = None
    command: str | None = None


@dataclass(frozen=True)
class FaultRule:
    index: int
    at: int
    operation: str
    match: FaultMatch
    probability: float
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class FaultPlan:
    seed: int
    rules: tuple[FaultRule, ...]

    def rule_for(self, exchange: Exchange) -> FaultRule | None:
        """Return the first eligible rule whose deterministic draw triggers."""

        for rule in self.rules:
            if rule.at != exchange.seq:
                continue
            if rule.match.kind is not None and rule.match.kind != exchange.kind:
                continue
            if (
                rule.match.command is not None
                and rule.match.command != exchange.command
            ):
                continue
            if rule.operation in {"truncate", "response_replace"} and not (
                exchange.kind == "query" and exchange.ok
            ):
                continue
            if rule.probability == 0:
                continue
            if rule.probability < 1 and (
                probability_sample(self.seed, exchange.seq, rule.index)
                >= rule.probability
            ):
                continue
            return rule
        return None


def probability_sample(seed: int, seq: int, rule_index: int) -> float:
    """Map SHA-256(benchvcr:v1:seed:seq:rule_index) to [0, 1).

    The first eight digest bytes are interpreted as an unsigned big-endian
    integer and divided by 2**64. No process-global random state is involved.
    """

    payload = f"benchvcr:v1:{seed}:{seq}:{rule_index}".encode("ascii")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def apply_fault(
    rule: FaultRule, exchange: Exchange, sleep: Callable[[float], None]
) -> str | None:
    """Apply one selected rule and return the possibly modified response."""

    operation = rule.operation
    if operation == "delay":
        sleep(cast(float, rule.parameters["delay_ms"]) / 1000.0)
    elif operation == "timeout":
        raise TransportTimeoutError("injected timeout")
    elif operation == "disconnect":
        raise DisconnectError("injected disconnect")
    elif operation == "truncate":
        response = exchange.response
        assert response is not None
        return response[: cast(int, rule.parameters["length"])]
    elif operation == "response_replace":
        return cast(str, rule.parameters["response"])
    return exchange.response


def _config(path: Path, reason: str) -> ConfigurationError:
    return ConfigurationError(f"{path}: {reason}")


def _finite_number(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _read_object(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw[: exc.start].count(b"\n") + 1
        raise _config(path, f"line {line}: invalid UTF-8: {exc.reason}") from None
    try:
        return _parse_json_object(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _config(path, f"invalid JSON: {exc}") from None


def _parse_match(value: object, path: Path, index: int) -> FaultMatch:
    if not isinstance(value, dict):
        raise _config(path, f"rule {index}: match must be an object")
    if set(value) - {"kind", "command"}:
        raise _config(path, f"rule {index}: unknown match field(s)")
    kind = value.get("kind")
    command = value.get("command")
    if kind is not None and kind not in ("write", "query"):
        raise _config(path, f"rule {index}: match.kind must be write or query")
    if command is not None and (
        not isinstance(command, str)
        or not command
        or "\n" in command
        or "\r" in command
    ):
        raise _config(path, f"rule {index}: invalid match.command")
    return FaultMatch(kind=cast(Kind | None, kind), command=command)


def _parse_rule(value: object, path: Path, index: int) -> FaultRule:
    if not isinstance(value, dict):
        raise _config(path, f"rule {index}: expected an object")
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        raise _config(path, f"rule {index}: unsupported operation {operation!r}")
    operation_name = operation
    allowed = _COMMON_RULE_FIELDS | _OPERATION_FIELDS[operation_name]
    required = {"at", "operation"} | _OPERATION_FIELDS[operation_name]
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing or unknown:
        raise _config(
            path,
            f"rule {index}: field mismatch; missing={missing}, unknown={unknown}",
        )
    at = value["at"]
    if isinstance(at, bool) or not isinstance(at, int) or at < 0:
        raise _config(path, f"rule {index}: at must be a non-negative integer")
    probability = value.get("probability", 1.0)
    if not _finite_number(probability) or not 0 <= probability <= 1:
        raise _config(path, f"rule {index}: probability must be in [0, 1]")

    parameters: dict[str, object] = {}
    if operation_name == "delay":
        delay_ms = value["delay_ms"]
        if not _finite_number(delay_ms) or delay_ms < 0:
            raise _config(path, f"rule {index}: delay_ms must be non-negative")
        parameters["delay_ms"] = float(delay_ms)
    elif operation_name == "truncate":
        length = value["length"]
        if isinstance(length, bool) or not isinstance(length, int) or length < 0:
            raise _config(path, f"rule {index}: length must be a non-negative integer")
        parameters["length"] = length
    elif operation_name == "response_replace":
        response = value["response"]
        if not isinstance(response, str):
            raise _config(path, f"rule {index}: response must be a string")
        parameters["response"] = response

    return FaultRule(
        index=index,
        at=at,
        operation=operation_name,
        match=(
            FaultMatch()
            if "match" not in value
            else _parse_match(value["match"], path, index)
        ),
        probability=float(probability),
        parameters=parameters,
    )


def load_fault_plan(path: PathLike) -> FaultPlan:
    """Load a JSON fault plan, raising ConfigurationError for bad structure."""

    plan_path = Path(path)
    value = _read_object(plan_path)
    if value.get("format") != FAULT_PLAN_FORMAT:
        raise _config(plan_path, "unsupported fault plan format")
    version = value.get("schema_version")
    if isinstance(version, bool) or version != 1:
        raise _config(plan_path, f"unsupported schema_version {version!r}")
    if set(value) != {"format", "schema_version", "seed", "rules"}:
        raise _config(plan_path, "fault plan must contain format, version, seed, rules")
    seed = value["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise _config(plan_path, "seed must be an integer")
    rules = value["rules"]
    if not isinstance(rules, list):
        raise _config(plan_path, "rules must be an array")
    return FaultPlan(
        seed=seed,
        rules=tuple(
            _parse_rule(rule, plan_path, index) for index, rule in enumerate(rules)
        ),
    )
