"""Tests for Chroma collection-name sanitization.

Chroma requires 3-63 chars, first and last character alphanumeric, and only
[a-zA-Z0-9._-] throughout. The original implementation applied the
end-alphanumeric fixup and THEN truncated with `return name[:63]`, so a cut
landing on a separator left a trailing '_'/'.'/'-' and Chroma rejected the
name at index time (surfacing as indexed=False / a failed Q&A rather than a
clear error).

retrieval.py and vector_store.py each carry a copy of this function; they
must stay identical or a write and a later read would resolve to different
collections. Both are tested here.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retrieval import _sanitize_collection_name as sanitize_retrieval  # noqa: E402
from vector_store import _sanitize_collection_name as sanitize_vector_store  # noqa: E402

IMPLEMENTATIONS = [
    pytest.param(sanitize_retrieval, id="retrieval"),
    pytest.param(sanitize_vector_store, id="vector_store"),
]

CHROMA_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]$")


def assert_valid_chroma_name(name):
    assert 3 <= len(name) <= 63, f"length {len(name)} out of range: {name!r}"
    assert name[0].isalnum(), f"must start alphanumeric: {name!r}"
    assert name[-1].isalnum(), f"must end alphanumeric: {name!r}"
    assert CHROMA_NAME_RE.match(name), f"illegal characters: {name!r}"


@pytest.mark.parametrize("sanitize", IMPLEMENTATIONS)
class TestSanitizeCollectionName:
    @pytest.mark.parametrize(
        "patient_key",
        [
            "amit sharma",
            "Jane Doe",
            "a",
            "ab",
            "  padded  ",
            "x" * 200,
            "!!!",
            "___",
            "...",
            "---",
            "",
            "   ",
            "user@example.com",
            "patient/with/slashes",
            "கமலா ராஜ்",  # non-Latin script -> all chars replaced
            "名前",
            "123",
            "1",
            "a-b_c.d",
        ],
    )
    def test_always_produces_a_valid_name(self, sanitize, patient_key):
        assert_valid_chroma_name(sanitize(patient_key))

    def test_long_key_truncating_on_separator_still_ends_alphanumeric(self, sanitize):
        """The regression: 62 'a's + a space + more text. The space becomes
        '_' at index 62, so a naive [:63] cut ends on that separator."""
        key = "a" * 62 + " bcd"
        name = sanitize(key)

        assert not name.endswith(("_", ".", "-")), f"ends on separator: {name!r}"
        assert_valid_chroma_name(name)

    @pytest.mark.parametrize("filler_len", range(58, 68))
    def test_boundary_lengths_around_the_63_char_cut(self, sanitize, filler_len):
        """Sweep the cut point across a separator to catch off-by-ones."""
        key = "a" * filler_len + " tail"
        assert_valid_chroma_name(sanitize(key))

    def test_never_exceeds_63_chars(self, sanitize):
        assert len(sanitize("z" * 500)) <= 63

    def test_minimum_length_padding_survives_truncation(self, sanitize):
        assert len(sanitize("a")) >= 3
        assert len(sanitize("!")) >= 3

    def test_is_deterministic(self, sanitize):
        key = "amit sharma"
        assert sanitize(key) == sanitize(key)

    def test_distinct_keys_stay_distinct(self, sanitize):
        assert sanitize("alice smith") != sanitize("bob jones")


def test_both_implementations_agree():
    """retrieval.py and vector_store.py must produce identical names — a
    divergence would mean writes and reads hit different collections."""
    keys = [
        "amit sharma",
        "Jane Doe",
        "a",
        "",
        "!!!",
        "x" * 200,
        "a" * 62 + " bcd",
        "user@example.com",
        "கமலா ராஜ்",
        "a" * 63 + "_tail",
        "-leading",
        "trailing-",
    ]
    for key in keys:
        assert sanitize_retrieval(key) == sanitize_vector_store(key), (
            f"implementations diverged for {key!r}: "
            f"{sanitize_retrieval(key)!r} != {sanitize_vector_store(key)!r}"
        )
