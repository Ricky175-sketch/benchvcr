from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fakes import FakeTransport, Step, exchange, write_cassette

from benchvcr import (
    CassetteMismatchError,
    ConfigurationError,
    ProtocolError,
    SessionStateError,
    TransportTimeoutError,
    UnplayedInteractionsError,
    use_cassette,
    validate_cassette,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_record_then_replay_including_empty_response(tmp_path: Path) -> None:
    path = tmp_path / "basic.jsonl"
    transport = FakeTransport(
        [
            Step("query", "*IDN?", "virtual"),
            Step("write", "*RST"),
            Step("query", "EMPTY?", ""),
        ]
    )

    with use_cassette(path, transport=transport) as taped:
        assert taped.query("*IDN?") == "virtual"
        taped.write("*RST")
        assert taped.query("EMPTY?") == ""
        taped.close()

    assert not transport.closed
    cassette = validate_cassette(path)
    assert [item.seq for item in cassette.exchanges] == [0, 1, 2]
    assert [item.kind for item in cassette.exchanges] == ["query", "write", "query"]
    assert cassette.exchanges[2].response == ""
    assert all(item.at_ms >= 0 and item.duration_ms >= 0 for item in cassette.exchanges)
    assert [a.at_ms for a in cassette.exchanges] == sorted(
        a.at_ms for a in cassette.exchanges
    )

    with use_cassette(path, mode="replay") as replay:
        assert replay.query("*IDN?") == "virtual"
        replay.write("*RST")
        assert replay.query("EMPTY?") == ""


def test_record_refuses_overwrite_by_default(tmp_path: Path) -> None:
    path = tmp_path / "existing.jsonl"
    path.write_bytes(b"original")
    transport = FakeTransport([])
    with pytest.raises(ConfigurationError, match="already exists"):
        with use_cassette(path, transport=transport):
            pass
    assert path.read_bytes() == b"original"
    assert not transport.closed


def test_record_overwrite_is_explicit(tmp_path: Path) -> None:
    path = write_cassette(tmp_path / "existing.jsonl", [exchange(0)])
    transport = FakeTransport([Step("query", "NEW?", "new")])
    with use_cassette(path, transport=transport, overwrite=True) as taped:
        assert taped.query("NEW?") == "new"
    assert [e.command for e in validate_cassette(path).exchanges] == ["NEW?"]


def test_body_exception_preserves_original_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "partial.jsonl"
    original = RuntimeError("test body failed")
    transport = FakeTransport([Step("query", "A?", "a")])
    with pytest.raises(RuntimeError) as caught:
        with use_cassette(path, transport=transport) as taped:
            assert taped.query("A?") == "a"
            raise original
    assert caught.value is original
    assert not path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_body_exception_preserves_existing_cassette(tmp_path: Path) -> None:
    path = tmp_path / "existing.jsonl"
    path.write_bytes(b"original")
    transport = FakeTransport([])
    with pytest.raises(ValueError, match="body"):
        with use_cassette(path, transport=transport, overwrite=True):
            raise ValueError("body")
    assert path.read_bytes() == b"original"


def test_caught_hardware_error_is_recorded_and_replay_can_continue(
    tmp_path: Path,
) -> None:
    path = tmp_path / "errors.jsonl"
    transport = FakeTransport(
        [
            Step("query", "A?", error=TransportTimeoutError("slow")),
            Step("query", "B?", "ok"),
        ]
    )
    with use_cassette(path, transport=transport) as taped:
        with pytest.raises(TransportTimeoutError, match="slow"):
            taped.query("A?")
        assert taped.query("B?") == "ok"

    exchanges = validate_cassette(path).exchanges
    assert not exchanges[0].ok
    assert exchanges[0].error is not None
    assert exchanges[0].error.as_dict() == {"type": "timeout", "message": "slow"}

    with use_cassette(path, mode="replay") as replay:
        with pytest.raises(TransportTimeoutError, match="slow"):
            replay.query("A?")
        assert replay.query("B?") == "ok"


def test_uncaught_hardware_error_does_not_publish(tmp_path: Path) -> None:
    path = tmp_path / "uncaught.jsonl"
    transport = FakeTransport(
        [Step("query", "A?", error=TransportTimeoutError("slow"))]
    )
    with pytest.raises(TransportTimeoutError):
        with use_cassette(path, transport=transport) as taped:
            taped.query("A?")
    assert not path.exists()


def test_builtin_timeout_is_normalized_when_recorded(tmp_path: Path) -> None:
    path = tmp_path / "timeout.jsonl"
    transport = FakeTransport([Step("query", "A?", error=TimeoutError("late"))])
    with use_cassette(path, transport=transport) as taped:
        with pytest.raises(TransportTimeoutError, match="late"):
            taped.query("A?")
    assert validate_cassette(path).exchanges[0].error is not None


def test_non_text_query_response_is_a_recorded_protocol_error(tmp_path: Path) -> None:
    path = tmp_path / "protocol.jsonl"
    transport = FakeTransport([Step("query", "A?", response=b"bytes")])
    with use_cassette(path, transport=transport) as taped:
        with pytest.raises(ProtocolError, match="non-text"):
            taped.query("A?")
    error = validate_cassette(path).exchanges[0].error
    assert isinstance(error, ProtocolError)


def test_mismatch_does_not_consume_exchange(tmp_path: Path) -> None:
    path = write_cassette(
        tmp_path / "strict.jsonl",
        [exchange(0, command="A?", response="a"), exchange(1, command="B?")],
    )
    with use_cassette(path, mode="replay") as replay:
        with pytest.raises(CassetteMismatchError) as caught:
            replay.query("WRONG?")
        assert caught.value.seq == 0
        assert caught.value.expected_command == "A?"
        assert caught.value.actual_command == "WRONG?"
        assert replay.query("A?") == "a"
        assert replay.query("B?") == "response"


def test_kind_mismatch_also_leaves_exchange_available(tmp_path: Path) -> None:
    path = write_cassette(
        tmp_path / "kind.jsonl", [exchange(0, command="A?", response="a")]
    )
    with use_cassette(path, mode="replay") as replay:
        with pytest.raises(CassetteMismatchError, match="expected query"):
            replay.write("A?")
        assert replay.query("A?") == "a"


def test_exhaustion_is_a_mismatch(tmp_path: Path) -> None:
    path = write_cassette(tmp_path / "one.jsonl", [exchange(0)])
    with use_cassette(path, mode="replay") as replay:
        replay.query("MEAS?")
        with pytest.raises(CassetteMismatchError, match="end of cassette") as caught:
            replay.query("MEAS?")
        assert caught.value.seq == 1


def test_unplayed_interactions_fail_only_normal_exit(tmp_path: Path) -> None:
    path = write_cassette(
        tmp_path / "unplayed.jsonl", [exchange(0), exchange(1, command="B?")]
    )
    with pytest.raises(UnplayedInteractionsError) as caught:
        with use_cassette(path, mode="replay") as replay:
            replay.query("MEAS?")
    assert caught.value.remaining == 1
    assert caught.value.next_seq == 1


def test_body_exception_is_not_masked_by_unplayed_or_cleanup(tmp_path: Path) -> None:
    path = write_cassette(tmp_path / "unplayed.jsonl", [exchange(0), exchange(1)])
    original = AssertionError("assertion from test body")
    with pytest.raises(AssertionError) as caught:
        with use_cassette(path, mode="replay"):
            raise original
    assert caught.value is original


def test_replay_never_modifies_cassette(tmp_path: Path) -> None:
    path = write_cassette(tmp_path / "immutable.jsonl", [exchange(0)])
    before = digest(path)
    with use_cassette(path, mode="replay") as replay:
        replay.query("MEAS?")
    assert digest(path) == before


def test_invalid_command_does_not_reach_transport_or_consume(tmp_path: Path) -> None:
    record_path = tmp_path / "invalid-command.jsonl"
    transport = FakeTransport([])
    with pytest.raises(ValueError, match="without newlines"):
        with use_cassette(record_path, transport=transport) as taped:
            taped.query("A\n")
    assert transport.calls == []

    path = write_cassette(tmp_path / "valid.jsonl", [exchange(0)])
    with use_cassette(path, mode="replay") as replay:
        with pytest.raises(ValueError):
            replay.query("")
        assert replay.query("MEAS?") == "response"


def test_api_rejects_ambiguous_modes(tmp_path: Path) -> None:
    path = tmp_path / "api.jsonl"
    transport = FakeTransport([])
    with pytest.raises(ConfigurationError, match="requires"):
        use_cassette(path, mode="record")
    with pytest.raises(ConfigurationError, match="does not accept"):
        use_cassette(path, mode="replay", transport=transport)
    with pytest.raises(ConfigurationError, match="mode must"):
        use_cassette(path, mode="auto", transport=transport)
    with pytest.raises(ConfigurationError, match="only supported"):
        use_cassette(path, transport=transport, fault_plan=tmp_path / "faults.json")


def test_operations_outside_context_fail_cleanly(tmp_path: Path) -> None:
    path = write_cassette(tmp_path / "state.jsonl", [])
    session = use_cassette(path, mode="replay")
    with pytest.raises(SessionStateError):
        session.query("A?")
    with session:
        pass
    with pytest.raises(SessionStateError):
        session.query("A?")
    with pytest.raises(SessionStateError):
        with session:
            pass
