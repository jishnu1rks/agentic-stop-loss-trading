from app.tax import estimate_tax


def test_no_tax_on_loss():
    assert estimate_tax(gross_profit=-500, charges=50) == 0.0


def test_no_tax_when_charges_exceed_gain():
    assert estimate_tax(gross_profit=10, charges=15) == 0.0


def test_tax_applied_to_net_gain():
    tax = estimate_tax(gross_profit=1000, charges=100)
    assert tax == round(900 * 0.20, 2)
