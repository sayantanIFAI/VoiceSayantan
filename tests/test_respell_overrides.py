"""agent/bn_respell.py layer 0 (the listener-override data file) and tools/apply_listening_picks.py (the sheet that writes it)."""

import json
import os
import sys

import pytest

from agent import bn_respell

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import apply_listening_picks as picks  # noqa: E402


@pytest.fixture
def overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "respell_overrides.json"
    monkeypatch.setattr(bn_respell, "OVERRIDES_FILE", str(path))
    monkeypatch.setitem(bn_respell._OVERRIDES_CACHE, "mtime", None)
    monkeypatch.setitem(bn_respell._OVERRIDES_CACHE, "data", {})
    monkeypatch.delenv("BN_RESPELL_OVERRIDES", raising=False)
    return path


def write(path, data, bump):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.utime(
        path, (bump, bump)
    )  # a distinct modification time, so the reload is seen whatever the filesystem's clock resolution


def test_no_file_changes_nothing(overrides_file):
    assert bn_respell.overrides() == {}
    assert bn_respell.respell("পেমেন্ট") == "পেমেন্ট"


def test_a_listed_word_is_respelled_with_its_endings_and_a_changed_file_is_read_again(overrides_file):
    write(overrides_file, {"পেমেন্ট": "পে মেন্ট"}, 1_000_000)
    assert bn_respell.respell("পেমেন্ট") == "পে মেন্ট"
    assert bn_respell.respell("পেমেন্টের") == "পে মেন্টের"  # the same endings the table's words take
    assert bn_respell.respell("পেমেন্টটা") == "পে মেন্টটা"
    assert bn_respell.apply("পেমেন্ট করুন", "bn") == "পে মেন্ট করুন"
    assert bn_respell.apply("পেমেন্ট করুন", "hi") == "পেমেন্ট করুন"
    write(overrides_file, {"পেমেন্ট": "পেইমেন্ট"}, 1_000_100)
    assert bn_respell.respell("পেমেন্ট") == "পেইমেন্ট"
    overrides_file.unlink()
    assert bn_respell.respell("পেমেন্ট") == "পেমেন্ট"


def test_a_listener_pick_wins_over_the_built_in_table(overrides_file):
    assert bn_respell.respell("হোয়াটসঅ্যাপ") == "ওয়াটস অ্যাপ"
    write(overrides_file, {"হোয়াটসঅ্যাপ": "ওয়াৎস অ্যাপ"}, 1_000_000)
    assert bn_respell.respell("হোয়াটসঅ্যাপ") == "ওয়াৎস অ্যাপ"
    assert bn_respell.respell("হোয়াটসঅ্যাপে") == "ওয়াৎস অ্যাপে"


def test_a_bad_entry_or_a_bad_file_is_ignored(overrides_file, monkeypatch):
    write(overrides_file, {"পেমেন্ট": "pay ment", "রিপোর্ট": "রিপোট", "টেস্ট": "x" * 80, "রেট": 5}, 1_000_000)
    assert bn_respell.overrides() == {"রিপোর্ট": "রিপোট"}
    overrides_file.write_text("not json", encoding="utf-8")
    os.utime(overrides_file, (1_000_200, 1_000_200))
    assert bn_respell.overrides() == {}
    write(overrides_file, {"রিপোর্ট": "রিপোট"}, 1_000_300)
    monkeypatch.setenv("BN_RESPELL_OVERRIDES", "0")
    assert bn_respell.overrides() == {} and bn_respell.respell("রিপোর্ট") == "রিপোর্ট"


SHEET = """# English-origin words: listening sheet

- `loan_1.wav` পেমেন্ট: 1: পেমেন্ট | 2: পে মেন্ট | 3: পেইমেন্ট  -> best: 3
- `loan_2.wav` অনলাইন: 1: অনলাইন | 2: অন লাইন  -> best: 1
- `loan_3.wav` লিংক: 1: লিংক | 2: লিঙ্ক  -> best: none
- `loan_4.wav` রিপোর্ট: 1: রিপোর্ট | 2: রিপোট  -> best: ___
- `loan_5.wav` হোয়াটসঅ্যাপ: 1: ওয়াটস অ্যাপ | 2: ওয়াৎস অ্যাপ | 3: হোয়াট স অ্যাপ  -> best: 2
  - said inside "এই নম্বরে কি ... আছে?"; 1 = English recording, 2 = Bengali voice, 3 = Bengali voice
"""


def test_the_sheet_gives_a_pick_only_for_a_number_above_one():
    got, problems = picks.parse_sheet(SHEET)
    assert got == {"পেমেন্ট": "পেইমেন্ট", "হোয়াটসঅ্যাপ": "ওয়াৎস অ্যাপ"} and problems == []


def test_a_wrong_number_or_unreadable_pick_is_reported_not_guessed():
    got, problems = picks.parse_sheet(
        "- `loan_1.wav` রেট: 1: রেট | 2: রেট্  -> best: 7\n- `loan_2.wav` কল: 1: কল | 2: কল্  -> best: two\n"
    )
    assert got == {} and len(problems) == 2


def test_the_tool_merges_into_the_file_and_keeps_a_backup(tmp_path, monkeypatch):
    sheet = tmp_path / "sheet.md"
    sheet.write_text(SHEET, encoding="utf-8")
    out = tmp_path / "overrides.json"
    out.write_text(json.dumps({"রিপোর্ট": "রিপোট"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["apply_listening_picks.py", str(sheet), "--out", str(out)])
    assert picks.main() == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "রিপোর্ট": "রিপোট",
        "পেমেন্ট": "পেইমেন্ট",
        "হোয়াটসঅ্যাপ": "ওয়াৎস অ্যাপ",
    }
    assert json.loads((tmp_path / "overrides.json.bak").read_text(encoding="utf-8")) == {"রিপোর্ট": "রিপোট"}
    monkeypatch.setattr(
        sys, "argv", ["apply_listening_picks.py", str(sheet), "--out", str(tmp_path / "dry.json"), "--dry-run"]
    )
    assert picks.main() == 0 and not (tmp_path / "dry.json").exists()
