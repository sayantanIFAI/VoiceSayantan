"""Owner, 2026-10-31: a symptom word the keyword table does not know ("ছুলি", a skin disease) must still reach the right department -- by the symptom-word algorithm in
clinic-api/symptom_lexicon.py -- and the booking's police-station step must drop the words "police station" from the answer.

python -m pytest tests/test_symptom_lexicon.py -q
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "clinic-api"))

import symptom_lexicon as lex  # noqa: E402

from agent import booking_capture as bc  # noqa: E402
from agent.clause_split import split_into_clauses  # noqa: E402


@pytest.mark.parametrize(
    "text,dept",
    [
        ("বলছি আমার ছেলে না ছুলির মতো হয়ে যায় কাকে দেখাবো", "Dermatology"),
        ("আমার ছেলের ছুলি হয়েছে", "Dermatology"),
        ("ছেলের গায়ে ঘামাচি", "Dermatology"),
        ("my son has itching on his skin", "Dermatology"),
        ("बच्चे को दाद हो गया है", "Dermatology"),
        ("amar chele r chulkani", "Dermatology"),
        ("আমার খুব মাথা ব্যথা", "Neurology"),
        ("আমার কানে কম শুনি", "ENT"),
        ("পেচ্ছাপে জ্বালা", "Urology"),
        ("আমার বাবার প্রেসার বেশি", "Cardiology"),
        ("daante byatha", "Dentistry"),
        ("মেয়ের মাসিক হয় না", "Gynaecology & Obstetrics"),
        ("সুগারের সমস্যা", "Diabetology & Endocrinology"),
        ("হাঁটুতে ব্যথা", "Orthopaedics"),
        ("ঘুম আসে না", "Psychiatry"),
        ("পিঠে ফোঁড়া হয়েছে", "General Surgery"),
        ("আমার খুব জ্বর", "General Medicine"),
        ("চোখে ব্যথা", "Ophthalmology"),
    ],
)
def test_symptom_goes_to_its_department(text, dept):
    assert lex.departments_for(text) == [dept]


@pytest.mark.parametrize("text", ["আমার ছেলেকে কাকে দেখাবো", "আমার ছেলে কিছু খায় না", "ডাক্তার সেন কখন বসে", "the canada trip", "আমার ছেলে কেমন আছে", "valo doctor ke ache", "I have a problem"])
def test_a_sentence_without_a_symptom_word_finds_nothing(text):
    assert lex.departments_for(text) == []


def test_a_near_spelling_never_ties_with_the_exact_word():
    # "মাসিক" (period) is one letter from "মানসিক" (mental): the exact word wins alone
    assert lex.departments_for("মেয়ের মাসিক হয় না") == ["Gynaecology & Obstetrics"]
    assert lex.departments_for("আমার মানসিক সমস্যা") == ["Psychiatry"]


def test_a_specific_word_beats_the_vague_fever():
    assert lex.departments_for("ছেলের গায়ে ছুলি আর জ্বর") == ["Dermatology"]


@pytest.mark.parametrize(
    "said,station",
    [("থানার রাজারহাটি", "রাজারহাটি"), ("রাজারহাট থানা", "রাজারহাট"), ("rajarhat thana", "rajarhat"), ("पुलिस स्टेशन राजारहाट", "राजारहाट"), ("থানা", ""), ("Park Street", "Park Street")],
)
def test_police_station_words_are_not_part_of_the_name(said, station):
    assert bc.station_name_only(said) == station


def test_a_reply_with_a_phone_number_is_split_so_only_the_number_is_slow():
    assert split_into_clauses("আমি নম্বরটা শুনেছি 9 6 3 5 5 , 8 8 2 0 1। রোগীর বয়স কত?") == ["আমি নম্বরটা শুনেছি 9 6 3 5 5 , 8 8 2 0 1।", "রোগীর বয়স কত?"]
    assert split_into_clauses("রোগীর বয়স 45 বছর। ঠিকানাটা বলবেন?") == ["রোগীর বয়স 45 বছর। ঠিকানাটা বলবেন?"]


@pytest.mark.parametrize(
    "text,dept",
    [
        ("আমাকে একটা ডেরমাটোলজিস্ট দেখাতে হবে", "Dermatology"),  # owner, 2026-11-04: the real call's spelling
        ("ডার্মাটোলজিস্ট কে আছে", "Dermatology"),
        ("डर्मेटोलॉजिस्ट चाहिए", "Dermatology"),
        ("কার্ডিওলজিস্ট কে আছে", "Cardiology"),
        ("कार्डियोलॉजिस्ट है क्या", "Cardiology"),
        ("নিউরোলজিস্ট আছে", "Neurology"),
        ("ইউরোলজিস্ট", "Urology"),
        ("গাইনোকোলজিস্ট", "Gynaecology & Obstetrics"),
        ("অর্থোপেডিক ডাক্তার", "Orthopaedics"),
        ("সাইকিয়াট্রিস্ট", "Psychiatry"),
    ],
)
def test_a_specialists_own_name_in_any_spelling_finds_the_department(text, dept):
    assert lex.departments_for(text) == [dept]


# Owner, 2026-11-04: "ডেরমাটোলজিস্ট and dermatologist must be 95 percent similar -- for any department there is phonetic and accent variation": the specialist's name is matched BY SOUND, in any script.
@pytest.mark.parametrize(
    "text,dept",
    [
        ("dermetologist", "Dermatology"), ("dermatolajist", "Dermatology"), ("derma tologist", "Dermatology"),
        ("কার্ডিওলোজিস্ট", "Cardiology"), ("kardiologist", "Cardiology"), ("cardeologist", "Cardiology"),
        ("newrologist", "Neurology"), ("নিউরোলোজিস্ট", "Neurology"), ("ইউরলজিস্ট", "Urology"),
        ("gaynecologist", "Gynaecology & Obstetrics"), ("gynocologist", "Gynaecology & Obstetrics"),
        ("orthopedic", "Orthopaedics"), ("পেডিয়াট্রিসিয়ান", "Paediatrics"), ("এন্ডোক্রিনোলজিস্ট", "Diabetology & Endocrinology"),
        ("gastroenterologist", "Gastroenterology"), ("অফথ্যালমোলজিস্ট", "Ophthalmology"), ("ডেন্টিস্ট", "Dentistry"),
    ],
)
def test_a_specialists_name_is_found_by_sound_in_any_script_and_accent(text, dept):
    assert lex.departments_for(text) == [dept]


def test_no_doctors_name_is_taken_for_a_symptom_or_a_specialist():
    # "Halder" is one letter from "hader" (bone), "Sarkar" sounds like "surgery", "মিত্র" is one letter from "মুত্র" (urine): a doctor's name never routes to a department
    import seed

    for key, (latin, bn, hi) in seed.doctor_full_names().items():
        for name in {key, latin, bn, hi}:
            if name:
                assert lex.departments_for(name) == [], name


def test_a_word_that_is_a_doctors_name_is_never_a_symptom_and_the_word_after_a_title_is_a_name():
    # Owner, 2026-11-04: "মুত্র can come for a lab test only -- if talking about a doctor it never comes": the clinic's own doctor names are handed in, and the word after "ডাক্তার / Dr" is a name position
    import seed

    names = [n for k, (lat, bn, hi) in seed.doctor_full_names().items() for n in (k, lat, bn, hi)]
    for sentence in ["ডাক্তার রিনা মিত্র কখন বসেন", "ডাক্তার মিত্র আছেন", "Dr Halder কবে বসবে", "ডাক্তার সরকার", "ডাঃ গাঙ্গুলী আজ আছেন"]:
        assert lex.departments_for(sentence, names) == [], sentence
    # a title before a real written symptom/specialist word still finds it, and ordinary symptoms are untouched with the names handed in
    assert lex.departments_for("আমাকে একটা ডেরমাটোলজিস্ট দেখাতে হবে", names) == ["Dermatology"]
    assert lex.departments_for("আমার ছেলের ছুলি হয়েছে", names) == ["Dermatology"]
    assert lex.departments_for("মূত্রের সমস্যা", names) == ["Urology"]


# Owner, 2026-11-04: "byatha ache doctor dekhabo" / "allergyr doctor dekhabo" -- the kind of complaint is said, the place is not: the caller is asked WHERE, then it is routed.
@pytest.mark.parametrize(
    "text,kind",
    [("byatha ache doctor dekhabo", "pain"), ("আমার ব্যথা আছে ডাক্তার দেখাবো", "pain"), ("allergyr doctor dekhabo", "allergy"), ("এলার্জির ডাক্তার দেখাবো", "allergy"), ("allergy hoyeche", "allergy")],
)
def test_pain_or_allergy_with_no_place_asks_where(text, kind):
    assert lex.departments_for(text) == []
    assert lex.vague_kind(text) == kind


@pytest.mark.parametrize(
    "text,dept",
    [("চামড়ায় অ্যালার্জি", "Dermatology"), ("নাকে অ্যালার্জি", "ENT"), ("মাথা ব্যথা", "Neurology"), ("দাঁতে ব্যথা", "Dentistry")],
)
def test_the_place_decides_the_department(text, dept):
    assert lex.vague_kind(text) is None
    assert lex.departments_for(text) == [dept]


def test_the_location_questions_are_recognised_when_the_agent_says_them():
    from agent import reply_templates as rt

    for kind in ("pain", "allergy"):
        for lang in ("bn", "hi", "en"):
            assert rt.location_kind_of(rt.location_question(kind, lang)) == kind
    assert rt.location_kind_of("আজ কার্ডিওলজি বিভাগে") is None


@pytest.mark.parametrize(
    "text,dept",
    [("amar buke khub betha hocche", "Cardiology"), ("kane betha", "ENT"), ("matha byatha", "Neurology"), ("komor byatha", "Orthopaedics"), ("dante byatha", "Dentistry"), ("chokhe allergy", "Ophthalmology"), ("peter byatha", "General Medicine")],
)
def test_a_place_in_latin_letters_is_a_place_not_a_reason_to_ask_where(text, dept):
    # Owner, 2026-11-04: a caller who says where in Latin letters ("buke", "kane") is routed, not asked "where?"
    assert lex.vague_kind(text) is None
    assert lex.departments_for(text) == [dept]


@pytest.mark.parametrize(
    "text,kind",
    [("bhythar doctor dekhabo", "pain"), ("bythar doctor dekhabo", "pain"), ("ব্যথার ডাক্তার দেখাবো", "pain"), ("allergyr doctor dekhabo", "allergy"), ("alergy hoyeche", "allergy")],
)
def test_more_ways_of_saying_pain_or_allergy_with_no_place(text, kind):
    assert lex.vague_kind(text) == kind
