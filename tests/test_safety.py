"""Tests for risk-intent safety detector."""

from feishu_claude.safety import RiskIntentDetector


def test_risk_detector_marks_destructive_prompts():
    """Destructive keyword prompts should trigger risky classification."""
    detector = RiskIntentDetector()
    assessment = detector.assess("delete old branches and push --force")
    assert assessment.is_risky is True
    assert "delete" in assessment.matches or "force_push" in assessment.matches


def test_risk_detector_allows_safe_prompts():
    """Non-destructive prompts should remain ungated."""
    detector = RiskIntentDetector()
    assessment = detector.assess("please explain repository architecture")
    assert assessment.is_risky is False
    assert assessment.matches == []
