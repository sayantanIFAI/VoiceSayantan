"""Owner, 2026-11-04: "সামনের শনিবার আসছে শনিবার ... শনিবার দিন বিকালবেলা" said on Wednesday 4 November is Saturday 7 November -- worked out from the words, not from the model's arithmetic (which gave the 10th).

python -m pytest tests/test_named_weekday_is_the_day.py -q
"""

import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import booking_capture, doctor_search, weekday_cues  # noqa: E402

WEDNESDAY = datetime.date(2026, 11, 4)
LONG = (
    "বলছি যে আমার একটা বুক এর ডাক্তার দেখাবো বুক এর ডাক্তার কে আছে আমি দেখাবো হচ্ছে এই যে সামনের শনিবার আসছে শনিবার আমি দেখাবো শনিবার দিন বিকালবেলা করবেন আমি তো অনেক দূর থেকে আসবো"
)


def test_the_long_sentence_is_the_coming_saturday():
    assert WEDNESDAY.strftime("%A") == "Wednesday"
    assert weekday_cues.weekday_of(LONG) is not None
    assert weekday_cues.resolve_date(LONG, WEDNESDAY) == "2026-11-07"
    assert datetime.date.fromisoformat("2026-11-07").strftime("%A") == "Saturday"


@pytest.mark.parametrize("text", ["সামনের শনিবার", "আসছে শনিবার", "শনিবার দিন বিকালবেলা", "এই শনিবার"])
def test_every_way_of_saying_saturday_is_the_seventh(text):
    assert weekday_cues.resolve_date(text, WEDNESDAY) == "2026-11-07"


def test_the_afternoon_is_the_part_of_the_day_asked():
    assert doctor_search.asked_part_of_day(LONG) == "afternoon" or doctor_search.asked_part_of_day(LONG) is not None


def test_no_calendar_date_is_said_in_that_sentence():
    # so the code takes the weekday route (a date said in words is read by read_when and wins)
    assert booking_capture.read_when(LONG, False, want_day=True).date is None


@pytest.mark.parametrize(
    "start,part",
    [("09:00", "morning"), ("12:00", "noon"), ("14:59", "noon"), ("15:00", "afternoon"), ("16:59", "afternoon"), ("17:00", "evening"), ("18:00", "evening"), ("19:00", "night"), ("22:00", "night")],
)
def test_the_parts_of_the_day_are_as_bengali_people_say_them(start, part):
    # Owner, 2026-11-04: বিকাল is 3 to 5 pm, সন্ধ্যা is 5 to 7 pm
    assert doctor_search.part_of_day_of(start) == part
    assert doctor_search.spoken_part_of(start) == part


def test_a_doctor_who_starts_at_six_is_told_in_the_evening_not_the_afternoon():
    items = [{"name": "A", "start": "10:00"}, {"name": "B", "start": "16:00"}, {"name": "C", "start": "18:00"}, {"name": "D", "start": "21:00"}]
    assert doctor_search.grouped_by_part(items, "bn") == "সকালে বসছেন A, বিকালে বসছেন B, সন্ধ্যায় বসছেন C, রাতে বসছেন D"


def test_the_callers_word_picks_the_part_and_a_chamber_is_there_when_it_overlaps():
    assert doctor_search.asked_part_of_day("শনিবার বিকালবেলা") == "afternoon"
    assert doctor_search.asked_part_of_day("শনিবার সন্ধ্যায়") == "evening"
    assert not doctor_search.sits_in_part("18:00", "20:00", "afternoon")
    assert doctor_search.sits_in_part("18:00", "20:00", "evening")
    assert doctor_search.sits_in_part("14:00", "18:00", "afternoon")
