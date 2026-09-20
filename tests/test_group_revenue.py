"""Commercial revenue confirmation runs after costs, markup, and band pricing."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from services.itinerary.pipeline.group_revenue import confirm_group_revenue
from services.itinerary.pipeline.models import GroupPricingRow


def row(lower, upper, price, vehicle="VIP_BUS", foc=1):
    return GroupPricingRow(lower + foc, upper + foc, foc, vehicle, price, 400)


def test_live_vip_example_raises_each_band_against_adjusted_predecessor():
    original = [row(8, 9, 1875), row(10, 11, 1675), row(12, 13, 1550), row(14, 14, 1450)]
    before = deepcopy(original)
    result = confirm_group_revenue(original)
    assert [r.price_per_person for r in result] == [1875, 1750, 1650, 1575]
    assert [r.revenue_check["revenue_increase"] for r in result] == [None, 625, 550, 600]
    assert [r.calculated_price_per_person for r in result] == [1875, 1675, 1550, 1450]
    assert original == before
    assert confirm_group_revenue(result) == result


def test_coaster_and_vip_are_confirmed_independently():
    result = confirm_group_revenue([
        row(8, 9, 1500, "TOYOTA_COASTER"), row(10, 11, 1375, "TOYOTA_COASTER"),
        row(8, 9, 1875), row(10, 11, 1675),
    ])
    assert [r.price_per_person for r in result] == [1500, 1400, 1875, 1750]
    assert result[1].revenue_check["previous_maximum_revenue"] == 13500
    assert result[3].revenue_check["previous_maximum_revenue"] == 16875


def test_exact_450_gap_passes_without_a_price_increase():
    result = confirm_group_revenue([row(8, 9, 950), row(10, 11, 900)])
    assert result[1].price_per_person == 900
    assert result[1].revenue_check["revenue_increase"] == 450
    assert result[1].revenue_check["increase_per_person"] == 0


def test_one_cent_short_rounds_to_the_next_25():
    result = confirm_group_revenue([row(8, 9, 950), row(10, 11, 899.999)])
    assert result[1].price_per_person == 900
    assert result[1].revenue_check["minimum_revenue"] == 9000


def test_already_sufficient_prices_never_decrease_and_foc_is_not_revenue():
    result = confirm_group_revenue([row(8, 9, 1000, foc=2), row(10, 11, 1000, foc=2)])
    assert [r.price_per_person for r in result] == [1000, 1000]
    assert result[0].revenue_check["maximum_revenue"] == 9000
    assert result[1].revenue_check["revenue_increase"] == 1000


def test_input_order_does_not_change_which_band_is_the_predecessor():
    result = confirm_group_revenue([row(10, 11, 1375), row(8, 9, 1500)])
    assert result[0].price_per_person == 1400
    assert result[1].price_per_person == 1500


@pytest.mark.parametrize("rows", [
    [row(8, 9, 1000), row(9, 10, 950)],
    [row(0, 1, 1000)], [row(9, 8, 1000)],
    [row(8, 9, float("nan"))], [row(8, 9, float("inf"))], [row(8, 9, 0)],
])
def test_invalid_bands_and_prices_are_rejected(rows):
    with pytest.raises(ValueError):
        confirm_group_revenue(rows)


def test_price_confirmation_survives_quote_serialization():
    result = confirm_group_revenue([row(8, 9, 1875), row(10, 11, 1675)])
    payload = asdict(result[1])
    assert payload["price_per_person"] == 1750
    assert payload["calculated_price_per_person"] == 1675
    assert payload["revenue_check"]["required_minimum_revenue"] == 17325
    assert payload["revenue_check"]["passed"]
