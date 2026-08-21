import pandas as pd

from quick_rankings import higher_low_trigger, setup_invalidation
from technical_signal_validation import evaluate_outcome, percent_change, signal_in_window


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
