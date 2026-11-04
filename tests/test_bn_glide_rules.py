"""agent/bn_glide_rules.py: shape rules for য় / ড়, all off unless BN_GLIDE_RULES chooses a variant; a word a listener already decided is never touched."""

import os
import unicodedata

import pytest

from agent import bn_glide_rules, bn_respell


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


@pytest.fixture(autouse=True)
def _no_rules(monkeypatch):
    monkeypatch.delenv("BN_GLIDE_RULES", raising=False)


def test_nothing_changes_by_default():
    for word in ("সময়", "কয়েক", "নিয়ে", "নেওয়া", "সাড়া", "বাড়ি", "মাথায়", "দয়া"):
        assert bn_glide_rules.rewrite(word) == word
    sentence = "আপনার সময় নিয়ে কয়েক দিন পরে বাড়ি যাবেন।"
    assert bn_respell.apply(sentence, "bn") == bn_respell.apply(
        sentence, "bn"
    )  # the same call, and no glide rule has run
    assert bn_glide_rules.active() == {}


def test_each_variant_rewrites_its_class(monkeypatch):
    cases = {
        "coda=oi": {"সময়": "সমোই", "বয়স": "বোইস", "জয়": "জোই"},
        "coda=i": {"সময়": "সমই", "পয়সা": "পইসা"},
        "before_vowel=sep": {"কয়েক": "কয়এক", "দয়া": "দয়আ"},
        "before_vowel=iy": {"কয়েক": "কইয়েক"},
        "after_i=iiy": {"নিয়ে": "নিইয়ে", "দিয়ে": "দিইয়ে"},
        "after_aa_o=i": {
            "মাথায়": "মাথাই",
            "কোথায়": "কোথাই",
            "গায়ে": "গাইয়ে",
            "মেয়ে": "মেইয়ে",
            "পেয়েছি": "পেইয়েছি",
            "দেয়": "দেই",
        },
        "owa=oa": {"দেওয়া": "দেওআ", "পাওয়া": "পাওআ"},
        "owa=waa": {"দেওয়া": "দেওয়াা"},
        "ra=nasal": {"বাড়ি": "বাঁড়ি", "ছাড়া": "ছাঁড়া"},
        "ra=r": {"বাড়ি": "বারি"},
    }
    for setting, words in cases.items():
        monkeypatch.setenv("BN_GLIDE_RULES", setting)
        for word, expected in words.items():
            assert bn_glide_rules.rewrite(word) == nfc(expected), (setting, word)


def test_a_precomposed_y_is_found_too(monkeypatch):
    monkeypatch.setenv("BN_GLIDE_RULES", "coda=oi")
    assert bn_glide_rules.rewrite("সময়") == nfc("সমোই")


def test_words_a_listener_decided_are_never_touched(monkeypatch):
    monkeypatch.setenv("BN_GLIDE_RULES", "coda=oi,before_vowel=sep,after_i=iiy,after_aa_o=i,owa=oa,ra=nasal")
    for word in ("গিয়ে", "থাইরয়েড", "হোয়াটসঅ্যাপ", "পঁয়ত্রিশ", "অ্যাপয়েন্টমেন্ট"):
        assert bn_glide_rules.rewrite(word) == word, word
    # the explicit listener table still wins over a rule
    assert (
        bn_respell.respell("নিয়ে") == "নিইয়ে"
        and bn_respell.respell("সময়টা") == "শমোইটা"
        and bn_respell.respell("কয়েক") == "কয়এক"
    )


def test_the_rules_run_inside_respell_after_the_sh_rule(monkeypatch):
    monkeypatch.setenv("BN_GLIDE_RULES", "coda=oi")
    assert bn_respell.respell("সময়") == "শমোই"  # sh rule (স -> শ) first, then the glide rule
    assert bn_respell.respell("পয়সা") == "পোইসা"
    monkeypatch.setenv("BN_GLIDE_RULES", "ra=nasal")
    assert bn_respell.apply("বাড়ি যাবেন", "bn") == "বাঁড়ি যাবেন"
    assert bn_respell.apply("বাড়ি", "hi") == "বাড়ি"  # only the Bengali voice


def test_one_class_does_not_rewrite_what_another_already_did(monkeypatch):
    monkeypatch.setenv("BN_GLIDE_RULES", "before_vowel=sep,coda=oi")
    assert bn_glide_rules.rewrite("কয়েক") == nfc("কয়এক")  # the য় of কয়এক is followed by a vowel: not a coda
    monkeypatch.setenv("BN_GLIDE_RULES", "after_i=iiy,coda=oi")
    assert bn_glide_rules.rewrite("নিয়ে") == nfc("নিইয়ে")


def test_a_typo_in_the_setting_turns_that_rule_off(monkeypatch):
    monkeypatch.setenv("BN_GLIDE_RULES", "coda=nope,nosuchclass=oi,owa")
    assert bn_glide_rules.active() == {}
    assert bn_glide_rules.rewrite("সময়") == "সময়"


def test_classify_lists_the_classes_a_word_belongs_to():
    assert bn_glide_rules.classify("কয়েক") == ["before_vowel"]
    assert bn_glide_rules.classify("সময়") == ["coda"]
    assert bn_glide_rules.classify("নেওয়া") == ["owa"]
    assert bn_glide_rules.classify("সাড়া") == ["ra"]
    assert bn_glide_rules.classify("হয়") == ["coda"]  # released from the protected list on 2026-11-04 (the listener wants it respelled)
    assert bn_glide_rules.classify("গিয়ে") == [] and bn_glide_rules.classify("আপনার") == []


E_RULES = {"coda": "e", "before_vowel": "e", "after_aa_o": "e"}


def test_the_glide_is_written_as_the_vowel_e(monkeypatch):
    """Owner, 2026-11-04: নয় -> নএ, and so on for the words of the same shape."""
    monkeypatch.setenv("BN_GLIDE_RULES", "coda=e,before_vowel=e,after_aa_o=e")
    expected = {
        "নয়": "নএ",
        "ছয়": "ছএ",
        "হয়": "হএ",
        "ভয়": "ভএ",
        "বয়স": "বএস",
        "সঞ্জয়": "সঞ্জএ",  # a glide at the end of a syllable
        "হয়েছে": "হএছে",
        "দয়া": "দএআ",
        "বিষয়ে": "বিষএ",  # a glide before a vowel (ে is not written twice)
        "মাথায়": "মাথাএ",
        "যায়": "যাএ",
        "কোথায়": "কোথাএ",
        "মেয়ে": "মেএ",
        "পেয়েছি": "পেএছি",
        "দেয়": "দেএ",  # after া / ো / ে
    }
    for word, spelling in expected.items():
        assert bn_glide_rules.rewrite(word) == nfc(spelling), word


def test_the_digits_are_no_longer_protected_but_decided_words_stay(monkeypatch):
    monkeypatch.setenv("BN_GLIDE_RULES", "coda=e,before_vowel=e,after_aa_o=e")
    assert bn_respell.respell("নয়") == "নএ" and bn_respell.respell("ছয়") == "ছএ" and bn_respell.respell("হয়") == "হএ"
    assert bn_respell.respell("সময়") == "শমএ"  # the স -> শ rule first, then the glide
    for kept in ("কয়েক", "নিয়ে", "সময়টা", "জয়দীপ", "গিয়ে", "থাইরয়েড"):
        assert bn_respell.respell(kept) == bn_respell.respell(
            kept
        )  # a decided word is returned by its own rule, never rewritten a second time
    assert (
        bn_respell.respell("জয়দীপ") == "জয় দীপ"
        and bn_respell.respell("কয়েক") == "কয়এক"
        and bn_respell.respell("নিয়ে") == "নিইয়ে"
    )


def test_the_rules_can_be_switched_on_from_a_data_file(monkeypatch, tmp_path):
    path = tmp_path / "glide_rules.json"
    monkeypatch.setattr(bn_glide_rules, "RULES_FILE", str(path))
    monkeypatch.setitem(bn_glide_rules._FILE_CACHE, "mtime", None)  # noqa: SLF001
    monkeypatch.setitem(bn_glide_rules._FILE_CACHE, "data", {})  # noqa: SLF001
    assert bn_glide_rules.active() == {} and bn_glide_rules.rewrite("নয়") == "নয়"
    path.write_text('{"coda": "e", "nosuch": "x", "ra": "bad"}', encoding="utf-8")
    os.utime(path, (2_000_000, 2_000_000))
    assert bn_glide_rules.active() == {"coda": "e"} and bn_glide_rules.rewrite("নয়") == "নএ"
    monkeypatch.setenv("BN_GLIDE_RULES", "coda=oi")  # the environment is put on top of the file
    assert bn_glide_rules.rewrite("নয়") == nfc("নোই")
    monkeypatch.delenv("BN_GLIDE_RULES")
    path.write_text("not json", encoding="utf-8")
    os.utime(path, (2_000_100, 2_000_100))
    assert bn_glide_rules.active() == {}
