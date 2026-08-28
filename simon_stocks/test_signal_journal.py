from signal_journal import eligibility, execution_check, merge_session_records


def eligible_inputs():
    return (
        {
            "score": 85,
            "setup_type": "HIGHER LOW",
            "entry_quality": {"action": "ETUDIER_UNE_ENTREE"},
        },
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


def test_eligibility_preserves_signal_but_blocks_bad_entry_timing():
    technical, fundamental, valuation, earnings = eligible_inputs()
    technical["entry_quality"] = {
        "action": "ATTENDRE_MEILLEUR_POINT_ENTREE"
    }
    eligible, blockers = eligibility(
        technical,
        fundamental,
        valuation,
        earnings,
    )
    assert not eligible
    assert "POINT_ENTRÉE_NON_FAVORABLE" in blockers


def test_same_session_record_is_replaced_instead_of_duplicated():
    prior = [{"ticker": "MSFT", "technical_as_of": "2026-08-27", "score": 47}]
    current = [{"ticker": "MSFT", "technical_as_of": "2026-08-27", "score": 67}]
    merged = merge_session_records(prior, current)
    assert len(merged) == 1
    assert merged[0]["score"] == 67
