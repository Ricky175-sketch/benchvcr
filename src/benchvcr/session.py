"""Atomic recording and strict sequential replay state machines."""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import TextIO

from . import __version__
from .cassette import (
    CASSETTE_FORMAT,
    PROTOCOL,
    SCHEMA_VERSION,
    Cassette,
    Exchange,
    Kind,
    PathLike,
    json_line,
    validate_cassette,
)
from .errors import (
    CassetteMismatchError,
    CommunicationError,
    ConfigurationError,
    ProtocolError,
    SessionStateError,
    TransportError,
    TransportTimeoutError,
    UnplayedInteractionsError,
)
from .faults import FaultPlan, apply_fault, load_fault_plan
from .transport import TextTransport

_ExceptionType = type[BaseException] | None


def _validate_command(command: str) -> None:
    if (
        not isinstance(command, str)
        or not command
        or "\n" in command
        or "\r" in command
    ):
        raise ValueError("command must be a non-empty string without newlines")


def _normalize_error(error: BaseException) -> CommunicationError:
    if isinstance(error, CommunicationError):
        return error
    if isinstance(error, TimeoutError):
        return TransportTimeoutError(str(error) or "transport timed out")
    if isinstance(error, OSError):
        return TransportError(str(error) or "transport failed")
    raise TypeError(f"unsupported communication error: {error!r}")


class _Session:
    """A close-noop transport facade; context exit controls only the cassette."""

    _active = False

    def close(self) -> None:
        """Do not close caller-owned hardware resources."""
        return None


class RecordSession(_Session):
    def __init__(
        self,
        path: PathLike,
        transport: TextTransport,
        *,
        overwrite: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = Path(path)
        self.transport = transport
        self.overwrite = overwrite
        self._clock = clock
        self._file: TextIO | None = None
        self._temp_path: Path | None = None
        self._seq = 0
        self._started = 0.0

    def __enter__(self) -> RecordSession:
        if self._active or self._temp_path is not None:
            raise SessionStateError("record session cannot be entered twice")
        if self.path.exists() and not self.overwrite:
            raise ConfigurationError(
                f"cassette already exists: {self.path}; pass overwrite=True to replace"
            )
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        self._temp_path = Path(temp_name)
        try:
            self._file = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
            header = {
                "format": CASSETTE_FORMAT,
                "schema_version": SCHEMA_VERSION,
                "protocol": PROTOCOL,
                "library_version": __version__,
                "created_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            }
            self._file.write(json_line(header))
            self._file.flush()
            self._started = self._clock()
            self._active = True
        except BaseException:
            if self._file is None:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            self._discard(suppress_errors=True)
            raise
        return self

    def _append(
        self,
        kind: Kind,
        command: str,
        at_ms: float,
        started: float,
        *,
        response: str | None,
        error: CommunicationError | None,
    ) -> None:
        if self._file is None:
            raise SessionStateError("record session is not active")
        exchange = Exchange(
            seq=self._seq,
            kind=kind,
            command=command,
            at_ms=round(max(0.0, at_ms), 6),
            duration_ms=round(max(0.0, (self._clock() - started) * 1000), 6),
            ok=error is None,
            response=response,
            error=error,
        )
        self._file.write(json_line(exchange.as_dict()))
        self._file.flush()
        self._seq += 1

    def _run(self, kind: Kind, command: str) -> str | None:
        if not self._active:
            raise SessionStateError("record session is not active")
        _validate_command(command)
        started = self._clock()
        at_ms = (started - self._started) * 1000
        try:
            if kind == "write":
                self.transport.write(command)
                response = None
            else:
                response = self.transport.query(command)
                if not isinstance(response, str):
                    raise ProtocolError("transport query returned a non-text response")
        except (CommunicationError, TimeoutError, OSError) as caught:
            error = _normalize_error(caught)
            self._append(
                kind,
                command,
                at_ms,
                started,
                response=None,
                error=error,
            )
            if error is caught:
                raise
            raise error from caught
        self._append(kind, command, at_ms, started, response=response, error=None)
        return response

    def write(self, command: str) -> None:
        self._run("write", command)

    def query(self, command: str) -> str:
        response = self._run("query", command)
        assert response is not None
        return response

    def _discard(self, *, suppress_errors: bool) -> None:
        try:
            if self._file is not None:
                self._file.close()
            if self._temp_path is not None:
                self._temp_path.unlink(missing_ok=True)
        except Exception:
            if not suppress_errors:
                raise
        finally:
            self._file = None
            self._active = False

    def __exit__(
        self,
        exc_type: _ExceptionType,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self._discard(suppress_errors=True)
            return None
        try:
            if self._file is None or self._temp_path is None:
                raise SessionStateError("record session is not active")
            self._file.close()
            self._file = None
            if self.path.exists() and not self.overwrite:
                raise ConfigurationError(
                    f"cassette appeared during recording: {self.path}"
                )
            os.replace(self._temp_path, self.path)
            self._active = False
        except BaseException:
            self._discard(suppress_errors=True)
            raise
        return None


class ReplaySession(_Session):
    def __init__(
        self,
        path: PathLike,
        *,
        fault_plan: PathLike | FaultPlan | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.path = Path(path)
        self._fault_plan_source = fault_plan
        self._sleep = sleep
        self._cassette: Cassette | None = None
        self._fault_plan: FaultPlan | None = None
        self._index = 0

    def __enter__(self) -> ReplaySession:
        if self._active or self._cassette is not None:
            raise SessionStateError("replay session cannot be entered twice")
        cassette = validate_cassette(self.path)
        source = self._fault_plan_source
        fault_plan = (
            source
            if isinstance(source, FaultPlan) or source is None
            else load_fault_plan(source)
        )
        self._cassette = cassette
        self._fault_plan = fault_plan
        self._active = True
        return self

    def _run(self, kind: Kind, command: str) -> str | None:
        if not self._active or self._cassette is None:
            raise SessionStateError("replay session is not active")
        _validate_command(command)
        exchanges = self._cassette.exchanges
        if self._index >= len(exchanges):
            raise CassetteMismatchError(self._index, None, None, kind, command)
        exchange = exchanges[self._index]
        if exchange.kind != kind or exchange.command != command:
            raise CassetteMismatchError(
                exchange.seq,
                exchange.kind,
                exchange.command,
                kind,
                command,
            )

        self._index += 1
        response = exchange.response
        if self._fault_plan is not None:
            rule = self._fault_plan.rule_for(exchange)
            if rule is not None:
                response = apply_fault(rule, exchange, self._sleep)
        if exchange.error is not None:
            raise exchange.error
        return response

    def write(self, command: str) -> None:
        self._run("write", command)

    def query(self, command: str) -> str:
        response = self._run("query", command)
        assert response is not None
        return response

    def __exit__(
        self,
        exc_type: _ExceptionType,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._active = False
        if exc_type is None and self._cassette is not None:
            remaining = len(self._cassette.exchanges) - self._index
            if remaining:
                raise UnplayedInteractionsError(remaining, self._index)
        return None


def use_cassette(
    path: PathLike,
    mode: str = "record",
    transport: TextTransport | None = None,
    fault_plan: PathLike | FaultPlan | None = None,
    overwrite: bool = False,
) -> RecordSession | ReplaySession:
    """Create a record or replay session for use in a ``with`` statement."""

    if mode == "record":
        if transport is None:
            raise ConfigurationError("record mode requires an explicit transport")
        if fault_plan is not None:
            raise ConfigurationError("fault injection is only supported during replay")
        return RecordSession(path, transport, overwrite=overwrite)
    if mode == "replay":
        if transport is not None:
            raise ConfigurationError("replay mode does not accept a transport")
        return ReplaySession(path, fault_plan=fault_plan)
    raise ConfigurationError("mode must be 'record' or 'replay'")
