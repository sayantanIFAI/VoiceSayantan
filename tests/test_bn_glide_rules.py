"""agent/bn_glide_rules.py: shape rules for য় / ড়, all off unless BN_GLIDE_RULES chooses a variant; a word a listener already decided is never touched."""

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
        "after_aa_o=i": {"মাথায়": "মাথাই", "কোথায়": "কোথাই", "গায়ে": "গাইয়ে"},
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
    for word in ("হয়", "গিয়ে", "ছয়", "নয়", "থাইরয়েড", "হোয়াটসঅ্যাপ", "পঁয়ত্রিশ", "অ্যাপয়েন্টমেন্ট"):
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
    assert bn_glide_rules.classify("হয়") == [] and bn_glide_rules.classify("আপনার") == []
