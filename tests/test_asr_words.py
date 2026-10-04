"""Tests for the ASR token cleanup, with a fake alignment result.

No model is loaded here: `_to_words` is pure, so a stand-in token stream is enough to pin
down the two filtering rules that matter (no punctuation/spacing tokens, no zero-length
spans).
"""

from __future__ import annotations

from types import SimpleNamespace

from censorflow.asr.parakeet import _to_words
from censorflow.models import SOURCE_ASR


def _token(text: str, start: float, end: float, confidence: float = 0.9) -> SimpleNamespace:
    return SimpleNamespace(
        id=0, text=text, start=start, duration=end - start, end=end, confidence=confidence
    )


def _result(tokens: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(text="", tokens=tokens, sentences=[])


def test_leading_spaces_are_stripped() -> None:
    words = _to_words(_result([_token(" hello", 1.0, 1.4)]))
    assert [w.text for w in words] == ["hello"]


def test_spacing_and_punctuation_tokens_are_dropped() -> None:
    tokens = [
        _token(" hey", 0.0, 0.2),
        _token(" ", 0.2, 0.3),
        _token(",", 0.3, 0.4),
        _token(".", 0.4, 0.5),
        _token("!", 0.5, 0.6),
        _token("-", 0.6, 0.7),
    ]
    assert [w.text for w in _to_words(_result(tokens))] == ["hey"]


def test_zero_length_and_inverted_spans_are_dropped() -> None:
    tokens = [
        _token(" kept", 0.0, 0.2),
        _token(" zero", 1.0, 1.0),
        _token(" backwards", 2.0, 1.9),
    ]
    assert [w.text for w in _to_words(_result(tokens))] == ["kept"]


def test_words_are_sorted_by_start_and_carry_the_asr_source() -> None:
    tokens = [_token(" second", 2.0, 2.3), _token(" first", 1.0, 1.2)]
    words = _to_words(_result(tokens))
    assert [w.text for w in words] == ["first", "second"]
    assert all(w.source == SOURCE_ASR for w in words)


def test_missing_confidence_defaults_to_one() -> None:
    token = SimpleNamespace(text="word", start=0.0, end=0.5)
    assert _to_words(_result([token]))[0].confidence == 1.0