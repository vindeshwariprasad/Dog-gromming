"""Tests for breed-to-size mapping."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from config.breed_mapping import get_dog_size, is_large_breed


class TestGetDogSize:
    def test_known_small_breed(self):
        assert get_dog_size("Pomeranian") == "Small"
        assert get_dog_size("Shih Tzu") == "Small"
        assert get_dog_size("Chihuahua") == "Small"

    def test_known_medium_breed(self):
        assert get_dog_size("Beagle") == "Medium"
        assert get_dog_size("Pug") == "Medium"
        assert get_dog_size("Indian Pariah Dog") == "Medium"

    def test_known_large_breed(self):
        assert get_dog_size("Labrador Retriever") == "Large"
        assert get_dog_size("Golden Retriever") == "Large"
        assert get_dog_size("German Shepherd") == "Large"

    def test_case_insensitive(self):
        assert get_dog_size("pomeranian") == "Small"
        assert get_dog_size("GOLDEN RETRIEVER") == "Large"
        assert get_dog_size("beagle") == "Medium"

    def test_partial_match(self):
        assert get_dog_size("Lab") == "Large"  # Matches "Labrador"
        assert get_dog_size("Golden") == "Large"  # Matches "Golden Retriever"

    def test_unknown_breed(self):
        assert get_dog_size("Xoloitzcuintli") is None
        assert get_dog_size("Mixed breed") is None

    def test_empty_input(self):
        assert get_dog_size("") is None
        assert get_dog_size(None) is None

    def test_indian_breeds(self):
        assert get_dog_size("Indie") == "Medium"
        assert get_dog_size("Rajapalayam") == "Large"
        assert get_dog_size("Mudhol Hound") == "Large"
        assert get_dog_size("Indian Spitz") == "Medium"


class TestIsLargeBreed:
    def test_large_breed(self):
        assert is_large_breed("Labrador") is True
        assert is_large_breed("Rottweiler") is True

    def test_non_large_breed(self):
        assert is_large_breed("Pomeranian") is False
        assert is_large_breed("Beagle") is False

    def test_unknown_breed(self):
        assert is_large_breed("Unknown") is False
