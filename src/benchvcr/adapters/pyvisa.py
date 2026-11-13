"""Thin message-based PyVISA adapter without importing PyVISA."""

from __future__ import annotations

from typing import Any

from ..errors import (
    CommunicationError,
    ProtocolError,
    TransportError,
    TransportTimeoutError,
)

VI_ERROR_TMO = -1073807339


class PyVISAAdapter:
    def __init__(
        self,
        resource: Any,
        *,
        timeout_ms: int | None = None,
        write_termination: str | None = "\n",
        read_termination: str | None = "\n",
        encoding: str | None = "utf-8",
    ) -> None:
        self.resource = resource
        if timeout_ms is not None:
            self.resource.timeout = timeout_ms
        if write_termination is not None:
            self.resource.write_termination = write_termination
        if read_termination is not None:
            self.resource.read_termination = read_termination
        if encoding is not None:
            self.resource.encoding = encoding

    @staticmethod
    def _normalize(error: Exception) -> CommunicationError:
        if isinstance(error, CommunicationError):
            return error
        if (
            isinstance(error, TimeoutError)
            or getattr(error, "status_code", None) == VI_ERROR_TMO
        ):
            return TransportTimeoutError(str(error) or "VISA operation timed out")
        return TransportError(str(error) or "VISA transport failed")

    def write(self, command: str) -> None:
        try:
            self.resource.write(command)
        except Exception as exc:
            error = self._normalize(exc)
            if error is exc:
                raise
            raise error from exc

    def query(self, command: str) -> str:
        try:
            response = self.resource.query(command)
            if not isinstance(response, str):
                raise ProtocolError("VISA query returned a non-text response")
            return response
        except Exception as exc:
            error = self._normalize(exc)
            if error is exc:
                raise
            raise error from exc

    def close(self) -> None:
        try:
            self.resource.close()
        except Exception as exc:
            error = self._normalize(exc)
            if error is exc:
                raise
            raise error from exc
