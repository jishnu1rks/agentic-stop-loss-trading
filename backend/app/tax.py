"""
Tax estimate (Section 6.3) - income tax liability on gains, tracked
separately from charges. This is a dashboard estimate only, not a
filing-ready figure: actual treatment (STCG vs. business income) depends
on the user's declared trading classification (Section 10 open item) -
confirm with a tax professional.
"""
from app.config import settings


def estimate_tax(gross_profit: float, charges: float) -> float:
    taxable_gain = gross_profit - charges
    if taxable_gain <= 0:
        return 0.0
    return round(taxable_gain * settings.stcg_tax_pct, 2)
