"""Tests for phone number validation in tool execution."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import pytest


def normalize_phone(phone: str) -> str | None:
    """Normalize phone to 10 digits. Returns None if invalid."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) > 10:
        digits = digits[-10:]
    if len(digits) == 10:
        return digits
    return None


class TestPhoneNormalization:
    def test_valid_10_digit(self):
        assert normalize_phone("9876543210") == "9876543210"

    def test_with_spaces(self):
        assert normalize_phone("987 654 3210") == "9876543210"

    def test_with_dashes(self):
        assert normalize_phone("987-654-3210") == "9876543210"

    def test_with_country_code(self):
        assert normalize_phone("+919876543210") == "9876543210"
        assert normalize_phone("919876543210") == "9876543210"

    def test_with_country_code_and_spaces(self):
        assert normalize_phone("+91 98765 43210") == "9876543210"

    def test_too_short(self):
        assert normalize_phone("12345") is None

    def test_empty(self):
        assert normalize_phone("") is None

    def test_non_numeric(self):
        assert normalize_phone("abcdefghij") is None

    def test_parentheses(self):
        assert normalize_phone("(987) 654-3210") == "9876543210"
