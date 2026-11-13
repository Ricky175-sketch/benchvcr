"""A deterministic virtual programmable DC power supply."""

from __future__ import annotations

import math

from .errors import DisconnectError, ProtocolError

IDN_RESPONSE = "BenchVCR,VirtualPSU,v0.1,0001"


def _format_number(value: float) -> str:
    return f"{value:.6f}"


class VirtualPowerSupply:
    """Fixed-load text protocol model; no random noise or physical simulation."""

    def __init__(self, *, load_ohms: float = 10.0) -> None:
        if not math.isfinite(load_ohms) or load_ohms <= 0:
            raise ValueError("load_ohms must be finite and positive")
        self.load_ohms = load_ohms
        self.voltage_set = 0.0
        self.current_limit = 0.1
        self.output_enabled = False
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise DisconnectError("virtual power supply is closed")

    def _reset(self) -> None:
        self.voltage_set = 0.0
        self.current_limit = 0.1
        self.output_enabled = False

    def _measurements(self) -> tuple[float, float]:
        if not self.output_enabled:
            return 0.0, 0.0
        voltage = min(self.voltage_set, self.current_limit * self.load_ohms)
        return voltage, voltage / self.load_ohms

    def write(self, command: str) -> None:
        self._check_open()
        parts = command.split()
        if not parts:
            raise ProtocolError("empty command")
        name = parts[0].upper()
        if name.endswith("?"):
            raise ProtocolError(f"query sent through write: {command!r}")

        if name == "*RST" and len(parts) == 1:
            self._reset()
            return
        if name == "VOLT" and len(parts) == 2:
            voltage = self._number(parts[1], 0.0, 30.0, "voltage")
            self.voltage_set = voltage
            return
        if name == "CURR" and len(parts) == 2:
            current = self._number(parts[1], 0.0, 5.0, "current")
            self.current_limit = current
            return
        if name == "OUTP" and len(parts) == 2:
            setting = parts[1].upper()
            if setting not in {"ON", "OFF", "1", "0"}:
                raise ProtocolError(f"invalid output setting: {parts[1]!r}")
            self.output_enabled = setting in {"ON", "1"}
            return
        raise ProtocolError(f"unknown or malformed write command: {command!r}")

    @staticmethod
    def _number(text: str, minimum: float, maximum: float, name: str) -> float:
        try:
            value = float(text)
        except ValueError:
            raise ProtocolError(f"invalid {name}: {text!r}") from None
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ProtocolError(f"{name} out of range: {text!r}")
        return value

    def query(self, command: str) -> str:
        self._check_open()
        if command != command.strip() or len(command.split()) != 1:
            raise ProtocolError(f"malformed query: {command!r}")
        name = command.upper()
        if not name.endswith("?"):
            raise ProtocolError(f"write command sent through query: {command!r}")
        if name == "*IDN?":
            return IDN_RESPONSE
        if name == "VOLT?":
            return _format_number(self.voltage_set)
        if name == "CURR?":
            return _format_number(self.current_limit)
        if name == "OUTP?":
            return "1" if self.output_enabled else "0"
        if name == "MEAS:VOLT?":
            return _format_number(self._measurements()[0])
        if name == "MEAS:CURR?":
            return _format_number(self._measurements()[1])
        raise ProtocolError(f"unknown query: {command!r}")

    def close(self) -> None:
        self._closed = True
