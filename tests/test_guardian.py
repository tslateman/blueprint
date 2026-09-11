"""Tests for the Guardian's self-healing path."""

from unittest.mock import MagicMock, patch

from blueprint.guardian import BlueprintGuardian


def test_trigger_self_healing_reaches_confidence_check():
    guardian = BlueprintGuardian.__new__(BlueprintGuardian)
    guardian.enforcer = MagicMock()
    guardian.enforcer.generate.return_value = MagicMock(
        error_analysis="analysis",
        rationale="rationale",
        confidence_score=10,
    )

    healer_spec = {
        "intent": "You are a test healer.",
        "output_schema": {
            "confidence_score": {"type": "integer", "description": "Confidence"},
        },
    }
    with patch("blueprint.guardian.SpecParser.parse_yaml", return_value=healer_spec):
        guardian._trigger_self_healing("blueprints/MISSING_ESSENTIAL_SPEC.yaml", "boom")

    guardian.enforcer.generate.assert_called_once()
