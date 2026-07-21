from app.fundamentals import classify_cap_size, is_recommendable, score_fundamentals


def test_classify_cap_size_bands():
    assert classify_cap_size(None) is None
    assert classify_cap_size(4_000 * 10_000_000) == "small"
    assert classify_cap_size(10_000 * 10_000_000) == "mid"
    assert classify_cap_size(50_000 * 10_000_000) == "large"


def test_no_data_scores_neutral():
    score, reasons = score_fundamentals({})
    assert score == 0.5
    assert reasons


def test_healthy_stock_scores_high():
    fundamentals = {
        "debt_to_equity": 40.0,  # 0.4x
        "peg": 0.8,
        "revenue_growth": 0.15,
        "earnings_growth": 0.20,
        "insider_holding_pct": 0.55,
        "pb": 3.0,
    }
    score, _ = score_fundamentals(fundamentals)
    assert score > 0.9

    recommendable, recommend_score, _ = is_recommendable(fundamentals)
    assert recommendable is True
    assert recommend_score == score


def test_weak_stock_scores_low():
    fundamentals = {
        "debt_to_equity": 250.0,  # 2.5x
        "peg": 3.5,
        "revenue_growth": -0.05,
        "earnings_growth": -0.10,
        "insider_holding_pct": 0.05,
        "pb": 9.0,
    }
    recommendable, score, _ = is_recommendable(fundamentals)
    assert recommendable is False
    assert score < 0.5


def test_hard_red_flag_debt_to_equity_overrides_score():
    fundamentals = {"debt_to_equity": 350.0}  # 3.5x - hard flag, regardless of everything else missing
    recommendable, score, reasons = is_recommendable(fundamentals)
    assert recommendable is False
    assert score == 0.0
    assert "red flag" in reasons[0]


def test_hard_red_flag_earnings_collapse_overrides_score():
    fundamentals = {"earnings_growth": -0.6}
    recommendable, score, reasons = is_recommendable(fundamentals)
    assert recommendable is False
    assert score == 0.0


def test_missing_fields_never_disqualify_on_their_own():
    fundamentals = {"peg": 0.5}
    recommendable, score, _ = is_recommendable(fundamentals)
    assert recommendable is True
    assert score == 1.0
