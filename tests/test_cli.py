from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fakes import exchange, write_cassette

from benchvcr.cli import main


def test_validate_command_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_cassette(tmp_path / "valid.jsonl", [exchange(0)])
    assert main(["cassette", "validate", str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"OK {path} (1 exchanges)\n"
    assert captured.err == ""


def test_validate_user_error_is_concise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"format":\n', encoding="utf-8")
    assert main(["cassette", "validate", str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "benchvcr: error:" in captured.err
    assert f"{path}:1" in captured.err
    assert "Traceback" not in captured.err


def test_validate_missing_file_has_stable_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.jsonl"
    assert main(["cassette", "validate", str(missing)]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("benchvcr: error:")
    assert "Traceback" not in captured.err


def test_demo_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "demo"
    assert main(["demo", "--output-dir", str(output), "--seed", "42"]) == 0
    captured = capsys.readouterr()
    assert captured.out.count("PASS") == 8
    assert captured.err == ""


def test_python_dash_m_entrypoint(tmp_path: Path) -> None:
    environment = os.environ.copy()
    source = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchvcr",
            "demo",
            "--output-dir",
            str(tmp_path / "module-demo"),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("PASS") == 8
    assert "Traceback" not in result.stderr


def test_argparse_user_error_has_no_traceback() -> None:
    environment = os.environ.copy()
    source = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "benchvcr", "unknown"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert "Traceback" not in result.stderr
