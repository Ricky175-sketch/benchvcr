from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import cassette_text, exchange, header, write_cassette

from benchvcr import CassetteValidationError, TransportTimeoutError, validate_cassette


def test_valid_cassette_preserves_empty_response_and_error(tmp_path: Path) -> None:
    path = write_cassette(
        tmp_path / "valid.jsonl",
        [
            exchange(0, command="EMPTY?", response=""),
            exchange(1, kind="write", command="RST", at_ms=1),
            exchange(
                2,
                command="LATE?",
                at_ms=1,
                ok=False,
                error={"type": "timeout", "message": "too slow"},
            ),
        ],
    )

    cassette = validate_cassette(path)

    assert cassette.header.library_version == "0.1.0"
    assert cassette.exchanges[0].response == ""
    assert cassette.exchanges[1].response is None
    assert isinstance(cassette.exchanges[2].error, TransportTimeoutError)
    assert str(cassette.exchanges[2].error) == "too slow"


def test_header_only_cassette_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text(cassette_text([]), encoding="utf-8")
    assert validate_cassette(path).exchanges == ()


@pytest.mark.parametrize(
    ("contents", "line", "reason"),
    [
        ("", 1, "empty cassette"),
        ("\n", 1, "blank lines"),
        ("not-json\n", 1, "invalid JSON"),
        ("[]\n", 1, "invalid JSON"),
        (cassette_text([]) + "\n", 2, "blank lines"),
        (cassette_text([]) + "{bad}\n", 2, "invalid JSON"),
    ],
)
def test_bad_document_shape(
    tmp_path: Path, contents: str, line: int, reason: str
) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(CassetteValidationError) as caught:
        validate_cassette(path)
    assert caught.value.line == line
    assert reason in caught.value.reason


def test_invalid_utf8_reports_physical_line(tmp_path: Path) -> None:
    path = tmp_path / "utf8.jsonl"
    path.write_bytes(cassette_text([]).encode() + b'{"seq":"\xff"}\n')
    with pytest.raises(CassetteValidationError) as caught:
        validate_cassette(path)
    assert caught.value.line == 2
    assert "invalid UTF-8" in caught.value.reason


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-key.jsonl"
    path.write_text('{"format":"benchvcr","format":"benchvcr"}\n', encoding="utf-8")
    with pytest.raises(CassetteValidationError, match="duplicate JSON key"):
        validate_cassette(path)


def test_duplicate_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-header.jsonl"
    path.write_text(cassette_text([]) + json.dumps(header()) + "\n", encoding="utf-8")
    with pytest.raises(CassetteValidationError) as caught:
        validate_cassette(path)
    assert caught.value.line == 2
    assert "duplicate header" in caught.value.reason


@pytest.mark.parametrize(
    ("header_value", "reason"),
    [
        (header(format="other"), "unsupported cassette format"),
        (header(schema_version=2), "unsupported schema_version"),
        (header(schema_version=True), "unsupported schema_version"),
        (header(protocol="binary"), "unsupported protocol"),
        (header(library_version=""), "library_version"),
        (header(created_at="yesterday"), "created_at"),
        (header(created_at="2026-01-02T03:04:05+01:00"), "must be UTC"),
        (header(extra=True), "unknown header"),
    ],
)
def test_bad_headers(
    tmp_path: Path, header_value: dict[str, object], reason: str
) -> None:
    path = tmp_path / "header.jsonl"
    path.write_text(cassette_text([], header_value), encoding="utf-8")
    with pytest.raises(CassetteValidationError, match=reason):
        validate_cassette(path)


def test_missing_header_field(tmp_path: Path) -> None:
    value = header()
    del value["protocol"]
    path = tmp_path / "missing.jsonl"
    path.write_text(cassette_text([], value), encoding="utf-8")
    with pytest.raises(CassetteValidationError, match="missing header"):
        validate_cassette(path)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (exchange(1), "non-contiguous seq"),
        (exchange(-1), "seq must be a non-negative integer"),
        (exchange(True), "seq must be a non-negative integer"),
        (exchange(0, kind="read"), "kind must"),
        (exchange(0, command=""), "command must"),
        (exchange(0, command="A\nB"), "command must"),
        (exchange(0, at_ms=-0.1), "at_ms"),
        (exchange(0, at_ms=10**1000), "at_ms"),
        (exchange(0, duration_ms=-1), "duration_ms"),
        (exchange(0, response=1), "response must be a string"),
        (exchange(0, ok=1), "ok must be a boolean"),
        (exchange(0, error={"type": "timeout", "message": "x"}), "null error"),
        (exchange(0, ok=False), "must contain an error"),
        (
            exchange(0, ok=False, error={"type": "other", "message": "x"}),
            "unsupported error type",
        ),
        (
            exchange(0, ok=False, error={"type": [], "message": "x"}),
            "unsupported error type",
        ),
        (
            exchange(0, ok=False, error={"type": "timeout", "message": ""}),
            "error message",
        ),
        (exchange(0, extra="no"), "unknown exchange"),
    ],
)
def test_bad_exchanges(tmp_path: Path, value: dict[str, object], reason: str) -> None:
    path = tmp_path / "exchange.jsonl"
    path.write_text(cassette_text([value]), encoding="utf-8")
    with pytest.raises(CassetteValidationError, match=reason):
        validate_cassette(path)


def test_successful_write_cannot_have_response(tmp_path: Path) -> None:
    value = exchange(0, kind="write", command="RST", response="unexpected")
    path = tmp_path / "write.jsonl"
    path.write_text(cassette_text([value]), encoding="utf-8")
    with pytest.raises(CassetteValidationError, match="successful write"):
        validate_cassette(path)


def test_successful_query_requires_string_even_when_null(tmp_path: Path) -> None:
    value = exchange(0)
    value["response"] = None
    path = tmp_path / "null.jsonl"
    path.write_text(cassette_text([value]), encoding="utf-8")
    with pytest.raises(CassetteValidationError, match="successful query"):
        validate_cassette(path)


def test_failed_exchange_cannot_have_response(tmp_path: Path) -> None:
    value = exchange(
        0,
        response="partial",
        ok=False,
        error={"type": "timeout", "message": "late"},
    )
    path = tmp_path / "failed.jsonl"
    path.write_text(cassette_text([value]), encoding="utf-8")
    with pytest.raises(CassetteValidationError, match="failed exchange"):
        validate_cassette(path)


def test_error_object_has_exact_fields(tmp_path: Path) -> None:
    value = exchange(
        0,
        ok=False,
        error={"type": "timeout", "message": "late", "stack": "secret"},
    )
    path = tmp_path / "error.jsonl"
    path.write_text(cassette_text([value]), encoding="utf-8")
    with pytest.raises(CassetteValidationError, match="exactly type and message"):
        validate_cassette(path)


def test_time_cannot_move_backwards(tmp_path: Path) -> None:
    path = tmp_path / "time.jsonl"
    path.write_text(
        cassette_text([exchange(0, at_ms=2), exchange(1, at_ms=1)]),
        encoding="utf-8",
    )
    with pytest.raises(CassetteValidationError) as caught:
        validate_cassette(path)
    assert caught.value.line == 3
    assert "moved backwards" in caught.value.reason


def test_non_standard_numbers_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nan.jsonl"
    path.write_text(cassette_text([]) + '{"seq":NaN}\n', encoding="utf-8")
    with pytest.raises(CassetteValidationError, match="non-standard JSON number"):
        validate_cassette(path)
