from app.charges import compute_charges


def test_delivery_buy_has_zero_brokerage():
    breakdown = compute_charges("buy", buy_price=100.0, sell_price=110.0, quantity=100)
    assert breakdown.brokerage == 0.0
    assert breakdown.stt > 0
    assert breakdown.total > 0


def test_intraday_sell_charges_brokerage_both_legs():
    breakdown = compute_charges("sell", buy_price=100.0, sell_price=95.0, quantity=100)
    assert breakdown.brokerage > 0
    # STT only applies to the sell leg for intraday/MIS trades (Section 6.3 assumption)
    assert breakdown.stt > 0


def test_charges_scale_with_quantity():
    small = compute_charges("buy", buy_price=100.0, sell_price=105.0, quantity=10)
    large = compute_charges("buy", buy_price=100.0, sell_price=105.0, quantity=100)
    assert large.total > small.total
