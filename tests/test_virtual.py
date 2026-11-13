from __future__ import annotations

import pytest

from benchvcr import DisconnectError, ProtocolError
from benchvcr.virtual import IDN_RESPONSE, VirtualPowerSupply


def test_identity_and_reset() -> None:
    supply = VirtualPowerSupply()
    assert supply.query("*IDN?") == IDN_RESPONSE
    supply.write("VOLT 12.5")
    supply.write("CURR 0.5")
    supply.write("OUTP ON")
    supply.write("*RST")
    assert supply.query("VOLT?") == "0.000000"
    assert supply.query("CURR?") == "0.100000"
    assert supply.query("OUTP?") == "0"


def test_voltage_and_current_queries() -> None:
    supply = VirtualPowerSupply()
    supply.write("VOLT 3.3")
    supply.write("CURR 1.25")
    supply.write("OUTP 1")
    assert supply.query("VOLT?") == "3.300000"
    assert supply.query("CURR?") == "1.250000"
    assert supply.query("OUTP?") == "1"


def test_fixed_load_measurement_model_is_deterministic() -> None:
    supply = VirtualPowerSupply(load_ohms=10)
    supply.write("VOLT 12")
    supply.write("CURR 2")
    supply.write("OUTP ON")
    assert supply.query("MEAS:VOLT?") == "12.000000"
    assert supply.query("MEAS:CURR?") == "1.200000"
    assert supply.query("MEAS:VOLT?") == "12.000000"

    supply.write("CURR 0.5")
    assert supply.query("MEAS:VOLT?") == "5.000000"
    assert supply.query("MEAS:CURR?") == "0.500000"
    supply.write("OUTP OFF")
    assert supply.query("MEAS:VOLT?") == "0.000000"
    assert supply.query("MEAS:CURR?") == "0.000000"


@pytest.mark.parametrize(
    "command",
    ["VOLT nope", "VOLT -1", "VOLT 31", "CURR NaN", "CURR 6", "OUTP MAYBE"],
)
def test_invalid_setting_does_not_change_state(command: str) -> None:
    supply = VirtualPowerSupply()
    before = (supply.voltage_set, supply.current_limit, supply.output_enabled)
    with pytest.raises(ProtocolError):
        supply.write(command)
    assert (supply.voltage_set, supply.current_limit, supply.output_enabled) == before


@pytest.mark.parametrize("command", ["", "BOGUS", "VOLT", "VOLT 1 2", "*RST now"])
def test_malformed_write_does_not_change_state(command: str) -> None:
    supply = VirtualPowerSupply()
    supply.write("VOLT 2")
    with pytest.raises(ProtocolError):
        supply.write(command)
    assert supply.voltage_set == 2


def test_write_and_query_cannot_be_interchanged() -> None:
    supply = VirtualPowerSupply()
    with pytest.raises(ProtocolError):
        supply.write("VOLT?")
    with pytest.raises(ProtocolError):
        supply.query("VOLT 2")
    assert supply.voltage_set == 0
    with pytest.raises(ProtocolError):
        supply.query("UNKNOWN?")


def test_close_is_explicit_and_terminal() -> None:
    supply = VirtualPowerSupply()
    supply.close()
    supply.close()
    with pytest.raises(DisconnectError):
        supply.query("*IDN?")
    with pytest.raises(DisconnectError):
        supply.write("*RST")


def test_invalid_load_is_rejected() -> None:
    with pytest.raises(ValueError):
        VirtualPowerSupply(load_ohms=0)
    with pytest.raises(ValueError):
        VirtualPowerSupply(load_ohms=float("inf"))
