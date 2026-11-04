"""agent/name_ner.py: is there a person's name in the caller's words, and which words are it. The cases are the turns of call 3fa23f68 and the everyday ways a name is said.

python -m pytest tests/test_name_ner.py -v
"""

import pytest

from agent import booking_capture as bc
from agent import name_ner as ner
from agent.booking_flow import new_state


@pytest.mark.parametrize(
    "said, name",
    [
        ("আমি বললাম আমার নাম শুভজিৎ", "শুভজিৎ"),  # call 3fa23f68: the fillers around the name are not the name
        ("আমার নাম শুভজিৎ গাঙ্গুলী", "শুভজিৎ গাঙ্গুলী"),
        ("শুভজিৎ গাঙ্গুলী বললাম", "শুভজিৎ গাঙ্গুলী"),
        ("বললাম শুভজিৎ", "শুভজিৎ"),
        ("নামটা সায়ন্তন চৌধুরী", "সায়ন্তন চৌধুরী"),
        ("নামটা চাঞ্জ হবে বিপ্লব সাহা", "বিপ্লব সাহা"),  # a changed name: the change words are dropped
        ("হ্যাঁ আমার নাম হচ্ছে সায়ন দাস", "সায়ন দাস"),
        ("হ্যাঁ সায়ন দাস", "সায়ন দাস"),
        ("না রাহুল দাস", "রাহুল দাস"),
        ("স্যার আমার নাম সুব্রত বসু", "সুব্রত বসু"),
        ("জি আমার নাম রোহান আনসারি", "রোহান আনসারি"),
        ("আবু আবু আলী", "আবু আবু আলী"),
        ("শুভজিৎ", "শুভজিৎ"),
        ("নলতির", "নলতির"),  # a name is an open class: an unknown word is still a name
        ("my name is rahul das", "Rahul Das"),
        ("this is Rahul Das", "Rahul Das"),
        ("मेरा नाम राहुल शर्मा है", "राहुल शर्मा"),
    ],
)
def test_the_name_is_found(said, name):
    span = ner.extract_name(said)
    assert span is not None and span.name == name, said


@pytest.mark.parametrize(
    "said",
    [
        "আমি নাম বললাম শুভজিৎ বয়স বললাম ঊনত্রিশ",  # a name AND an age: another answer, not a name
        "who was",
        "Who Was",
        "I said my name",
        "আমি বললাম",
        "নাম",
        "আচ্ছা",
        "জি",
        "হ্যাঁ",
        "না",
        "ঠিক আছে",
        "কখন বসবে",
        "ডাক্তার সেন",
        "কাল সকালে বুক করুন",
        "আমার ডেঙ্গু হয়েছে",
        "পেটে ব্যথা",
        "9876543210",
        "ঊনত্রিশ",
        "সাতাশ বছর",
        "জয়ন্ত?",
        "জয় kumar",  # two scripts in one name is a misreading
        "হ্যাঁ পারবো",  # filler words and one word nothing vouches for: a sentence, not a name
        "তিন চারগুলো কেমন হবে",
        "এটাই ঠিক",
        "বাংলায় বলুন",
        "আছে বন্ধু",
        "এই সেদিনেরই করুন",
        "কলকাতা পুলিশ স্টেশন বিধাননগর",
        "বিশ্বজিৎ সেনের কথা বলছি",  # a question about a doctor
        "x",
        "",
    ],
)
def test_something_that_is_not_a_name_gives_none(said):
    assert ner.extract_name(said) is None, said


def test_confidence_tells_a_vouched_name_from_a_bare_one():
    assert ner.extract_name("আমার নাম নলতির").confidence == "high" and ner.extract_name("আমার নাম নলতির").evidence == "cue"
    assert ner.extract_name("জয়ন্ত").confidence == "high" and ner.extract_name("জয়ন্ত").evidence == "known"
    assert ner.extract_name("সাহা").evidence == "known"  # a surname
    bare = ner.extract_name("নলতির")
    assert bare.confidence == "medium" and bare.evidence == "bare"


def test_the_voice_must_be_able_to_say_the_name_back():
    assert ner.speakable_in("শুভজিৎ", "bn") and ner.speakable_in("Rahul", "en") and ner.speakable_in("राहुल", "hi")
    assert (
        not ner.speakable_in("Rahul Das", "bn")
        and not ner.speakable_in("राहुल", "bn")
        and not ner.speakable_in("শুভজিৎ", "en")
        and not ner.speakable_in("", "bn")
    )


# ---------------------------------------------------------------------------- the booking, turn by turn (call 3fa23f68)


def waiting(pending=None):
    st = new_state("book_appointment")
    st.stage = "collecting"
    st.slots.update(
        {
            "doctor_name": "Pravir Ghosh",
            "date": "2026-11-05",
            "time_slot": "18:00",
            "phone": "9876543210",
            "_phone_ok": "9876543210",
        }
    )
    st.asked_fields.add("patient_name")
    st.pending_name = pending
    return st


def test_an_english_misreading_is_not_read_back_as_the_name():
    st = waiting()
    plan = bc.before_model(st, "who was", "bn", agreement=1.0)
    assert (
        plan.speak is None and st.pending_name is None
    )  # asked again by the normal flow, nothing blocked as unspeakable


def test_a_latin_name_is_not_read_back_in_a_bengali_reply():
    st = waiting()
    assert bc.before_model(st, "Rahul Das", "bn", agreement=1.0).speak is None and st.pending_name is None


def test_a_correction_with_fillers_gives_just_the_name():
    st = waiting("Who Was")
    plan = bc.before_model(st, "আমি বললাম আমার নাম শুভজিৎ", "bn", agreement=1.0)
    assert st.pending_name == "শুভজিৎ" and "শুভজিৎ" in plan.speak and "বললাম" not in plan.speak


def test_a_mumble_is_not_read_back_as_a_correction():
    st = waiting("শুভজিৎ")
    plan = bc.before_model(st, "নলতির", "bn", agreement=0.0)
    assert st.pending_name is None and (plan.speak is None or "নলতির" not in plan.speak)


def test_a_sentence_with_the_name_and_the_age_is_not_taken_as_a_name():
    st = waiting("শুভজিৎ")
    plan = bc.before_model(st, "আমি নাম বললাম শুভজিৎ বয়স বললাম ঊনত্রিশ", "bn", agreement=0.97)
    assert "বললাম" not in (plan.speak or "")
