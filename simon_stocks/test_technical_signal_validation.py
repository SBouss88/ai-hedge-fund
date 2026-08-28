import pandas as pd

from quick_rankings import higher_low_trigger, setup_invalidation
from technical_signal_validation import (
    entry_filter_passes,
    evaluate_outcome,
    percent_change,
    signal_in_window,
    summarize_entry_filter,
)


def price_frame(rows):
    return pd.DataFrame(
        rows,
        columns=["Open", "High", "Low", "Close", "Volume"],
        index=pd.date_range("2026-01-01", periods=len(rows), freq="B"),
    )


def test_higher_low_waits_without_price_confirmation():
    frame = price_frame(
        [
            (100, 102, 99, 101, 1000),
            (101, 103, 100, 102, 1000),
            (102, 103, 99, 100, 1000),
        ]
    )
    points, detail, setup_type = higher_low_trigger(
        frame,
        {"score": 15, "change": 4.0, "age": 5, "distance": 2.0},
    )
    assert points == 5
    assert "À CONFIRMER" in setup_type
    assert "reprise" in detail


def test_higher_low_requires_a_strong_close_above_previous_high():
    frame = price_frame(
        [
            (100, 102, 99, 101, 1000),
            (101, 103, 100, 101, 1000),
            (101, 105, 101, 104, 1200),
        ]
    )
    points, _, setup_type = higher_low_trigger(
        frame,
        {"score": 15, "change": 4.0, "age": 5, "distance": 3.0},
    )
    assert points == 15
    assert setup_type == "HIGHER LOW"


def test_outcome_reports_return_drawdown_and_reward_risk():
    frame = price_frame([(100, 101, 99, 100, 1000)] + [(100, 112, 95, 110, 1000)] * 10)
    outcome = evaluate_outcome(frame, 0, 10)
    assert outcome == {
        "entry_date": "2026-01-02",
        "entry_price": 100.0,
        "return_pct": 10.0,
        "max_favorable_pct": 12.0,
        "max_drawdown_pct": -5.0,
        "reward_risk": 2.4,
    }


def test_entry_gap_is_measured_from_signal_close_to_next_open():
    assert round(percent_change(103, 100), 1) == 3.0


def test_signal_window_uses_the_signal_date():
    signal = {"date": "2026-02-20"}
    assert signal_in_window(signal, pd.Timestamp("2026-02-20").date())
    assert not signal_in_window(signal, pd.Timestamp("2026-02-21").date())


def test_setup_invalidation_uses_the_setup_specific_level():
    invalidation = setup_invalidation(
        "BREAKOUT",
        {"level": 98.0},
        {},
        100.0,
    )
    assert invalidation == {
        "level": 98.0,
        "distance_pct": -2.0,
        "rule": "Clôture de retour sous le niveau de breakout",
    }


def test_entry_filter_keeps_signal_detection_separate_from_entry_timing():
    item = {
        "score": 85,
        "setup_type": "HIGHER LOW",
        "entry_quality": {
            "action": "ATTENDRE_MEILLEUR_POINT_ENTREE",
            "reason": "mouvement récent trop étendu",
        },
    }
    assert entry_filter_passes(item) is False

    item["entry_quality"]["action"] = "ETUDIER_UNE_ENTREE"
    assert entry_filter_passes(item) is True


def test_entry_filter_summary_compares_retained_and_rejected_signals():
    outcome = {
        "return_pct": 5.0,
        "max_drawdown_pct": -2.0,
        "reward_risk": 2.0,
    }
    signals = [
        {
            "outcome_20d": outcome,
            "successful_20d": True,
            "clean_successful_20d": True,
            "execution_allowed": True,
            "new_leg": True,
            "entry_filter_passes": True,
            "entry_quality": {"reason": "signal confirmé"},
        },
        {
            "outcome_20d": outcome,
            "successful_20d": True,
            "clean_successful_20d": True,
            "execution_allowed": True,
            "new_leg": True,
            "entry_filter_passes": False,
            "entry_quality": {"reason": "mouvement récent trop étendu"},
        },
    ]

    comparison = summarize_entry_filter(signals)

    assert comparison["baseline_technical_signal"]["completed_20d"] == 2
    assert comparison["with_entry_quality_filter"]["completed_20d"] == 1
    assert comparison["signal_retention_rate_pct"] == 50.0
    assert comparison["rejection_reasons"] == {
        "mouvement récent trop étendu": 1
    }
