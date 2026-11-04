"""Owner, 2026-11-04: another ending is another name (মানস / মানসী); a doctor named by sound is that doctor (মানুষ for মানস); the Chief Minister is not the clinic's business; the clinic's founding year is
not in any table and is not answered with the opening hours.

python -m pytest tests/test_names_and_topics_2026_11_04.py -q
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "clinic-api"))

import seed  # noqa: E402

from agent import name_groups, off_topic, owner_answers  # noqa: E402

ROWS = [{"name": k, "full_name": lat, "full_name_bn": bn, "full_name_hi": hi} for k, (lat, bn, hi) in seed.doctor_full_names().items()]


@pytest.mark.parametrize("a,b", [("মানসী", "মানস"), ("পল্লবী", "পল্লব"), ("অমিত", "অমিতা")])
def test_another_ending_is_another_name(a, b):
    assert name_groups.ending_variant(a, b) and not name_groups.sounds_like_given(a, b) and not name_groups.exact_given(a, b)


@pytest.mark.parametrize("a,b", [("মানুষ", "মানস"), ("অনীর্বাণ", "অনির্বাণ"), ("মানস", "মানস")])
def test_the_same_name_as_heard_is_the_same_name(a, b):
    assert name_groups.sounds_like_given(a, b)


def test_manasi_dutta_is_nobody_and_manas_dutta_is_offered_as_a_close_name():
    said = "মানসী দত্ত"
    reply = name_groups.reply(name_groups.build(said, ROWS, []), said, "bn", lambda d: d)
    assert reply.startswith("'মানসী দত্ত' নামে কেউ বসেন না।") and "কাছাকাছি নামে আছেন" in reply and "মানস দত্ত" in reply
    assert "হ্যাঁ" not in reply


def test_amit_kumar_is_nobody_and_amit_kar_is_found_by_the_first_name_not_by_kumar_sounding_like_kar():
    said = "অমিত কুমার"
    reply = name_groups.reply(name_groups.build(said, ROWS, []), said, "bn", lambda d: d)
    assert reply.startswith("'অমিত কুমার' নামে কেউ বসেন না।") and "অমিত নামে আছেন ডাঃ অমিত কর" in reply
    assert "কুমার নামে আছেন" not in reply


@pytest.mark.parametrize("text", ["হ্যাঁ বলছি পশ্চিমবঙ্গের মুখ্যমন্ত্রী কি আছে আপনাদের ওখানে", "প্রধানমন্ত্রী কে", "আজকে ক্রিকেট ম্যাচ কে জিতল"])
def test_politics_and_sport_are_off_topic_even_with_your_place(text):
    assert off_topic.names_unrelated_topic(text)


@pytest.mark.parametrize("text", ["ডাক্তার সরকার কখন বসেন", "আমার পেটে ব্যথা", "আপনাদের ক্লিনিক কখন খোলা"])
def test_clinic_business_is_never_off_topic(text):
    assert not off_topic.names_unrelated_topic(text)


@pytest.mark.parametrize("text", ["বলছি যে সোনা স্কাম কত সালে প্রতিষ্ঠা হয়েছে", "when was sonoscan established", "আপনাদের ক্লিনিক কত সালে শুরু হয়েছে"])
def test_the_founding_year_is_asked_about(text):
    assert owner_answers.asks_founding_year(text)
    assert "আমার কাছে নেই" in owner_answers.founding_year_reply("bn")


@pytest.mark.parametrize("text", ["ডাক্তার কত সালে পাস করেছেন", "চেম্বার কখন শুরু হয়", "আপনাদের ক্লিনিক কখন খোলা"])
def test_other_questions_are_not_the_founding_year(text):
    assert not owner_answers.asks_founding_year(text)


def test_manasi_is_not_manas_in_any_of_the_doctors_spellings():
    # the doctor is written in Bengali, Hindi and Latin letters: the Bengali spelling's ending check must hold even though a cross-script comparison alone cannot see the ending
    manas = next(r for r in ROWS if r["full_name"] == "Dr. Manas Dutta")
    givens, _sur = name_groups._own_names(manas)
    assert name_groups.given_matches("মানুষ", givens)  # as heard
    assert name_groups.given_matches("মানস", givens)
    assert not name_groups.given_matches("মানসী", givens)  # another name
    assert not name_groups.given_matches("मानसी", givens)


def test_an_offered_list_is_not_picked_by_another_ending_or_a_longer_surname():
    manas = next(r for r in ROWS if r["full_name"] == "Dr. Manas Dutta")
    assert name_groups.which_offered("কে বসে মানসী দত্ত", [manas]) == []  # মানসী is not মানস
    assert name_groups.which_offered("কে বসে মানস দত্ত", [manas]) == [manas]
    assert name_groups.which_offered("মানুষ দত্ত", [manas]) == [manas]  # as heard
