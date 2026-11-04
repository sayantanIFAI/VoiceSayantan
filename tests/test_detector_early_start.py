"""agent/detector_budget.start_detector / finish_within_budget: a detector that needs only the audio starts beside the recogniser, and its budget
runs from the moment the turn waits for it, not from when it began.

    python -m pytest tests/test_detector_early_start.py -v
"""

import asyncio
import os
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from agent.detector_budget import _OVER_BUDGET_COUNTS, finish_within_budget, snapshot, start_detector


def _takes_a_moment() -> str:
    time.sleep(0.15)
    return "done"


def _fails() -> str:
    raise ValueError("bad clip")


@pytest.mark.asyncio
async def test_time_spent_beside_the_recogniser_is_free():
    job = start_detector(_takes_a_moment)
    await asyncio.sleep(0.3)  # the recogniser's time
    assert await finish_within_budget("early_ok", job, 0.02, previous_value="old") == "done"
    assert snapshot()["early_ok"]["over_budget_count"] == 0


@pytest.mark.asyncio
async def test_a_detector_still_running_past_the_budget_degrades_to_the_previous_value():
    job = start_detector(_takes_a_moment)
    t0 = time.monotonic()
    assert await finish_within_budget("early_slow", job, 0.03, previous_value="old") == "old"
    assert time.monotonic() - t0 < 0.12
    assert _OVER_BUDGET_COUNTS["early_slow"] == 1


@pytest.mark.asyncio
async def test_a_failure_is_raised_as_run_within_budget_does():
    job = start_detector(_fails)
    with pytest.raises(ValueError):
        await finish_within_budget("early_fail", job, 0.5)


@pytest.mark.asyncio
async def test_a_failure_nobody_awaits_is_not_an_error():
    start_detector(_fails)
    await asyncio.sleep(0.05)
