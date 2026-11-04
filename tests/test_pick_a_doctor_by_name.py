"""Owner, 2026-11-04: after "কুণাল সিনহা, অভিজিৎ সরকার. কাকে দেখাতে চান?" the answer "সিনহাকে করে দিন" must book Dr. Sinha -- for EVERY doctor, by surname or first name, with any Bengali ending and any phrasing,
among the other doctors of the same department; and no other rule (the clinic's name, ...) may read it first.

python -m pytest tests/test_pick_a_doctor_by_name.py -q
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "clinic-api"))

import seed  # noqa: E402

from agent import doctor_search, owner_answers  # noqa: E402

ENDINGS = ["", "কে", "র", "ের", "এর", "কেই", "বাবু", "বাবুকে", "বাবুর"]
FRAMES = ["{}", "{} করে দিন", "{} বুক করুন", "{} এর কাছে", "ওনাকে {} করে দিন", "হ্যাঁ {} কে দিন", "{} সাহেবকে দিন"]


def _departments():
    names = seed.doctor_full_names()
    out = {}
    for dept, doctors in seed.DEPARTMENTS.items():
        rows = []
        for short, _quals in doctors:
            latin, bn, hi = names.get(short, ("", "", ""))
            if bn:
                rows.append((bn, [bn, latin or short]))
        if len(rows) >= 2:
            out[dept] = rows
    return out


DEPTS = _departments()


def _forms(bn_name: str):
    parts = bn_name.split()
    yield from ((parts[-1], "surname"),) if parts else ()
    if len(parts) > 1:
        yield parts[0], "first name"


@pytest.mark.parametrize("dept", sorted(DEPTS))
def test_every_doctor_is_picked_by_surname_or_first_name_with_any_ending_and_phrasing(dept):
    rows = DEPTS[dept]
    offered = [spellings for _bn, spellings in rows]
    failures = []
    for idx, (bn, _sp) in enumerate(rows):
        others = [r[0] for i, r in enumerate(rows) if i != idx]
        for word, kind in _forms(bn):
            # a first name that is also another offered doctor's first name or surname is ambiguous on purpose (the question is asked again, never guessed)
            clash = any(word in o.split() for o in others)
            for ending in ENDINGS:
                for frame in FRAMES:
                    said = frame.format(word + ending)
                    got = doctor_search.choose_by_name(said, offered)
                    if clash:
                        if got is not None and got != idx:
                            failures.append((said, kind, "picked the WRONG doctor", got))
                    elif got != idx:
                        failures.append((said, kind, "not picked", got))
                    assert not owner_answers.branch_identity(said, "bn"), (said, "taken for the clinic's name")
    assert not failures, failures[:15]


@pytest.mark.parametrize("dept", sorted(DEPTS))
@pytest.mark.parametrize(
    "said",
    ["বুক করে দিন", "করে দিন", "ঠিক আছে করুন", "হ্যাঁ করে দিন", "কত টাকা লাগবে", "আমি ডাক্তার দেখাতে চাই", "কখন বসেন", "যে কেউ হলেই হবে", "বুক করব কি করে", "না থাক"],
)
def test_a_sentence_that_names_nobody_picks_nobody(dept, said):
    # the two-letter-surname relaxation must not turn "বুক করে দিন" ("book it") into Dr. Kar
    offered = [spellings for _bn, spellings in DEPTS[dept]]
    assert doctor_search.choose_by_name(said, offered) is None, said
