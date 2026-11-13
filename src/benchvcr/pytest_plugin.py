"""Opt-in replay fixture loaded through the pytest11 entry point."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from .session import ReplaySession


@pytest.fixture
def benchvcr_replay(
    request: pytest.FixtureRequest,
) -> Callable[[str | Path], ReplaySession]:
    """Return a replay factory rooted beside the current test file.

    The caller must explicitly enter the returned context manager. There is no
    fixture finalizer, so test assertions and context-exit errors stay visible.
    """

    cassette_root = Path(str(request.node.fspath)).parent / "cassettes"

    def replay(name: str | Path) -> ReplaySession:
        relative = Path(name)
        if relative.is_absolute():
            raise ValueError("benchvcr_replay expects a relative cassette path")
        return ReplaySession(cassette_root / relative)

    return replay
