from signal_journal import eligibility, execution_check


def eligible_inputs():
    return (
        {"score": 70, "setup_type": "HIGHER LOW"},
        {"score": 80, "max_exposure_usd": 10000},
        {"label": "REASONABLE"},
        {"days_until": 30},
    )


def test_eligibility_requires_all_four_dimensions():
    eligible, blockers = eligibility(*eligible_inputs())
    assert eligible
    assert blockers == []


def test_eligibility_blocks_unconfirmed_technical_setup():
    technical, fundamental, valuation, earnings = eligible_inputs()
    technical["setup_type"] = "HIGHER LOW À CONFIRMER"
    eligible, blockers = eligibility(
        technical,
        fundamental,
        valuation,
        earnings,
    )
    assert not eligible
    assert "TECHNIQUE_NON_CONFIRMÉE" in blockers


def test_execution_is_cancelled_when_opening_gap_exceeds_two_percent():
    result = execution_check(
        {"reference_price": 100, "invalidation": {"level": 95}},
        {"open": 103},
    )
    assert result["status"] == "ANNULER_GAP"
    assert result["gap_pct"] == 3.0


def test_execution_is_cancelled_below_invalidation():
    result = execution_check(
        {"reference_price": 100, "invalidation": {"level": 95}},
        {"open": 94},
    )
    assert result["status"] == "ANNULER_INVALIDATION"
