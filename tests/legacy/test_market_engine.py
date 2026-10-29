from datetime import date, timedelta

import pytest

import market_engine as me

ITEMS = [("it_layoff_hedge", "high"), ("cricket_mood_index", "medium"), ("monsoon_insurance", "low"),
         ("coconut_oil_commodity", "medium"), ("other", "unknown-volatility")]


@pytest.mark.parametrize("item_id,vol", ITEMS)
def test_price_within_floor_and_ceiling(item_id, vol):
    base = 200
    start = date(2026, 1, 1)
    for d in range(0, 120):
        for hour in (0, 6, 12, 23):
            p = me._compute_price(item_id, base, vol, start + timedelta(days=d), rain_mm=80.0, hour=hour)
            assert int(base * 0.20) <= p <= int(base * 3.0)


def test_price_is_deterministic():
    a = me._compute_price("x", 100, "medium", date(2026, 5, 5), hour=3)
    b = me._compute_price("x", 100, "medium", date(2026, 5, 5), hour=3)
    assert a == b


def test_floor_is_at_least_one():
    assert me._compute_price("x", 1, "high", date(2026, 5, 5)) >= 1


def test_rain_boost_only_for_monsoon_and_capped():
    d = date(2026, 6, 2)
    dry = me._compute_price("monsoon_insurance", 1000, "low", d, rain_mm=0.0)
    wet = me._compute_price("monsoon_insurance", 1000, "low", d, rain_mm=500.0)
    assert wet >= dry
    assert wet <= int(1000 * 3.0)
    assert me._compute_price("other", 1000, "low", d, rain_mm=0.0) == me._compute_price("other", 1000, "low", d, rain_mm=500.0)


def test_trend_arrow_returns_str():
    assert isinstance(me.get_trend_arrow(150, 100), str)
    assert me.get_trend_arrow(150, 100) != me.get_trend_arrow(50, 100)
