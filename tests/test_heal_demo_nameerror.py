from unittest.mock import MagicMock

from blueprint.guardian import BlueprintGuardian


def test_trigger_self_healing_reaches_enforcer_generate():
    guardian = BlueprintGuardian.__new__(BlueprintGuardian)
    guardian.blueprint_paths = ["blueprints/MISSING_ESSENTIAL_SPEC.yaml"]
    guardian.enforcer = MagicMock()
    guardian.enforcer.generate.return_value = MagicMock(
        error_analysis="",
        rationale="",
        confidence_score=0,
    )

    guardian._trigger_self_healing(
        "blueprints/MISSING_ESSENTIAL_SPEC.yaml", "spec file not found"
    )

    guardian.enforcer.generate.assert_called_once()
