from __future__ import annotations

import pytest
from fakes import cassette_text, exchange


def test_static_cassette_integration(benchvcr_replay: object) -> None:
    with benchvcr_replay("plugin.jsonl") as replay:  # type: ignore[operator]
        assert replay.query("*IDN?") == "fixture-device"
        replay.write("*RST")


def test_absolute_path_is_rejected(benchvcr_replay: object) -> None:
    with pytest.raises(ValueError, match="relative"):
        benchvcr_replay("/tmp/absolute.jsonl")  # type: ignore[operator]


def prepare_nested(pytester: pytest.Pytester) -> None:
    cassette_dir = pytester.path / "cassettes"
    cassette_dir.mkdir()
    (cassette_dir / "two.jsonl").write_text(
        cassette_text([exchange(0, command="A?"), exchange(1, command="B?")]),
        encoding="utf-8",
    )


def test_fixture_resolves_relative_to_nested_test_file(
    pytester: pytest.Pytester,
) -> None:
    prepare_nested(pytester)
    pytester.makepyfile(
        """
        def test_replay(benchvcr_replay):
            with benchvcr_replay("two.jsonl") as replay:
                assert replay.query("A?") == "response"
                assert replay.query("B?") == "response"
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)


def test_unplayed_error_is_raised_by_explicit_with(
    pytester: pytest.Pytester,
) -> None:
    prepare_nested(pytester)
    pytester.makepyfile(
        """
        def test_replay(benchvcr_replay):
            with benchvcr_replay("two.jsonl") as replay:
                replay.query("A?")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(failed=1)
    assert "UnplayedInteractionsError" in result.stdout.str()


def test_fixture_does_not_mask_test_assertion(pytester: pytest.Pytester) -> None:
    prepare_nested(pytester)
    pytester.makepyfile(
        """
        def test_replay(benchvcr_replay):
            with benchvcr_replay("two.jsonl"):
                assert False, "sentinel assertion"
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "sentinel assertion" in output
    assert "UnplayedInteractionsError" not in output


def test_no_finalizer_consumption_check_without_with(
    pytester: pytest.Pytester,
) -> None:
    prepare_nested(pytester)
    pytester.makepyfile(
        """
        def test_replay(benchvcr_replay):
            benchvcr_replay("two.jsonl")
        """
    )
    result = pytester.runpytest("-q")
    result.assert_outcomes(passed=1)
