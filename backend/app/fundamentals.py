"""
Standard recommendability screen for "screener" (trending) universe agents.

Approximates the financial-health/valuation/governance criteria typically
used for Indian equities, scoped to what YFinanceMarketDataAdapter.get_fundamentals
can actually supply for NSE tickers: P/E, P/B, PEG, Debt/Equity, market cap,
insider-holding % and trailing revenue/earnings growth. ROE, ROCE, free cash
flow, interest coverage, and promoter pledging/governance history are not
reliably available from this data source and are intentionally left out of
the score rather than faked.
"""

# INR crore bands commonly used for Indian large/mid/small-cap classification.
_CRORE = 10_000_000
LARGE_CAP_FLOOR = 20_000 * _CRORE
MID_CAP_FLOOR = 5_000 * _CRORE

RECOMMENDABLE_SCORE_THRESHOLD = 0.5


def classify_cap_size(market_cap: float | None) -> str | None:
    if market_cap is None:
        return None
    if market_cap >= LARGE_CAP_FLOOR:
        return "large"
    if market_cap >= MID_CAP_FLOOR:
        return "mid"
    return "small"


def score_fundamentals(fundamentals: dict) -> tuple[float, list[str]]:
    """Weighted 0-1 score built only from whatever fields are present - a
    missing field is skipped entirely (neither rewarded nor penalized)
    rather than zeroed, since per-ticker NSE coverage in yfinance is patchy."""
    weighted_total = 0.0
    weight_sum = 0.0
    reasons: list[str] = []

    debt_to_equity = fundamentals.get("debt_to_equity")
    if debt_to_equity is not None:
        ratio = debt_to_equity / 100
        weight_sum += 1
        if ratio < 1:
            weighted_total += 1
            reasons.append(f"Debt/Equity {ratio:.2f} is under the 1x comfort level")
        elif ratio < 2:
            weighted_total += 0.4
            reasons.append(f"Debt/Equity {ratio:.2f} is above 1x")
        else:
            reasons.append(f"Debt/Equity {ratio:.2f} is high (2x or more)")

    peg = fundamentals.get("peg")
    if peg is not None:
        weight_sum += 1
        if 0 < peg <= 1:
            weighted_total += 1
            reasons.append(f"PEG {peg:.2f} suggests growth at a reasonable price")
        elif peg > 1:
            weighted_total += 0.4
            reasons.append(f"PEG {peg:.2f} is over 1 (pricier relative to growth)")
        else:
            reasons.append(f"PEG {peg:.2f} isn't meaningful (flat/negative growth)")

    for label, key in (("Revenue growth", "revenue_growth"), ("Earnings growth", "earnings_growth")):
        value = fundamentals.get(key)
        if value is not None:
            weight_sum += 1
            if value > 0.10:
                weighted_total += 1
                reasons.append(f"{label} is strong ({value * 100:.1f}%)")
            elif value > 0:
                weighted_total += 0.6
                reasons.append(f"{label} is positive ({value * 100:.1f}%)")
            else:
                reasons.append(f"{label} is negative ({value * 100:.1f}%)")

    insider_holding_pct = fundamentals.get("insider_holding_pct")
    if insider_holding_pct is not None:
        weight_sum += 1
        if insider_holding_pct >= 0.3:
            weighted_total += 1
            reasons.append(f"Insider/promoter holding is meaningful ({insider_holding_pct * 100:.1f}%)")
        else:
            weighted_total += 0.5
            reasons.append(f"Insider/promoter holding is modest ({insider_holding_pct * 100:.1f}%)")

    pb = fundamentals.get("pb")
    if pb is not None:
        weight_sum += 1
        if pb <= 5:
            weighted_total += 1
        else:
            weighted_total += 0.3
            reasons.append(f"P/B {pb:.1f} is rich (over 5x book value)")

    if weight_sum == 0:
        return 0.5, ["No fundamentals data available - treated as neutral"]

    return weighted_total / weight_sum, reasons


def is_recommendable(fundamentals: dict) -> tuple[bool, float, list[str]]:
    """A stock clears the standard bar if its weighted score is at or above
    the threshold AND it doesn't trip a hard red flag. A hard flag fails it
    outright regardless of score, but only fires when the data needed to
    check it is actually present - missing data never disqualifies a stock
    on its own."""
    debt_to_equity = fundamentals.get("debt_to_equity")
    if debt_to_equity is not None and debt_to_equity / 100 > 3:
        return False, 0.0, [f"Debt/Equity {debt_to_equity / 100:.2f} is a hard red flag (3x or more)"]

    earnings_growth = fundamentals.get("earnings_growth")
    if earnings_growth is not None and earnings_growth < -0.5:
        return False, 0.0, [f"Earnings growth collapsed ({earnings_growth * 100:.1f}%) - hard red flag"]

    score, reasons = score_fundamentals(fundamentals)
    return score >= RECOMMENDABLE_SCORE_THRESHOLD, score, reasons
