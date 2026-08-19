"""Offline tests for the workspace display-name policy (pure, no services)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workspace_names import (  # noqa: E402
    MAX_LENGTH,
    is_valid_workspace_name,
    name_key,
    normalize_workspace_name,
)


def test_normalize_trims_and_collapses_whitespace():
    assert normalize_workspace_name("  Amma's   records  ") == "Amma's records"


def test_rejects_empty_and_whitespace_only():
    assert normalize_workspace_name("") is None
    assert normalize_workspace_name("   ") is None
    assert normalize_workspace_name(None) is None


def test_rejects_names_over_max_length():
    assert normalize_workspace_name("a" * (MAX_LENGTH + 1)) is None
    assert normalize_workspace_name("a" * MAX_LENGTH) is not None


def test_rejects_disallowed_characters():
    assert normalize_workspace_name("no@name") is None
    assert normalize_workspace_name("name#1") is None
    # Control characters that are not whitespace are rejected.
    assert normalize_workspace_name("name\x01bad") is None


def test_collapses_internal_whitespace():
    # Tabs/newlines are neutralised to single spaces rather than rejected.
    assert normalize_workspace_name("name\nwith\tnewline") == "name with newline"


def test_allows_reasonable_human_names():
    assert normalize_workspace_name("Amma's records") == "Amma's records"
    assert normalize_workspace_name("John Smith 2026") == "John Smith 2026"
    assert normalize_workspace_name("A.B-C_D") == "A.B-C_D"


def test_name_key_is_case_and_space_insensitive():
    assert name_key("Amma's Records") == name_key("amma's records")
    assert name_key(" A B ") == name_key("a b")
    assert name_key("A") != name_key("B")


def test_is_valid_workspace_name():
    assert is_valid_workspace_name("Hello") is True
    assert is_valid_workspace_name("   ") is False
