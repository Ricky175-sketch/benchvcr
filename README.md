# BenchVCR

BenchVCR records, strictly replays, and injects communication faults into
synchronous request–response text protocols used by bench instruments. Cassette
files are human-readable JSONL. The core package uses only the Python standard
library.

Version 0.1 is intentionally small: one connection, one outstanding operation,
and the `write(command)` / `query(command)` operations. It is not a general
instrument driver or a physical simulator.

## Scope and non-goals

Included:

- Atomic cassette recording and ordered, exact replay.
- Stable timeout, disconnect, protocol, and transport errors.
- Deterministic delay, timeout, disconnect, truncation, and response replacement.
- A deterministic virtual programmable power supply for hardware-free tests.
- Thin pyserial and message-based PyVISA adapters.
- A pytest replay fixture and cassette-validation CLI.

Not included: automatic hardware discovery, an `auto` mode, async or concurrent
I/O, multiple responses or unsolicited reports, generic binary streams,
CAN/Modbus/I2C/SPI, AI diagnosis, web services, or real-hardware certification.
The virtual power supply validates protocol and tool behavior only.

## Requirements and installation

The package supports Python 3.10 and later. Python 3.12 is used for the local
development environment. The core has no runtime dependencies.

```bash
python -m pip install -e .
```

For development:

```bash
python -m pip install -e ".[dev]"
pytest -q
```

Optional adapters are installed only when requested:

```bash
python -m pip install -e ".[serial]"
python -m pip install -e ".[pyvisa]"
```

Importing BenchVCR, running its demo, or validating a cassette does not import
pyserial or PyVISA.

A project-isolated uv setup can be reproduced without changing shell startup
files:

```bash
export UV_CACHE_DIR="$PWD/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.python"
export UV_PYTHON_BIN_DIR="$PWD/.tools/python-bin"
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

All of those directories are ignored by git. Unset the variables if you do not
want project-local uv storage in a different shell.

## Quick start

### Record

Record mode always requires an explicitly supplied transport. BenchVCR does not
open hardware and does not close the caller's transport.

```python
from benchvcr import use_cassette
from benchvcr.virtual import VirtualPowerSupply

supply = VirtualPowerSupply()
try:
    with use_cassette("cassettes/basic.jsonl", mode="record", transport=supply) as io:
        assert io.query("*IDN?").startswith("BenchVCR,")
        io.write("VOLT 5")
        io.write("OUTP ON")
        assert io.query("MEAS:VOLT?") == "5.000000"
finally:
    supply.close()  # The creator retains resource ownership.
```

The destination's parent directory must exist. Recording refuses to replace an
existing file unless `overwrite=True` is explicit. Data is appended to a temporary
file in the same directory and flushed after every exchange. Normal context exit
closes it and atomically replaces the destination.

If the test body raises, the partial file is discarded and the original exception
is preserved. To retain a recorded hardware error, catch it inside the context and
finish the body normally:

```python
from benchvcr import CommunicationError, use_cassette

with use_cassette("errors.jsonl", transport=supply) as io:
    try:
        io.query("MEAS:VOLT?")
    except CommunicationError:
        pass  # The failed exchange is now part of the cassette.
```

### Replay

Replay never accepts a transport and never accesses hardware:

```python
from benchvcr import use_cassette

with use_cassette("cassettes/basic.jsonl", mode="replay") as io:
    identify = io.query("*IDN?")
    io.write("VOLT 5")
    io.write("OUTP ON")
    voltage = io.query("MEAS:VOLT?")
```

The `kind` and original `command` string must match the next exchange exactly.
A mismatch raises `CassetteMismatchError` and does not consume that exchange, so
a caller can inspect the error and retry. A matched exchange is consumed before
its recorded or injected result is returned/raised; callers may catch a
communication error and continue.

Normal exit with exchanges left raises `UnplayedInteractionsError`. If the body
already raised, BenchVCR does not add a teardown error that could hide it. Replay
never modifies the cassette. Recorded times are metadata: they are not matched
and normal replay does not sleep for the recorded duration.

## Cassette JSONL v1

The first line is a header; every later line is one exchange. Exchange `seq`
values start at zero.

```jsonl
{"format":"benchvcr","schema_version":1,"protocol":"text","library_version":"0.1.0","created_at":"2026-01-02T03:04:05Z"}
{"seq":0,"kind":"query","command":"*IDN?","at_ms":0.0,"duration_ms":0.12,"ok":true,"response":"example","error":null}
```

`created_at` is UTC wall-clock time. `at_ms` is relative to a monotonic clock and
`duration_ms` is the measured operation duration. Invariants include:

- contiguous zero-based sequence numbers;
- finite, non-negative times and non-decreasing `at_ms`;
- non-empty commands without CR/LF;
- `kind` of `write` or `query`;
- successful writes have `response: null`;
- successful queries have a string response (the empty string is valid);
- failed exchanges have `response: null` and a stable error object;
- error types are `timeout`, `disconnect`, `protocol`, or `transport`.

Invalid UTF-8/JSON, duplicate headers, unsupported versions, and invalid field
combinations produce a path, line number, and reason. Unknown fields and
non-standard JSON numbers are rejected.

Validate from Python or the CLI:

```python
from benchvcr import validate_cassette

cassette = validate_cassette("cassettes/basic.jsonl")
print(len(cassette.exchanges))
```

```bash
benchvcr cassette validate cassettes/basic.jsonl
python -m benchvcr cassette validate cassettes/basic.jsonl
```

## Fault plans

Faults apply only during replay. A plan has an integer seed and an ordered rule
array. `at` is the zero-based cassette sequence number, not a timestamp.
`match.kind` and `match.command` are optional exact filters. `probability` is
optional and defaults to 1.

```json
{
  "format": "benchvcr-fault-plan",
  "schema_version": 1,
  "seed": 42,
  "rules": [
    {
      "at": 3,
      "match": {"kind": "query", "command": "MEAS:VOLT?"},
      "operation": "delay",
      "delay_ms": 25,
      "probability": 1.0
    }
  ]
}
```

```python
from benchvcr import load_fault_plan, use_cassette

plan = load_fault_plan("faults/delay.json")
with use_cassette("cassettes/basic.jsonl", mode="replay", fault_plan=plan) as io:
    # Issue exactly the recorded calls here.
    ...
```

Operations:

| `operation` | Parameters | Behavior |
| --- | --- | --- |
| `delay` | non-negative `delay_ms` | Sleep through an injectable sleeper, then return/raise the original result. |
| `timeout` | none | Raise `TransportTimeoutError` immediately. |
| `disconnect` | none | Raise `DisconnectError` for this exchange only; no permanent-down model. |
| `truncate` | non-negative integer `length` | Truncate a successful query by Python text characters. |
| `response_replace` | string `response` | Replace a successful query response; an empty string is allowed. |

Rules are examined in array order. Only the first rule that actually triggers is
applied, and at most one fault affects an exchange. Response-modifying rules are
ineligible for writes and failed queries, so evaluation can continue to a later
eligible rule. Malformed plans raise `ConfigurationError`; they are not disguised
as hardware failures.

For probability `p`, BenchVCR uses the first eight bytes of
`SHA-256("benchvcr:v1:{seed}:{seq}:{rule_index}")` as an unsigned big-endian
integer divided by `2**64`. The rule triggers when the sample is less than `p`.
This stateless algorithm is stable across processes and platforms; fixed test
vectors protect it.

## Hardware-free demo

```bash
benchvcr demo --output-dir demo-output --seed 42
# Equivalent:
python -m benchvcr demo --output-dir demo-output --seed 42
```

The demo records the virtual power supply, performs a clean replay, performs five
separate fault replays, and verifies that the cassette SHA-256 is unchanged. It
prints one `PASS` line per stage and writes the cassette plus five fault plans.
It replaces its own cassette on repeated runs. No physical simulation or real
instrument compatibility is claimed.

The virtual device supports `*IDN?`, `*RST`, `VOLT`/`VOLT?`, `CURR`/`CURR?`,
`OUTP`/`OUTP?`, `MEAS:VOLT?`, and `MEAS:CURR?`. Its fixed resistive-load model is
`V = min(VOLT, CURR * load_ohms)` while output is on, and `I = V / load_ohms`.
There is no noise or random state. Invalid commands do not mutate settings.

## Optional adapters

### pyserial

```python
import serial
from benchvcr.adapters import SerialTextAdapter

connection = serial.Serial("/dev/ttyUSB0", baudrate=9600, timeout=0.2)
io = SerialTextAdapter(
    connection,
    encoding="utf-8",
    write_termination="\n",
    read_termination="\n",
)
```

The adapter appends the write terminator, reads through the read terminator, and
returns the response without that terminator. It does not call `.strip()`;
other whitespace remains intact. Empty reads become timeout errors, including a
distinct partial-response timeout. Short writes, decoding failures, and
underlying exceptions are normalized. A read containing bytes after a complete
response is rejected rather than silently losing data.

### PyVISA

```python
import pyvisa
from benchvcr.adapters import PyVISAAdapter

manager = pyvisa.ResourceManager()
resource = manager.open_resource("TCPIP::192.0.2.10::INSTR")
io = PyVISAAdapter(resource, timeout_ms=500)
```

The wrapper configures timeout, encoding, and message termination on the supplied
message-based text resource. It maps the explicit VISA `VI_ERROR_TMO` status to
`TransportTimeoutError` and other failures to stable communication errors.
Applications remain responsible for closing resources and resource managers.

Adapter tests use fakes. They do not assert compatibility with any physical
serial device or VISA implementation.

## pytest fixture

When the package is installed, its `pytest11` entry point supplies
`benchvcr_replay`. The factory resolves a relative name in `cassettes/` beside the
current test file and returns a context manager. Enter it explicitly:

```python
def test_identity(benchvcr_replay):
    with benchvcr_replay("identity.jsonl") as io:
        assert io.query("*IDN?") == "expected identity"
```

There is deliberately no fixture-finalizer consumption check, no global
`--record` switch, no automatic naming, and no implicit hardware construction.
Use the public `use_cassette(..., mode="record", transport=...)` API to create
cassettes explicitly.

## Exceptions

- `ConfigurationError`: invalid API mode/arguments or fault-plan structure.
- `CassetteValidationError`: malformed cassette, with line and reason.
- `CassetteMismatchError`: strict replay mismatch, with expected/actual values.
- `UnplayedInteractionsError`: normal replay exit with remaining exchanges.
- `CommunicationError`: base for `TransportTimeoutError`, `DisconnectError`,
  `ProtocolError`, and `TransportError`.
- `SessionStateError`: operations outside an active context.

Expected CLI user errors produce a concise stderr message and exit code 2 rather
than a long traceback.

## Development checks

```bash
pytest -q
coverage run --source=src/benchvcr --branch -m pytest -q
coverage report -m
ruff check .
ruff format --check .
mypy src/benchvcr
python -m build
python -m pip check
```

The GitHub Actions configuration covers Ubuntu, Windows, and macOS on Python
3.10 and 3.13, with an additional Ubuntu quality job. Its presence is not a claim
that remote checks or real-hardware tests have run.

## License

MIT. See `LICENSE`.
