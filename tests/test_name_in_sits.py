"""Owner, 2026-10-31: when the doctor asked for does not sit that day, the later sitting names the doctor ("ডাক্তার <name> ... বসবেন", not "উনি"), and "হ্যাঁ বলুন কোন ডাক্তার এটার নাম কি" is a
question about the doctor's name.

python -m pytest tests/test_name_in_sits.py -q
"""

import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import doctor_facts, slot_proposal  # noqa: E402

NOW = datetime.datetime(2026, 10, 31, 12, 0)


@pytest.mark.parametrize("lang", ["bn", "hi", "en"])
def test_the_moved_sitting_names_the_doctor(lang):
    say = slot_proposal.sits_statement("Dr. Arup Sen", "2026-11-02", "18:00", lang, now=NOW, moved=True, asked_date="2026-11-01")
    assert "Arup Sen" in say
    assert "উনি" not in say and "वे " not in say
    assert "Dr. Dr" not in say and "ডাক্তার ডাঃ" not in say


@pytest.mark.parametrize("text", ["হ্যাঁ বলুন কোন ডাক্তার এটার নাম কি", "কোন ডাক্তার এটা", "উনার নাম কি", "ওটার নাম কি"])
def test_who_is_this_doctor_is_recognised(text):
    assert doctor_facts.asks_which_doctor(text)


def test_the_sitting_sentence_names_the_doctors_department_and_asks_to_book():
    # Owner, 2026-11-04: "ডাক্তার পার্থ রায় ... বসবেন। অ্যাপয়েন্টমেন্ট করব?" -- "পার্থ রায় which department?" (he is the sugar / endocrinology doctor): the department is told, and the question is "বুক করব?"
    say = slot_proposal.sits_statement("পার্থ রায়", "2026-11-05", "10:00", "bn", now=NOW, dept="ডায়াবেটোলজি ও এন্ডোক্রিনোলজি")
    assert say.startswith("ডায়াবেটোলজি ও এন্ডোক্রিনোলজি বিভাগের ডাক্তার পার্থ রায়") and say.endswith("বুক করব?")
    assert "অ্যাপয়েন্টমেন্ট" not in say
    moved = slot_proposal.sits_statement("পার্থ রায়", "2026-11-07", "10:00", "bn", now=NOW, moved=True, asked_date="2026-11-05", dept="ডায়াবেটোলজি ও এন্ডোক্রিনোলজি")
    assert "ডায়াবেটোলজি ও এন্ডোক্রিনোলজি বিভাগের ডাক্তার পার্থ রায়" in moved and moved.endswith("বুক করব?")
