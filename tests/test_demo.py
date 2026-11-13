from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

from benchvcr import validate_cassette
from benchvcr.demo import OPERATIONS, run_demo


def test_demo_passes_all_stages_without_optional_drivers(tmp_path: Path) -> None:
    stream = io.StringIO()
    result = run_demo(tmp_path / "artifacts", seed=42, stream=stream)

    assert result.checks == (
        "record",
        "clean replay",
        "fault: delay",
        "fault: timeout",
        "fault: disconnect",
        "fault: truncate",
        "fault: response_replace",
        "cassette hash unchanged",
    )
    assert stream.getvalue().count("PASS") == 8
    assert len(validate_cassette(result.cassette_path).exchanges) == len(OPERATIONS)
    assert (
        hashlib.sha256(result.cassette_path.read_bytes()).hexdigest() == result.sha256
    )
    assert "serial" not in sys.modules
    assert "pyvisa" not in sys.modules
    for name in ("delay", "timeout", "disconnect", "truncate", "response_replace"):
        plan = json.loads(
            (result.cassette_path.parent / f"fault-{name}.json").read_text()
        )
        assert plan["seed"] == 42


def test_demo_can_be_repeated_in_same_output_directory(tmp_path: Path) -> None:
    first = run_demo(tmp_path, seed=42, stream=io.StringIO())
    second = run_demo(tmp_path, seed=42, stream=io.StringIO())
    assert first.checks == second.checks
    assert second.cassette_path.exists()
