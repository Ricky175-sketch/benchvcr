from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import exchange, write_cassette, write_fault_plan

from benchvcr import (
    ConfigurationError,
    DisconnectError,
    TransportTimeoutError,
    load_fault_plan,
    probability_sample,
    use_cassette,
)
from benchvcr.session import ReplaySession


def one_query(tmp_path: Path, response: str = "abcdef") -> Path:
    return write_cassette(
        tmp_path / "one.jsonl", [exchange(0, command="A?", response=response)]
    )


def test_fixed_probability_vectors() -> None:
    vectors = [
        ((42, 0, 0), "b3c155444bcd52c1", 0.7021687785852937),
        ((42, 1, 0), "38e0a97091e36bea", 0.22217806814468383),
        ((42, 1, 1), "54d85bebf5de6c14", 0.3314263773989922),
        ((-7, 9, 2), "dcb99691c108a55f", 0.8622068506092854),
    ]
    for arguments, digest_prefix, expected in vectors:
        assert probability_sample(*arguments) == expected
        assert (
            int.from_bytes(bytes.fromhex(digest_prefix), "big") / float(1 << 64)
            == expected
        )


def test_load_plan_with_optional_match_and_probability(tmp_path: Path) -> None:
    path = write_fault_plan(
        tmp_path / "plan.json",
        [{"at": 0, "operation": "delay", "delay_ms": 2}],
    )
    plan = load_fault_plan(path)
    assert plan.seed == 42
    assert plan.rules[0].probability == 1
    assert plan.rules[0].match.kind is None
    assert plan.rules[0].match.command is None


def test_delay_uses_injected_sleep_and_returns_original(tmp_path: Path) -> None:
    cassette = one_query(tmp_path)
    plan_path = write_fault_plan(
        tmp_path / "delay.json",
        [{"at": 0, "operation": "delay", "delay_ms": 25}],
    )
    sleeps: list[float] = []
    with ReplaySession(cassette, fault_plan=plan_path, sleep=sleeps.append) as replay:
        assert replay.query("A?") == "abcdef"
    assert sleeps == [0.025]


def test_delay_before_recorded_error(tmp_path: Path) -> None:
    cassette = write_cassette(
        tmp_path / "error.jsonl",
        [
            exchange(
                0,
                command="A?",
                ok=False,
                error={"type": "timeout", "message": "recorded"},
            )
        ],
    )
    plan = write_fault_plan(
        tmp_path / "delay.json",
        [{"at": 0, "operation": "delay", "delay_ms": 1}],
    )
    sleeps: list[float] = []
    with ReplaySession(cassette, fault_plan=plan, sleep=sleeps.append) as replay:
        with pytest.raises(TransportTimeoutError, match="recorded"):
            replay.query("A?")
    assert sleeps == [0.001]


def test_timeout_and_disconnect_consume_and_allow_continuation(tmp_path: Path) -> None:
    cassette = write_cassette(
        tmp_path / "two.jsonl",
        [exchange(0, command="A?"), exchange(1, command="B?", response="ok")],
    )
    plan = write_fault_plan(
        tmp_path / "errors.json",
        [
            {"at": 0, "operation": "timeout"},
            {"at": 1, "operation": "disconnect"},
        ],
    )
    with use_cassette(cassette, mode="replay", fault_plan=plan) as replay:
        with pytest.raises(TransportTimeoutError, match="injected timeout"):
            replay.query("A?")
        with pytest.raises(DisconnectError, match="injected disconnect"):
            replay.query("B?")


def test_truncate_and_replace_including_empty_string(tmp_path: Path) -> None:
    cassette = write_cassette(
        tmp_path / "text.jsonl",
        [exchange(0, command="A?", response="abcdef"), exchange(1, command="B?")],
    )
    plan = write_fault_plan(
        tmp_path / "text-plan.json",
        [
            {"at": 0, "operation": "truncate", "length": 3},
            {"at": 1, "operation": "response_replace", "response": ""},
        ],
    )
    with use_cassette(cassette, mode="replay", fault_plan=plan) as replay:
        assert replay.query("A?") == "abc"
        assert replay.query("B?") == ""


def test_response_modifiers_skip_write_and_failed_query(tmp_path: Path) -> None:
    cassette = write_cassette(
        tmp_path / "eligible.jsonl",
        [
            exchange(0, kind="write", command="RST"),
            exchange(
                1,
                command="BAD?",
                ok=False,
                error={"type": "protocol", "message": "bad"},
            ),
            exchange(2, command="GOOD?", response="good"),
        ],
    )
    plan = write_fault_plan(
        tmp_path / "eligible-plan.json",
        [
            {"at": 0, "operation": "response_replace", "response": "no"},
            {"at": 1, "operation": "truncate", "length": 1},
            {"at": 1, "operation": "disconnect"},
            {"at": 2, "operation": "truncate", "length": 2},
        ],
    )
    with use_cassette(cassette, mode="replay", fault_plan=plan) as replay:
        replay.write("RST")
        with pytest.raises(DisconnectError):
            replay.query("BAD?")
        assert replay.query("GOOD?") == "go"


def test_match_and_array_order_select_first_actual_fault(tmp_path: Path) -> None:
    cassette = one_query(tmp_path)
    plan = write_fault_plan(
        tmp_path / "ordered.json",
        [
            {
                "at": 0,
                "match": {"command": "OTHER?"},
                "operation": "timeout",
            },
            {"at": 0, "match": {"kind": "write"}, "operation": "disconnect"},
            {"at": 0, "operation": "delay", "delay_ms": 0},
            {"at": 0, "operation": "timeout"},
        ],
    )
    sleeps: list[float] = []
    with ReplaySession(cassette, fault_plan=plan, sleep=sleeps.append) as replay:
        assert replay.query("A?") == "abcdef"
    assert sleeps == [0.0]


def test_probability_threshold_is_reproducible(tmp_path: Path) -> None:
    cassette = one_query(tmp_path)
    below = write_fault_plan(
        tmp_path / "below.json",
        [{"at": 0, "operation": "timeout", "probability": 0.7}],
    )
    above = write_fault_plan(
        tmp_path / "above.json",
        [{"at": 0, "operation": "timeout", "probability": 0.703}],
    )
    for _ in range(2):
        with use_cassette(cassette, mode="replay", fault_plan=below) as replay:
            assert replay.query("A?") == "abcdef"
        with use_cassette(cassette, mode="replay", fault_plan=above) as replay:
            with pytest.raises(TransportTimeoutError):
                replay.query("A?")


def test_zero_and_one_probability_have_defined_boundaries(tmp_path: Path) -> None:
    cassette = one_query(tmp_path)
    zero = write_fault_plan(
        tmp_path / "zero.json",
        [{"at": 0, "operation": "timeout", "probability": 0}],
    )
    one = write_fault_plan(
        tmp_path / "one.json",
        [{"at": 0, "operation": "timeout", "probability": 1}],
    )
    with use_cassette(cassette, mode="replay", fault_plan=zero) as replay:
        assert replay.query("A?") == "abcdef"
    with use_cassette(cassette, mode="replay", fault_plan=one) as replay:
        with pytest.raises(TransportTimeoutError):
            replay.query("A?")


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        ({}, "unsupported fault plan format"),
        (
            {"format": "benchvcr-fault-plan", "schema_version": 2},
            "unsupported schema_version",
        ),
        (
            {
                "format": "benchvcr-fault-plan",
                "schema_version": 1,
                "seed": True,
                "rules": [],
            },
            "seed must be an integer",
        ),
        (
            {
                "format": "benchvcr-fault-plan",
                "schema_version": 1,
                "seed": 1,
                "rules": {},
            },
            "rules must be an array",
        ),
    ],
)
def test_bad_plan_documents(
    tmp_path: Path, document: dict[str, object], reason: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=reason):
        load_fault_plan(path)


@pytest.mark.parametrize(
    ("rule", "reason"),
    [
        ({"at": 0, "operation": "other"}, "unsupported operation"),
        ({"at": 0, "operation": []}, "unsupported operation"),
        ({"operation": "timeout"}, "field mismatch"),
        ({"at": -1, "operation": "timeout"}, "at must"),
        ({"at": True, "operation": "timeout"}, "at must"),
        (
            {"at": 0, "operation": "timeout", "probability": 2},
            "probability",
        ),
        (
            {"at": 0, "operation": "timeout", "probability": 10**1000},
            "probability",
        ),
        ({"at": 0, "operation": "delay", "delay_ms": -1}, "delay_ms"),
        ({"at": 0, "operation": "delay", "delay_ms": 10**1000}, "delay_ms"),
        ({"at": 0, "operation": "delay"}, "field mismatch"),
        ({"at": 0, "operation": "truncate", "length": -1}, "length"),
        ({"at": 0, "operation": "response_replace", "response": 1}, "response"),
        ({"at": 0, "operation": "timeout", "match": None}, "match must"),
        ({"at": 0, "operation": "timeout", "match": {"kind": "read"}}, "kind"),
        ({"at": 0, "operation": "timeout", "match": {"command": ""}}, "command"),
        ({"at": 0, "operation": "timeout", "match": {"regex": "x"}}, "unknown match"),
        ({"at": 0, "operation": "timeout", "extra": 1}, "field mismatch"),
    ],
)
def test_bad_rules(tmp_path: Path, rule: dict[str, object], reason: str) -> None:
    path = write_fault_plan(tmp_path / "bad-rule.json", [rule])
    with pytest.raises(ConfigurationError, match=reason):
        load_fault_plan(path)


def test_invalid_json_and_utf8_are_configuration_errors(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid JSON"):
        load_fault_plan(invalid)
    invalid.write_bytes(b"\xff")
    with pytest.raises(ConfigurationError, match="invalid UTF-8"):
        load_fault_plan(invalid)
