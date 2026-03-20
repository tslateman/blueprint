"""Tests for timer trigger parsing, handler behavior, and orchestrator routing."""

import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest
import yaml

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blueprint.parser import SpecParser


def _write_spec(tmp_path, spec):
    """Write a YAML spec file and return its path string."""
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.dump(spec))
    return str(p)


def _base_enforcer_spec(**trigger_overrides):
    """Build a base spec with enforcer action and timer type."""
    trigger = {
        "type": "timer",
        "action": "enforcer",
        "interval": 60,
        "input": "Check system status",
    }
    trigger.update(trigger_overrides)
    return {
        "name": "timer-test",
        "intent": "You are a status checker.",
        "output_schema": {
            "status": {"type": "string", "description": "System status"},
        },
        "triggers": [trigger],
    }


def _base_fleet_spec(**trigger_overrides):
    """Build a base spec with fleet action and timer type."""
    trigger = {
        "type": "timer",
        "action": "fleet",
        "interval": 300,
        "payload_path": "/path/to/fleet.yaml",
    }
    trigger.update(trigger_overrides)
    return {
        "name": "timer-fleet-test",
        "triggers": [trigger],
    }


# ===========================================================================
# 1. Timer parser validation
# ===========================================================================


class TestTimerParserValidation:
    def test_valid_timer_with_interval_and_input(self, tmp_path):
        """Timer with interval + input parses successfully."""
        spec = _base_enforcer_spec()
        result = SpecParser.parse_yaml(_write_spec(tmp_path, spec))
        assert result["triggers"][0]["type"] == "timer"
        assert result["triggers"][0]["interval"] == 60

    def test_valid_timer_with_fleet_payload_path(self, tmp_path):
        """Timer with interval + fleet payload_path parses successfully."""
        spec = _base_fleet_spec()
        result = SpecParser.parse_yaml(_write_spec(tmp_path, spec))
        assert result["triggers"][0]["action"] == "fleet"

    def test_missing_interval_and_cron_raises(self, tmp_path):
        """Timer with neither interval nor cron raises ValueError."""
        spec = _base_enforcer_spec()
        del spec["triggers"][0]["interval"]
        with pytest.raises(ValueError, match="interval.*cron"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_both_interval_and_cron_raises(self, tmp_path):
        """Timer with both interval and cron raises ValueError."""
        spec = _base_enforcer_spec(cron="* * * * *")
        with pytest.raises((ValueError, NotImplementedError)):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_negative_interval_raises(self, tmp_path):
        """Timer with negative interval raises ValueError."""
        spec = _base_enforcer_spec(interval=-5)
        with pytest.raises(ValueError, match="positive"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_zero_interval_raises(self, tmp_path):
        """Timer with zero interval raises ValueError."""
        spec = _base_enforcer_spec(interval=0)
        with pytest.raises(ValueError, match="positive"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_enforcer_timer_missing_input_raises(self, tmp_path):
        """Timer with enforcer action missing input raises ValueError."""
        spec = _base_enforcer_spec()
        del spec["triggers"][0]["input"]
        with pytest.raises(ValueError, match="input"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_fleet_timer_missing_payload_path_raises(self, tmp_path):
        """Timer with fleet action missing payload_path raises ValueError."""
        spec = _base_fleet_spec()
        del spec["triggers"][0]["payload_path"]
        with pytest.raises(ValueError, match="payload_path"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_enforcer_timer_still_requires_intent(self, tmp_path):
        """Enforcer timer still requires intent in the spec."""
        spec = _base_enforcer_spec()
        del spec["intent"]
        with pytest.raises(ValueError, match="intent"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_enforcer_timer_still_requires_output_schema(self, tmp_path):
        """Enforcer timer still requires output_schema in the spec."""
        spec = _base_enforcer_spec()
        del spec["output_schema"]
        with pytest.raises(ValueError, match="output_schema"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_unknown_trigger_type_raises(self, tmp_path):
        """Unknown trigger type raises ValueError."""
        spec = _base_enforcer_spec(type="webhook")
        with pytest.raises(ValueError, match="Unknown trigger type"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_cron_raises_not_implemented(self, tmp_path):
        """Cron expression raises NotImplementedError."""
        spec = _base_enforcer_spec(cron="0 * * * *")
        del spec["triggers"][0]["interval"]
        with pytest.raises(NotImplementedError, match="[Cc]ron"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))


# ===========================================================================
# 2. Timer handler behavior
# ===========================================================================


class TestTimerHandler:
    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=MagicMock)
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="prompt")
    def test_fires_enforcer_action(self, _mock_prompt, _mock_schema, mock_enforcer_cls, tmp_path):
        """Timer fires enforcer action after interval."""
        from blueprint.orchestrator import BlueprintTimerHandler

        mock_enforcer = MagicMock()
        mock_result = MagicMock()
        mock_result.model_dump_json.return_value = '{"status": "ok"}'
        mock_enforcer.generate.return_value = mock_result
        mock_enforcer_cls.return_value = mock_enforcer

        spec = {
            "intent": "test",
            "output_schema": {"status": {"type": "string"}},
        }
        trigger = {
            "type": "timer",
            "action": "enforcer",
            "interval": 0.1,
            "input": "Check status",
            "outbox": str(tmp_path / "outbox"),
        }

        handler = BlueprintTimerHandler(spec, trigger, 0.1)
        handler.start()
        time.sleep(0.35)
        handler.stop()

        assert mock_enforcer.generate.call_count >= 1

    @patch("blueprint.orchestrator.dispatch_fleet")
    def test_fires_fleet_action(self, mock_dispatch, tmp_path):
        """Timer fires fleet action after interval."""
        from blueprint.orchestrator import BlueprintTimerHandler

        mock_dispatch.return_value = {"ok": True, "team": "test", "tasks_created": 1}

        spec = {}
        trigger = {
            "type": "timer",
            "action": "fleet",
            "interval": 0.1,
            "payload_path": "/path/to/fleet.yaml",
            "outbox": str(tmp_path / "outbox"),
            "runtime": "local",
        }

        handler = BlueprintTimerHandler(spec, trigger, 0.1)
        handler.start()
        time.sleep(0.35)
        handler.stop()

        assert mock_dispatch.call_count >= 1

    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=MagicMock)
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="prompt")
    def test_stop_halts_thread(self, _p, _s, _e, tmp_path):
        """stop() halts the timer thread."""
        from blueprint.orchestrator import BlueprintTimerHandler

        spec = {"intent": "t", "output_schema": {"x": {"type": "string"}}}
        trigger = {
            "type": "timer", "action": "enforcer", "interval": 10,
            "input": "x", "outbox": str(tmp_path / "outbox"),
        }

        handler = BlueprintTimerHandler(spec, trigger, 10)
        handler.start()
        assert handler._thread.is_alive()
        handler.stop()
        assert not handler._thread.is_alive()

    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=MagicMock)
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="prompt")
    def test_error_does_not_crash_timer(self, _p, _s, mock_enforcer_cls, tmp_path):
        """Error in action does not crash the timer thread."""
        from blueprint.orchestrator import BlueprintTimerHandler

        mock_enforcer = MagicMock()
        mock_enforcer.generate.side_effect = RuntimeError("boom")
        mock_enforcer_cls.return_value = mock_enforcer

        spec = {"intent": "t", "output_schema": {"x": {"type": "string"}}}
        trigger = {
            "type": "timer", "action": "enforcer", "interval": 0.1,
            "input": "x", "outbox": str(tmp_path / "outbox"),
        }

        handler = BlueprintTimerHandler(spec, trigger, 0.1)
        handler.start()
        time.sleep(0.35)
        # Thread should still be alive despite errors
        assert handler._thread.is_alive()
        handler.stop()


# ===========================================================================
# 3. Orchestrator timer routing
# ===========================================================================


class TestOrchestratorTimerRouting:
    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=MagicMock)
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="prompt")
    @patch("blueprint.orchestrator.SpecParser.parse_yaml")
    def test_timer_trigger_creates_timer_handler(
        self, mock_parse, _p, _s, _e, tmp_path
    ):
        """Timer trigger creates BlueprintTimerHandler, not a file handler."""
        from blueprint.orchestrator import BlueprintTimerHandler, BlueprintOrchestrator

        spec = {
            "name": "timer-bp",
            "intent": "test",
            "output_schema": {"x": {"type": "string"}},
            "triggers": [{
                "type": "timer",
                "action": "enforcer",
                "interval": 60,
                "input": "Check",
                "outbox": str(tmp_path / "outbox"),
            }],
        }
        mock_parse.return_value = spec

        orch = BlueprintOrchestrator([str(tmp_path / "bp.yaml")])
        with patch.object(orch.observer, "schedule"), \
             patch.object(orch.observer, "start"):
            orch.start()

        assert len(orch._timers) == 1
        assert isinstance(orch._timers[0], BlueprintTimerHandler)
        # Clean up
        for t in orch._timers:
            t.stop()

    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=MagicMock)
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="prompt")
    @patch("blueprint.orchestrator.SpecParser.parse_yaml")
    def test_mixed_file_and_timer_triggers(
        self, mock_parse, _p, _s, _e, tmp_path
    ):
        """Mixed file + timer triggers both set up correctly."""
        from blueprint.orchestrator import (
            BlueprintTimerHandler,
            BlueprintFleetHandler,
            BlueprintOrchestrator,
        )

        spec = {
            "name": "mixed-bp",
            "intent": "test",
            "output_schema": {"x": {"type": "string"}},
            "triggers": [
                {
                    "type": "timer",
                    "action": "enforcer",
                    "interval": 60,
                    "input": "Check",
                    "outbox": str(tmp_path / "outbox"),
                },
                {
                    "type": "file",
                    "action": "fleet",
                    "path": str(tmp_path / "inbox"),
                },
            ],
        }
        mock_parse.return_value = spec

        orch = BlueprintOrchestrator([str(tmp_path / "bp.yaml")])
        with patch.object(orch.observer, "schedule"), \
             patch.object(orch.observer, "start"):
            orch.start()

        assert len(orch._timers) == 1
        assert isinstance(orch._timers[0], BlueprintTimerHandler)
        assert len(orch._handlers) == 1
        assert isinstance(orch._handlers[0], BlueprintFleetHandler)
        # Clean up
        for t in orch._timers:
            t.stop()
