from valuation import (
    collect_metrics,
    finalize_score,
    valuation_label,
)


def info_template(**overrides):
    data = {
        "forwardPE": 25,
        "forwardEps": 4,
        "trailingPE": 30,
        "trailingEps": 3.5,
        "revenueGrowth": 0.20,
        "earningsGrowth": 0.25,
        "priceToSalesTrailing12Months": 8,
        "enterpriseToRevenue": 8,
        "freeCashflow": 5,
        "marketCap": 100,
        "currency": "USD",
        "financialCurrency": "USD",
    }
    data.update(overrides)
    return data


def test_new_labels_describe_premium_instead_of_absolute_expensiveness():
    assert valuation_label(90) == "TRÈS ATTRACTIVE"
    assert valuation_label(72) == "ATTRACTIVE"
    assert valuation_label(60) == "RAISONNABLE"
    assert valuation_label(45) == "PRIME MODÉRÉE"
    assert valuation_label(25) == "PRIME ÉLEVÉE"


def test_own_history_rewards_current_multiple_below_company_median():
    item = collect_metrics(
        "NVDA",
        info_template(trailingPE=24),
        {"price": 100, "price_date": "2026-08-21"},
        historical_pe_samples=[{"pe": 40}, {"pe": 44}, {"pe": 48}],
        fx_rate=1,
    )
    component = item["components"]["own_history"]
    assert component["available"] is True
    assert component["score"] == 100
    assert item["metrics"]["historical_pe_median"] == 44


def test_peer_comparison_uses_relevant_group_and_excludes_company_itself():
    nvda = collect_metrics("NVDA", info_template(forwardPE=20, forwardEps=None))
    amd = collect_metrics("AMD", info_template(forwardPE=40, forwardEps=None))
    avgo = collect_metrics("AVGO", info_template(forwardPE=30, forwardEps=None))
    peers = [nvda, amd, avgo]
    finalize_score(nvda, peers)
    finalize_score(amd, peers)
    assert nvda["metrics"]["peer_median"] == 35
    assert nvda["components"]["peers"]["score"] == 100
    assert amd["metrics"]["peer_median"] == 25
    assert amd["components"]["peers"]["score"] == 25


def test_extreme_short_term_earnings_growth_is_rejected():
    item = collect_metrics(
        "NVDA",
        info_template(earningsGrowth=2.94, revenueGrowth=0.22),
    )
    assert item["metrics"]["growth_rate_used"] == 0.22
    assert item["metrics"]["growth_source"] == "revenueGrowth"


def test_coverage_reports_missing_history_and_peers_instead_of_hiding_them():
    item = collect_metrics(
        "NBIS",
        info_template(forwardPE=None, forwardEps=None, trailingPE=None),
    )
    finalize_score(item, [item])
    assert item["coverage_pct"] == 35
    assert item["confidence"] == "LOW"


def test_too_little_coverage_returns_unavailable():
    item = collect_metrics(
        "NBIS",
        info_template(
            forwardPE=None,
            forwardEps=None,
            trailingPE=None,
            revenueGrowth=None,
            earningsGrowth=None,
            freeCashflow=None,
        ),
    )
    finalize_score(item, [item])
    assert item["score"] is None
    assert item["label"] == "INDISPONIBLE"


def test_memory_cycle_cannot_look_very_attractive_without_normalized_growth():
    mu = collect_metrics(
        "MU",
        info_template(
            forwardPE=6,
            forwardEps=None,
            revenueGrowth=1.2,
            earningsGrowth=3.0,
        ),
        historical_pe_samples=[{"pe": 25}, {"pe": 30}, {"pe": 35}],
    )
    nvda = collect_metrics("NVDA", info_template(forwardPE=18, forwardEps=None))
    amd = collect_metrics("AMD", info_template(forwardPE=24, forwardEps=None))
    finalize_score(mu, [mu, nvda, amd])
    assert mu["score"] <= 69
    assert "cyclique" in " ".join(mu["risk_flags"])


def test_foreign_currency_cashflow_is_used_after_conversion():
    item = collect_metrics(
        "ASML",
        info_template(
            currency="USD",
            financialCurrency="EUR",
            freeCashflow=100,
            marketCap=200,
        ),
        fx_rate=1.2,
    )
    assert item["metrics"]["fcf_yield"] == 0.6
    assert item["components"]["cash_flow"]["available"] is True
