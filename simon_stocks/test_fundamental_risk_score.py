import fundamental_risk_score as scoring
from fundamental_risk_score import apply_approved_calibration


def sample_item(score=83):
    return {
        "ticker": "TSM",
        "score": score,
        "category": "B",
        "max_exposure_usd": 10000,
        "criteria": {
            "moat": {"score": 24, "max": 25},
            "financial_strength": {"score": 24, "max": 25, "metrics": {}},
            "diversification": {"score": 15, "max": 20},
            "competitive_resilience": {"score": 13, "max": 15},
            "specific_risk_resilience": {"score": 7, "max": 15},
        },
    }


def calibration(version=1):
    return {
        "version": version,
        "approved_at": "2026-08-26",
        "approved_score": 85,
        "reason": "Suppression du double comptage.",
        "criteria": {
            "moat": {"score": 24},
            "financial_strength": {"score": 24},
            "diversification": {"score": 16},
            "competitive_resilience": {"score": 13},
            "specific_risk_resilience": {"score": 8},
        },
    }


def test_approved_calibration_restores_score_category_and_maximum():
    result = apply_approved_calibration(sample_item(), calibration())
    assert result["score"] == 85
    assert result["category"] == "A"
    assert result["max_exposure_usd"] == 15000
    assert result["calibration"]["status"] == "APPLIED"


def test_material_trigger_expires_calibration_and_keeps_new_assessment():
    result = apply_approved_calibration(
        sample_item(score=82),
        calibration(),
        ["nouvel événement matériel : résultats trimestriels"],
    )
    assert result["score"] == 82
    assert result["calibration"]["status"] == "EXPIRED_ON_MATERIAL_TRIGGER"


def test_first_assessment_still_uses_approved_calibration():
    result = apply_approved_calibration(
        sample_item(),
        calibration(),
        ["première évaluation"],
    )
    assert result["score"] == 85


def test_new_calibration_version_can_replace_an_expired_one():
    item = sample_item(score=82)
    item["calibration"] = {
        "status": "EXPIRED_ON_MATERIAL_TRIGGER",
        "version": 1,
    }
    result = apply_approved_calibration(item, calibration(version=2))
    assert result["score"] == 85
    assert result["calibration"]["version"] == 2


def test_button_workflow_persists_calibration_without_openai(monkeypatch):
    previous = sample_item()
    payload = {"items": [previous], "usage": {"input": 99, "output": 99}}
    snapshot = {
        "ticker": "TSM",
        "financial_strength": {"score": 24},
        "recent_public_headlines": [],
    }
    monkeypatch.setattr(scoring, "company_snapshot", lambda ticker: snapshot)
    monkeypatch.setattr(
        scoring,
        "load_previous_scores",
        lambda: ({"TSM": previous}, payload),
    )
    monkeypatch.setattr(
        scoring,
        "load_calibrations",
        lambda: {"TSM": calibration()},
    )

    result = scoring.build_scores(["TSM"])

    assert result["items"][0]["score"] == 85
    assert result["reassessment_status"] == "APPROVED_CALIBRATION_APPLIED"
    assert result["usage"] == {"input": 0, "output": 0}
    assert result["_unchanged"] is False
