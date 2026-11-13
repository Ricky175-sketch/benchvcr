"""Thin pyserial-compatible adapter; pyserial itself is not imported here."""

from __future__ import annotations

from typing import Any

from ..errors import (
    CommunicationError,
    ProtocolError,
    TransportError,
    TransportTimeoutError,
)


class SerialTextAdapter:
    def __init__(
        self,
        connection: Any,
        *,
        encoding: str = "utf-8",
        write_termination: str = "\n",
        read_termination: str = "\n",
        timeout: float | None = None,
        read_chunk_size: int = 1,
    ) -> None:
        if not read_termination:
            raise ValueError("read_termination must not be empty")
        if read_chunk_size <= 0:
            raise ValueError("read_chunk_size must be positive")
        self.connection = connection
        self.encoding = encoding
        self.write_termination = write_termination.encode(encoding)
        self.read_termination = read_termination.encode(encoding)
        self.read_chunk_size = read_chunk_size
        if timeout is not None:
            self.connection.timeout = timeout

    @staticmethod
    def _normalize(error: Exception) -> CommunicationError:
        if isinstance(error, CommunicationError):
            return error
        if isinstance(error, TimeoutError):
            return TransportTimeoutError(str(error) or "serial operation timed out")
        return TransportError(str(error) or "serial transport failed")

    def write(self, command: str) -> None:
        try:
            payload = command.encode(self.encoding) + self.write_termination
            written = self.connection.write(payload)
            if written is not None and written != len(payload):
                raise TransportError(
                    f"serial short write: {written} of {len(payload)} bytes"
                )
        except Exception as exc:
            error = self._normalize(exc)
            if error is exc:
                raise
            raise error from exc

    def query(self, command: str) -> str:
        self.write(command)
        buffer = bytearray()
        try:
            while True:
                chunk = self.connection.read(self.read_chunk_size)
                if not chunk:
                    if buffer:
                        raise TransportTimeoutError(
                            "serial read timed out after a partial response"
                        )
                    raise TransportTimeoutError("serial read timed out")
                if not isinstance(chunk, (bytes, bytearray)):
                    raise ProtocolError("serial read returned non-bytes data")
                buffer.extend(chunk)
                end = buffer.find(self.read_termination)
                if end >= 0:
                    response_end = end + len(self.read_termination)
                    if response_end != len(buffer):
                        raise ProtocolError("bytes received after read termination")
                    try:
                        return bytes(buffer[:end]).decode(self.encoding)
                    except UnicodeDecodeError as exc:
                        raise ProtocolError(
                            f"serial response is not valid {self.encoding}"
                        ) from exc
        except Exception as exc:
            error = self._normalize(exc)
            if error is exc:
                raise
            raise error from exc

    def close(self) -> None:
        try:
            self.connection.close()
        except Exception as exc:
            error = self._normalize(exc)
            if error is exc:
                raise
            raise error from exc
