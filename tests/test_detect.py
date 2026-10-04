"""Profanity detection, against a test-only list of innocuous placeholder words.

AGENTS.md forbids putting real profanity in test files, so every word here is invented.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

from censorflow import config
from censorflow.models import SOURCE_ASR, Flag, Word
from censorflow.profanity import detect

# Invented words standing in for a word list: "snork", "blorp", "wibble" and so on.
LIST = """
# a comment that must be ignored
snork
blorp
zzapp
flummery
wibble
"""


class Lists(NamedTuple):
    extra: Path
    allow: Path

    @property
    def sets(self) -> tuple[frozenset[str], frozenset[str]]:
        return detect.load_wordlist(self.extra, self.allow)

    def __call__(self, word: str) -> bool:
        profane, allowed = self.sets
        return detect.is_profane(word, profane, allowed)


@pytest.fixture
def lists(tmp_path) -> Lists:
    extra = tmp_path / "extra.txt"
    extra.write_text(LIST, encoding="utf-8")
    allow = tmp_path / "allow.txt"
    allow.write_text("# nothing allowed by default\n", encoding="utf-8")
    return Lists(extra, allow)


def test_comments_and_blanks_are_ignored(lists):
    profane, _ = lists.sets
    assert {"snork", "blorp", "zzapp", "flummery", "wibble"} <= profane
    assert "comment" not in profane
    assert "ignored" not in profane
    assert "" not in profane


def test_plain_word_matches(lists):
    assert lists("snork")


def test_case_and_accents_are_folded(lists):
    assert lists("SNORK")
    assert lists("snórk")


def test_stretched_letters_collapse(lists):
    assert detect.normalise("snorrrk") == "snork"
    assert lists("snorrrk")


def test_a_stretched_double_letter_matches(lists):
    assert lists("snorrk"), "one stretched letter must still reach the list entry"


def test_doubled_letters_stay_doubled():
    # Collapsing the ss in "ass" would turn it into the ordinary word "as", so a
    # two-letter run is never collapsed in the normalised form.
    assert detect.normalise("ass") == "ass"
    assert detect.normalise("wibble") == "wibble"


def test_a_stretched_doubled_letter_still_matches(lists):
    """'wiiiibbbble' is one stretched vowel and one doubled consonant, or two vowels
    and a stretched consonant: both spellings have to be offered."""
    assert lists("wiiiiiiibbbble")
    assert "wibble" in detect.variants("wiiiiiiibbbble")


def test_a_short_word_never_shrinks_into_a_match():
    assert detect.variants("ass") == {"ass"}
    assert detect.variants("as") == set()


def test_symbol_masking_expands_to_a_wildcard(lists):
    """'w*bble' hides one letter, so it must match the word it stands in for."""
    assert lists("w*bble")
    assert lists("zz*pp")
    assert lists("sn*rk")
    assert not lists("w*ork"), "the wildcard must not match a different letter"


def test_symbol_masking_cannot_match_a_different_length(lists):
    assert not lists("w*ork")
    assert not lists("zz**pp")


def test_inflections_are_peeled(lists):
    assert lists("snorks")
    assert lists("snorking")
    assert lists("snorked")
    assert lists("snorker")
    assert lists("snorkings")


def test_apostrophes_are_stripped():
    assert detect.normalise("snorkin'") == "snorkin"


def test_in_apostrophe_inflection_is_peeled(lists):
    assert lists("snorkin")
    assert lists("snorkin'")


def test_plural_of_an_er_word_keeps_that_word():
    assert "snorker" in detect.variants("snorkers")
    assert "snork" in detect.variants("snorkers")


def test_ies_and_sibilant_es_keep_the_stem():
    assert "blory" in detect.variants("blories")
    assert "snorch" in detect.variants("snorches")
    assert "flummox" in detect.variants("flummoxes")


def test_silent_e_is_restored_for_ing_and_ed():
    assert "snore" in detect.variants("snoring")
    assert "snore" in detect.variants("snored")


def test_coming_stays_come():
    assert detect.variants("coming") == {"coming", "com", "come"}


def test_a_short_in_ending_is_not_peeled():
    assert detect.variants("cumin") == {"cumin"}


def test_a_doubled_letter_does_not_invent_a_shorter_stem():
    # "assess" can be spelled with one less s, which is a different word. That
    # alternate must not be peeled down to the three-letter stem.
    for word in ("assess", "assessed", "assessing", "assessment"):
        assert "ass" not in detect.variants(word)


def test_a_mask_that_leaves_one_letter_still_matches(lists):
    assert lists("b****")
    assert not lists("b***")


def test_peeling_never_goes_below_a_word(lists):
    # "flummery" minus "er" is "flumm"; it must not match anything on the list.
    assert not lists("flummer")


def test_matching_is_whole_token_only(lists):
    assert not lists("snorkerifico")
    assert not lists("unsnork")
    assert not lists("snorkskate")


def test_tokenise_drops_punctuation():
    assert detect.tokenise("Snork, blorp! zz-app") == ["snork", "blorp", "zz", "app"]


def test_allowlist_wins(lists, tmp_path):
    allow = tmp_path / "allow2.txt"
    allow.write_text("snork\n", encoding="utf-8")
    profane, allowed = detect.load_wordlist(lists.extra, allow)
    assert not detect.is_profane("snork", profane, allowed)
    assert not detect.is_profane("snorrk", profane, allowed)
    assert not detect.is_profane("sn*rk", profane, allowed)
    assert not detect.is_profane("snorkings", profane, allowed)
    assert detect.is_profane("blorp", profane, allowed)


def test_allowlist_of_a_longer_word_keeps_the_stem(lists, tmp_path):
    allow = tmp_path / "allow3.txt"
    allow.write_text("snorking\n", encoding="utf-8")
    profane, allowed = detect.load_wordlist(lists.extra, allow)
    assert not detect.is_profane("snorking", profane, allowed)
    assert detect.is_profane("snork", profane, allowed)


# Ordinary words the shipped list used to flag, plus near-collisions of stems it
# still keeps. None of these are profanity; they must stay uncensored.
_ORDINARY = (
    "fat",
    "pot",
    "meth",
    "weed",
    "hell",
    "damn",
    "crap",
    "gay",
    "sex",
    "suck",
    "kill",
    "porn",
    "piss",
    "class",
    "classes",
    "classic",
    "bass",
    "pass",
    "mass",
    "glass",
    "grass",
    "compass",
    "cassette",
    "assume",
    "assassin",
    "assault",
    "assembly",
    "assistant",
    "harass",
    "embarrass",
    "embarrassing",
    "molasses",
    "passenger",
    "coming",
    "cumin",
    "document",
    "cucumber",
    "circumstance",
    "cocktail",
    "cockatoo",
    "cockpit",
    "cockroach",
    "cocky",
    "peacock",
    "dickens",
    "predict",
    "title",
    "titan",
    "pussycat",
    "analysis",
    "shiitake",
    "scunthorpe",
    "nigeria",
    "niger",
    "night",
    "niggle",
    "niggard",
    "niggardly",
    "snigger",
    "japan",
    "spice",
    "cracker",
    "honky",
    "cousin",
    "virgin",
    "cabin",
    "muffin",
    "pumpkin",
    "shoe",
    "phoenix",
    "passion",
    "massive",
    "assess",
    "assessed",
    "assessing",
    "assessment",
    "cocked",
    "titter",
    "pricked",
    "spiced",
    "spice",
    "shiite",
    "cummer",
    "cummerbund",
    "dicker",
    "retardant",
    "pakistan",
)


def test_missing_extra_and_allow_files_fall_back_to_the_shipped_list(tmp_path):
    profane, allowed = detect.load_wordlist(tmp_path / "nope.txt", tmp_path / "nope2.txt")
    assert allowed == frozenset()
    assert profane, "data/profanity.txt looks empty"


def test_shipped_word_list_loads():
    profane, allowed = detect.load_wordlist()
    assert profane, "data/profanity.txt looks empty"
    assert isinstance(allowed, frozenset)
    assert not detect.is_profane("snork", profane, allowed), "placeholder must not be listed"


def test_shipped_list_leaves_ordinary_words_alone():
    profane, allowed = detect.load_wordlist()
    flagged = [word for word in _ORDINARY if detect.is_profane(word, profane, allowed)]
    assert flagged == []


def test_detect_builds_flags_with_asr_timing(lists):
    words = [
        Word(text="I", start=0.0, end=0.2, confidence=0.99, source="asr"),
        Word(text="snork", start=1.0, end=1.4, confidence=0.88, source="asr"),
        Word(text="blorp", start=2.0, end=2.3, confidence=0.5, source="asr"),
        Word(text="today", start=3.0, end=3.5, confidence=0.7, source="asr"),
    ]
    flags = detect.detect(words, extra_path=lists.extra, allowlist_path=lists.allow)
    assert [f.word_index for f in flags] == [1, 2]
    assert [f.text for f in flags] == ["snork", "blorp"]
    assert all(f.source == SOURCE_ASR for f in flags)
    assert all(f.censor and not f.approx for f in flags)
    assert (flags[0].start, flags[0].end, flags[0].confidence) == (1.0, 1.4, 0.88)


def test_detect_finds_nothing_in_clean_song():
    words = [
        Word(text="today", start=0.0, end=0.4, confidence=0.9, source="asr"),
        Word(text="we", start=0.5, end=0.6, confidence=0.9, source="asr"),
        Word(text="roll", start=0.7, end=0.9, confidence=0.9, source="asr"),
        Word(text="together", start=1.0, end=1.6, confidence=0.9, source="asr"),
    ]
    assert detect.detect(words) == []


def test_mask_word_hides_the_word():
    assert detect.mask_word("snork") == "s****"
    assert detect.mask_word("SNORK") == "s****"
    assert detect.mask_word("s*nork") == "s****"
    flags = [Flag(word_index=0, text="snork", start=0.0, end=0.5)]
    assert detect.mask_flags(flags) == ["s****"]


def test_peelable_suffixes_never_strip_the_whole_word():
    for suffix in config.PEELABLE_SUFFIXES:
        assert "" not in detect.variants(suffix)
        assert all(len(v) >= 3 for v in detect.variants(suffix))