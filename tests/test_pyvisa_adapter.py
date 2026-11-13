from __future__ import annotations

import pytest

from benchvcr import ProtocolError, TransportError, TransportTimeoutError
from benchvcr.adapters import PyVISAAdapter
from benchvcr.adapters.pyvisa import VI_ERROR_TMO


class FakeVisaError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(message)


class FakeResource:
    def __init__(self) -> None:
        self.timeout: int | None = None
        self.write_termination: str | None = None
        self.read_termination: str | None = None
        self.encoding: str | None = None
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.response: object = "response"
        self.error: Exception | None = None
        self.closed = False

    def write(self, command: str) -> None:
        self.writes.append(command)
        if self.error is not None:
            raise self.error

    def query(self, command: str) -> object:
        self.queries.append(command)
        if self.error is not None:
            raise self.error
        return self.response

    def close(self) -> None:
        self.closed = True
        if self.error is not None:
            raise self.error


def test_resource_configuration_and_text_round_trip() -> None:
    resource = FakeResource()
    resource.response = " 1.0 \r"
    adapter = PyVISAAdapter(resource, timeout_ms=250)
    assert resource.timeout == 250
    assert resource.write_termination == "\n"
    assert resource.read_termination == "\n"
    assert resource.encoding == "utf-8"
    adapter.write("VOLT 1")
    assert adapter.query("MEAS?") == " 1.0 \r"
    assert resource.writes == ["VOLT 1"]
    assert resource.queries == ["MEAS?"]


def test_optional_resource_settings_can_be_left_untouched() -> None:
    resource = FakeResource()
    PyVISAAdapter(
        resource,
        write_termination=None,
        read_termination=None,
        encoding=None,
    )
    assert resource.write_termination is None
    assert resource.read_termination is None
    assert resource.encoding is None


def test_explicit_visa_timeout_status_is_mapped() -> None:
    resource = FakeResource()
    resource.error = FakeVisaError("VISA timeout", VI_ERROR_TMO)
    adapter = PyVISAAdapter(resource)
    with pytest.raises(TransportTimeoutError, match="VISA timeout"):
        adapter.query("A?")
    with pytest.raises(TransportTimeoutError):
        adapter.write("A")


def test_other_visa_errors_are_transport_errors() -> None:
    resource = FakeResource()
    resource.error = FakeVisaError("VISA disconnected", -1073800000)
    adapter = PyVISAAdapter(resource)
    with pytest.raises(TransportError, match="VISA disconnected"):
        adapter.query("A?")


def test_builtin_timeout_is_mapped() -> None:
    resource = FakeResource()
    resource.error = TimeoutError("late")
    with pytest.raises(TransportTimeoutError, match="late"):
        PyVISAAdapter(resource).query("A?")


def test_non_text_response_is_protocol_error() -> None:
    resource = FakeResource()
    resource.response = b"bytes"
    with pytest.raises(ProtocolError, match="non-text"):
        PyVISAAdapter(resource).query("A?")


def test_close_delegates_and_normalizes() -> None:
    resource = FakeResource()
    PyVISAAdapter(resource).close()
    assert resource.closed
    resource = FakeResource()
    resource.error = OSError("close failed")
    with pytest.raises(TransportError, match="close failed"):
        PyVISAAdapter(resource).close()
