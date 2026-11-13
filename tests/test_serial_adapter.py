from __future__ import annotations

import pytest

from benchvcr import ProtocolError, TransportError, TransportTimeoutError
from benchvcr.adapters import SerialTextAdapter


class FakeSerial:
    def __init__(self, reads: list[object] | None = None) -> None:
        self.reads = list(reads or [])
        self.writes: list[bytes] = []
        self.timeout: float | None = None
        self.closed = False
        self.write_result: int | None = None
        self.write_error: Exception | None = None

    def write(self, payload: bytes) -> int:
        if self.write_error is not None:
            raise self.write_error
        self.writes.append(payload)
        return len(payload) if self.write_result is None else self.write_result

    def read(self, size: int) -> bytes:
        assert size > 0
        if not self.reads:
            return b""
        value = self.reads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value  # type: ignore[return-value]

    def close(self) -> None:
        self.closed = True


def test_write_encodes_and_appends_exact_termination() -> None:
    serial = FakeSerial()
    adapter = SerialTextAdapter(serial, timeout=0.25, write_termination="\r\n")
    adapter.write("VOLT 1")
    assert serial.writes == [b"VOLT 1\r\n"]
    assert serial.timeout == 0.25


def test_query_reads_to_termination_without_stripping() -> None:
    serial = FakeSerial([b" ", b"1", b".", b"0", b" ", b"\r", b"\n"])
    adapter = SerialTextAdapter(serial)
    assert adapter.query("MEAS?") == " 1.0 \r"
    assert serial.writes == [b"MEAS?\n"]


def test_multicharacter_termination_and_chunked_read() -> None:
    serial = FakeSerial([b"ab<", b"END>"])
    adapter = SerialTextAdapter(serial, read_termination="<END>", read_chunk_size=4)
    assert adapter.query("A?") == "ab"


def test_empty_read_is_timeout() -> None:
    adapter = SerialTextAdapter(FakeSerial([]))
    with pytest.raises(TransportTimeoutError, match="timed out"):
        adapter.query("A?")


def test_partial_read_timeout_is_distinct_and_preserves_no_response() -> None:
    adapter = SerialTextAdapter(FakeSerial([b"partial", b""]))
    with pytest.raises(TransportTimeoutError, match="partial response"):
        adapter.query("A?")


def test_short_write_is_transport_error() -> None:
    serial = FakeSerial()
    serial.write_result = 1
    adapter = SerialTextAdapter(serial)
    with pytest.raises(TransportError, match="short write"):
        adapter.write("ABC")


def test_underlying_write_error_is_normalized() -> None:
    serial = FakeSerial()
    serial.write_error = OSError("disconnected")
    adapter = SerialTextAdapter(serial)
    with pytest.raises(TransportError, match="disconnected"):
        adapter.write("A")


def test_underlying_read_errors_are_normalized() -> None:
    adapter = SerialTextAdapter(FakeSerial([TimeoutError("late")]))
    with pytest.raises(TransportTimeoutError, match="late"):
        adapter.query("A?")
    adapter = SerialTextAdapter(FakeSerial([OSError("gone")]))
    with pytest.raises(TransportError, match="gone"):
        adapter.query("A?")


def test_invalid_response_type_and_encoding_are_protocol_errors() -> None:
    adapter = SerialTextAdapter(FakeSerial(["not bytes"]))
    with pytest.raises(ProtocolError, match="non-bytes"):
        adapter.query("A?")
    adapter = SerialTextAdapter(FakeSerial([b"\xff\n"]))
    with pytest.raises(ProtocolError, match="not valid utf-8"):
        adapter.query("A?")


def test_data_after_termination_is_not_silently_discarded() -> None:
    adapter = SerialTextAdapter(FakeSerial([b"first\nextra"]), read_chunk_size=16)
    with pytest.raises(ProtocolError, match="after read termination"):
        adapter.query("A?")


def test_close_delegates_and_normalizes() -> None:
    serial = FakeSerial()
    adapter = SerialTextAdapter(serial)
    adapter.close()
    assert serial.closed


def test_adapter_configuration_is_validated() -> None:
    with pytest.raises(ValueError, match="read_termination"):
        SerialTextAdapter(FakeSerial(), read_termination="")
    with pytest.raises(ValueError, match="read_chunk_size"):
        SerialTextAdapter(FakeSerial(), read_chunk_size=0)
