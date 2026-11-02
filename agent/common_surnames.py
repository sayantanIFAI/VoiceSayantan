"""Surnames a caller may say that no doctor of the clinic carries.

Owner, 2026-11-03 ("ডাক্তার দেবাশিস দেব বসছে কালকে" was answered for Dr. Debashis Das): a first name that one doctor has, followed by a surname that is NOT his, names nobody. The
clinic's own surnames are known from the catalogue; these are the other everyday Bengali / Hindi surnames, so "দেবাশিস দেব" is recognised as "a first name and some other surname" and the caller
is told no such doctor sits, instead of being given the answer for the doctor who only shares the first name. Words that are also everyday words (ধর, খান, দেব as "will give" is kept: it only
matters beside a first name that a doctor has) are left out.
"""

from __future__ import annotations

import unicodedata

_SURNAMES = """
দেব দেবনাথ নাথ বর্মন বর্মণ পোদ্দার দাশ ঘটক সিংহ সিং শর্মা গুপ্ত গুপ্তা মিশ্র ঠাকুর আলী হোসেন রহমান শেখ পাণ্ডে পান্ডে যাদব বসাক রক্ষিত দত্তগুপ্ত
ভৌমিক সামন্ত মাইতি জানা প্রধান হাজরা বেরা ঘোড়ই সাউ দলুই পাত্র মাহাতো রাউত কর্মকার সরখেল চট্টরাজ রাহা বিশ্বাস সান্যাল তরফদার
देव नाथ शर्मा गुप्ता गुप्त मिश्रा ठाकुर यादव सिंह वर्मा अग्रवाल पांडे पाण्डे
""".split()


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


SURNAMES = frozenset(_nfc(s) for s in _SURNAMES)
