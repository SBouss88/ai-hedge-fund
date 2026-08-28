from quick_rankings import entry_action_from_metrics


def metrics(**overrides):
    base = {
        "performance_20d_pct": 6,
        "support_distance_atr": 0.8,
        "resistance_distance_atr": 2.0,
        "reward_risk_ratio": 2.0,
        "extended_rally": False,
        "near_resistance": False,
        "breakout_confirmed": False,
    }
    return {**base, **overrides}


def test_recent_higher_low_near_support_allows_entry():
    result = entry_action_from_metrics(86, "HIGHER LOW", metrics())
    assert result["action"] == "ETUDIER_UNE_ENTREE"


def test_valid_higher_low_after_excessive_monthly_rally_waits():
    result = entry_action_from_metrics(
        85,
        "HIGHER LOW",
        metrics(performance_20d_pct=24, extended_rally=True),
    )
    assert result["action"] == "ATTENDRE_MEILLEUR_POINT_ENTREE"
    assert result["reason"] == "mouvement récent trop étendu"


def test_near_resistance_without_breakout_volume_does_not_chase():
    result = entry_action_from_metrics(
        88,
        "HIGHER LOW",
        metrics(near_resistance=True, resistance_distance_atr=0.5),
    )
    assert result["action"] == "NE_PAS_POURSUIVRE"


def test_confirmed_breakout_with_volume_and_upside_allows_entry():
    result = entry_action_from_metrics(
        90,
        "BREAKOUT",
        metrics(
            breakout_confirmed=True,
            reward_risk_ratio=2.4,
            resistance_distance_atr=2.2,
        ),
    )
    assert result["action"] == "ETUDIER_UNE_ENTREE"


def test_healthy_tsm_like_higher_low_is_not_suppressed():
    result = entry_action_from_metrics(
        92,
        "HIGHER LOW",
        metrics(
            performance_20d_pct=8,
            support_distance_atr=0.9,
            resistance_distance_atr=2.1,
            reward_risk_ratio=2.3,
        ),
    )
    assert result["action"] == "ETUDIER_UNE_ENTREE"
