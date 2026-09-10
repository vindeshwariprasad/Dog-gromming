"""Tests for shop data helpers."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from config.shop_data import (
    get_service_by_name, get_service_price, get_service_duration,
    get_full_groom_price, SERVICES, SHOP_HOURS,
)


class TestGetServiceByName:
    def test_exact_match(self):
        service = get_service_by_name("Bath & Brush")
        assert service is not None
        assert service["name"] == "Bath & Brush"
        assert service["price"] == 500
        assert service["duration_minutes"] == 30

    def test_case_insensitive(self):
        service = get_service_by_name("full groom")
        assert service is not None
        assert service["name"] == "Full Groom"

    def test_partial_match(self):
        service = get_service_by_name("nail trim")
        assert service is not None
        assert service["name"] == "Nail Trim & File"

    def test_unknown_service(self):
        assert get_service_by_name("Massage") is None
        assert get_service_by_name("") is None

    def test_all_services_exist(self):
        for s in SERVICES:
            result = get_service_by_name(s["name"])
            assert result is not None, f"Service {s['name']} not found"


class TestGetServicePrice:
    def test_fixed_price_service(self):
        assert get_service_price("Bath & Brush") == 500
        assert get_service_price("Nail Trim & File") == 200
        assert get_service_price("Teeth Brushing") == 150
        assert get_service_price("Puppy Introduction") == 350
        assert get_service_price("De-shedding Treatment") == 700
        assert get_service_price("Flea & Tick Treatment") == 650

    def test_full_groom_with_size(self):
        assert get_service_price("Full Groom", "Small") == 800
        assert get_service_price("Full Groom", "Medium") == 1000
        assert get_service_price("Full Groom", "Large") == 1200

    def test_full_groom_without_size(self):
        assert get_service_price("Full Groom") is None

    def test_unknown_service(self):
        assert get_service_price("Unknown") is None


class TestGetServiceDuration:
    def test_30_min_services(self):
        assert get_service_duration("Bath & Brush") == 30
        assert get_service_duration("Nail Trim & File") == 30
        assert get_service_duration("Teeth Brushing") == 30
        assert get_service_duration("Puppy Introduction") == 30

    def test_60_min_services(self):
        assert get_service_duration("Full Groom") == 60
        assert get_service_duration("De-shedding Treatment") == 60
        assert get_service_duration("Flea & Tick Treatment") == 60

    def test_unknown(self):
        assert get_service_duration("Unknown") is None


class TestFullGroomPricing:
    def test_all_sizes(self):
        assert get_full_groom_price("Small") == 800
        assert get_full_groom_price("Medium") == 1000
        assert get_full_groom_price("Large") == 1200

    def test_invalid_size(self):
        assert get_full_groom_price("XL") is None


class TestShopHours:
    def test_weekdays_open(self):
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            assert SHOP_HOURS[day] is not None
            assert SHOP_HOURS[day] == ("09:00", "17:00")

    def test_saturday_open(self):
        assert SHOP_HOURS["Saturday"] == ("09:00", "17:00")

    def test_sunday_closed(self):
        assert SHOP_HOURS["Sunday"] is None
