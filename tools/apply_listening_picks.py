"""Turn a filled-in listening sheet (tools/loanword_pack.py's answer_sheet.md) into the data file the agent reads, /workspace/respell_overrides.json (agent/bn_respell.py, layer 0).

    python tools/apply_listening_picks.py loan_pack/answer_sheet.md --dry-run       show what would be written
    python tools/apply_listening_picks.py loan_pack/answer_sheet.md                 merge the picks into /workspace/respell_overrides.json (run on the pod)

Each sheet line ends "-> best: ___". The listener replaces the blanks with the number of the best candidate: 1 = what the bot says today (nothing to change), 2.. = that candidate's spelling, `none` or blank = no pick.
The agent reads the file again whenever it changes: the pick is heard on the next reply that is not already in the audio cache; no restart. The old file is kept as <file>.bak.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import bn_respell  # noqa: E402

_LINE = re.compile(r"^- `[^`]+` (\S+): (.*?)\s+-> best:\s*(.*)$")
_CANDIDATE = re.compile(r"^(\d+): (.*)$")


def parse_sheet(text: str) -> tuple[dict[str, str], list[str]]:
    """({word: chosen spelling}, [problems]). A line with no number, `none` or 1 gives no entry; a number with no such candidate, or a spelling the agent would refuse, is reported."""
    picks: dict[str, str] = {}
    problems: list[str] = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        word, candidates, best = m.group(1), m.group(2), m.group(3).strip().strip("_ ").strip()
        if not best or best.lower() == "none" or not best.isdigit():
            if best and best.lower() != "none":
                problems.append(f"{word}: cannot read the pick {best!r}")
            continue
        number = int(best)
        if number == 1:
            continue
        spellings = {}
        for part in candidates.split(" | "):
            cm = _CANDIDATE.match(part.strip())
            if cm:
                spellings[int(cm.group(1))] = unicodedata.normalize("NFC", cm.group(2).strip())
        chosen = spellings.get(number)
        if chosen is None:
            problems.append(f"{word}: there is no candidate {number}")
        elif not bn_respell._OVERRIDE_VALUE.match(chosen) or len(chosen) > 60:  # noqa: SLF001
            problems.append(f"{word}: {chosen!r} is not a Bengali spelling the agent accepts")
        else:
            picks[unicodedata.normalize("NFC", word)] = chosen
    return picks, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--out", default=bn_respell.OVERRIDES_FILE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with open(args.sheet, encoding="utf-8") as fh:
        picks, problems = parse_sheet(fh.read())
    for p in problems:
        print("problem:", p)
    for word, spelling in picks.items():
        print(f"{word} -> {spelling}")
    if problems:
        print("fix the sheet and run again; nothing written")
        return 1
    if not picks:
        print("no picks in the sheet; nothing written")
        return 0
    if args.dry_run:
        print(f"(dry run) {len(picks)} pick(s) would be merged into {args.out}")
        return 0
    existing: dict[str, str] = {}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fh:
            existing = json.load(fh) or {}
        shutil.copyfile(args.out, args.out + ".bak")
    existing.update(picks)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, args.out)  # one atomic step: the agent never reads half a file
    print(f"wrote {len(existing)} spelling(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
