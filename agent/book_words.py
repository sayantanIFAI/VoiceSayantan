"""বুক: "book" and "chest" are the same Bengali word (call 87bbe05b: "হ্যাঁ কালকের জন্য বুক করুন" -- yes, book it for tomorrow -- counted as a health word, was routed as a chest complaint and answered with the
Cardiology doctor; and "বুকে ব্যথা", chest pain, counted as a request to book).

The two are told apart by what follows. "বুক" is the verb when a booking verb comes straight after it (করুন, করব, করে দিন, দিন, দেন, নিন, হবে, লাগবে ...); every other "বুক" is the chest ("বুকে", "বুকের", "বুক ব্যথা",
"বুক ধড়ফড়"). Pure string work, no model.
"""

from __future__ import annotations

import re

_NOT_BN = r"(?<![ঀ-৿])"
# "বুক" as a whole word, then (after spaces) the start of a booking verb
# a particle may stand between ("বুক তো করিনি", "বুক ই করব"): তো / ই / ও / আর
_BOOK_VERB_BN = re.compile(_NOT_BN + r"বুক(?=\s+(?:(?:তো|ই|ও|আর)\s+)?(?:কর|দি|দে|দা|নি|নে|হ[বয়চ]|লাগ|চাই|করা))")
_BOOK_VERB_HI = re.compile(_NOT_BN + r"बुक(?=\s+(?:(?:तो|ही|भी)\s+)?(?:कर|दी|दे|दो|लग|चाह|हो))")


def has_book_verb(text: str) -> bool:
    """True when the text has "বুক" / "बुक" used as the verb "book" (followed by a booking verb)."""
    t = text or ""
    return bool(_BOOK_VERB_BN.search(t) or _BOOK_VERB_HI.search(t))


def strip_book_verb(text: str) -> str:
    """The text with "বুক" taken out where it is the verb "book", so what is left can be read for symptoms and body parts without the chest being found in a booking request."""
    t = text or ""
    return _BOOK_VERB_HI.sub(" ", _BOOK_VERB_BN.sub(" ", t))
