"""Tests for fleet dispatch: payload validation, topo sort, dispatch, parser, and orchestrator routing."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

# Ensure the project root is on sys.path so `blueprint` is importable.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blueprint.fleet_dispatch import dispatch_fleet, topo_sort, validate_payload
from blueprint.parser import SpecParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(team="test-team", tasks=None):
    """Build a minimal valid payload dict."""
    if tasks is None:
        tasks = [
            {"name": "a", "title": "Task A", "agent_type": "coder"},
            {"name": "b", "title": "Task B", "agent_type": "reviewer"},
        ]
    return {"team": team, "tasks": tasks}


def _ok_result(args, **_kwargs):
    """Generic subprocess.run mock that succeeds with JSON stdout."""
    if "task" in args and "create" in args:
        try:
            idx = args.index("--title")
            title = args[idx + 1]
        except (ValueError, IndexError):
            title = "unknown"
        name = title.lower().replace(" ", "-")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"task_id": f"task-{name}-001", "ok": True}),
            stderr="",
        )
    # team create or drive
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")


def _write_payload(tmp_path, payload):
    """Write a YAML payload file and return its path string."""
    p = tmp_path / "dispatch.yaml"
    p.write_text(yaml.dump(payload))
    return str(p)


def _write_spec(tmp_path, spec):
    """Write a YAML spec file and return its path string."""
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.dump(spec))
    return str(p)


# ===========================================================================
# 1. Payload validation
# ===========================================================================


class TestValidatePayload:
    def test_valid_payload(self):
        validate_payload(_make_payload())

    def test_missing_team(self):
        with pytest.raises(ValueError, match="team"):
            validate_payload(
                {"tasks": [{"name": "a", "title": "A", "agent_type": "x"}]}
            )

    def test_missing_tasks(self):
        with pytest.raises(ValueError, match="tasks"):
            validate_payload({"team": "t"})

    def test_empty_tasks(self):
        with pytest.raises(ValueError, match="tasks"):
            validate_payload({"team": "t", "tasks": []})

    def test_task_missing_name(self):
        with pytest.raises(ValueError, match="name"):
            validate_payload(
                {"team": "t", "tasks": [{"title": "A", "agent_type": "x"}]}
            )

    def test_task_missing_title(self):
        with pytest.raises(ValueError, match="title"):
            validate_payload({"team": "t", "tasks": [{"name": "a", "agent_type": "x"}]})

    def test_task_missing_agent_type(self):
        with pytest.raises(ValueError, match="agent_type"):
            validate_payload({"team": "t", "tasks": [{"name": "a", "title": "A"}]})

    def test_duplicate_task_names(self):
        tasks = [
            {"name": "dup", "title": "First", "agent_type": "x"},
            {"name": "dup", "title": "Second", "agent_type": "y"},
        ]
        with pytest.raises(ValueError, match="Duplicate task name"):
            validate_payload({"team": "t", "tasks": tasks})

    def test_depends_on_nonexistent_task(self):
        tasks = [
            {"name": "a", "title": "A", "agent_type": "x", "depends_on": ["ghost"]},
        ]
        with pytest.raises(ValueError, match="unknown task.*ghost"):
            validate_payload({"team": "t", "tasks": tasks})


# ===========================================================================
# 2. Topological sort
# ===========================================================================


class TestTopoSort:
    def test_independent_tasks_preserve_order(self):
        tasks = [
            {"name": "x", "title": "X", "agent_type": "a"},
            {"name": "y", "title": "Y", "agent_type": "a"},
        ]
        result = topo_sort(tasks)
        assert [t["name"] for t in result] == ["x", "y"]

    def test_linear_chain(self):
        tasks = [
            {"name": "c", "title": "C", "agent_type": "a", "depends_on": ["b"]},
            {"name": "b", "title": "B", "agent_type": "a", "depends_on": ["a"]},
            {"name": "a", "title": "A", "agent_type": "a"},
        ]
        result = topo_sort(tasks)
        names = [t["name"] for t in result]
        assert names.index("a") < names.index("b") < names.index("c")

    def test_diamond_dependency(self):
        tasks = [
            {"name": "d", "title": "D", "agent_type": "a", "depends_on": ["b", "c"]},
            {"name": "b", "title": "B", "agent_type": "a", "depends_on": ["a"]},
            {"name": "c", "title": "C", "agent_type": "a", "depends_on": ["a"]},
            {"name": "a", "title": "A", "agent_type": "a"},
        ]
        result = topo_sort(tasks)
        names = [t["name"] for t in result]
        assert names.index("a") < names.index("b")
        assert names.index("a") < names.index("c")
        assert names.index("b") < names.index("d")
        assert names.index("c") < names.index("d")

    def test_cycle_raises(self):
        tasks = [
            {"name": "a", "title": "A", "agent_type": "x", "depends_on": ["b"]},
            {"name": "b", "title": "B", "agent_type": "x", "depends_on": ["a"]},
        ]
        with pytest.raises(ValueError, match="Cycle"):
            topo_sort(tasks)


# ===========================================================================
# 3. Fleet dispatch (mock subprocess.run)
# ===========================================================================


class TestDispatchFleet:
    @patch("blueprint.fleet_dispatch.subprocess.run", side_effect=_ok_result)
    def test_two_independent_tasks(self, mock_run, tmp_path):
        """Two independent tasks: team create + 2 task creates + 2 drives."""
        path = _write_payload(tmp_path, _make_payload())
        outbox = str(tmp_path / "outbox")

        result = dispatch_fleet(path, outbox, "local")

        assert result["ok"] is True
        assert result["tasks_created"] == 2
        assert result["tasks_driven"] == 2

        # Verify call pattern: team create, 2x task create, 2x drive
        calls = mock_run.call_args_list
        fl_cmds = [c.args[0] for c in calls if c.args[0][0] == "fl"]
        assert fl_cmds[0][1:3] == ["team", "create"]
        task_creates = [c for c in fl_cmds if c[1:3] == ["task", "create"]]
        drives = [c for c in fl_cmds if c[1] == "drive"]
        assert len(task_creates) == 2
        assert len(drives) == 2

    @patch("blueprint.fleet_dispatch.subprocess.run", side_effect=_ok_result)
    def test_dependent_task_not_driven(self, _mock_run, tmp_path):
        """Task B depends on A: only A is driven."""
        tasks = [
            {"name": "a", "title": "Task A", "agent_type": "coder"},
            {
                "name": "b",
                "title": "Task B",
                "agent_type": "reviewer",
                "depends_on": ["a"],
            },
        ]
        path = _write_payload(tmp_path, _make_payload(tasks=tasks))
        outbox = str(tmp_path / "outbox")

        result = dispatch_fleet(path, outbox, "local")

        assert result["ok"] is True
        assert result["tasks_created"] == 2
        assert result["tasks_driven"] == 1

    def test_team_create_fails_aborts(self, tmp_path):
        """Team create fails (non-duplicate): aborts, returns ok=False."""

        def fail_team(args, **_kw):
            if "team" in args and "create" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout="", stderr="permission denied"
                )
            return _ok_result(args)

        with patch("blueprint.fleet_dispatch.subprocess.run", side_effect=fail_team):
            path = _write_payload(tmp_path, _make_payload())
            outbox = str(tmp_path / "outbox")

            result = dispatch_fleet(path, outbox, "local")

        assert result["ok"] is False
        assert any("team create failed" in e for e in result["errors"])

    def test_team_create_already_exists_continues(self, tmp_path):
        """Team create fails with 'already exists': continues normally."""

        def already_exists(args, **_kw):
            if "team" in args and "create" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout="", stderr="team already exists"
                )
            return _ok_result(args)

        with patch(
            "blueprint.fleet_dispatch.subprocess.run", side_effect=already_exists
        ):
            path = _write_payload(tmp_path, _make_payload())
            outbox = str(tmp_path / "outbox")

            result = dispatch_fleet(path, outbox, "local")

        assert result["ok"] is True
        assert result["tasks_created"] == 2

    def test_task_create_fails_partial(self, tmp_path):
        """Task create fails on second task: partial result with correct count."""
        call_count = {"task_creates": 0}

        def fail_second_task(args, **_kw):
            if "task" in args and "create" in args:
                call_count["task_creates"] += 1
                if call_count["task_creates"] == 2:
                    return subprocess.CompletedProcess(
                        args=args, returncode=1, stdout="", stderr="quota exceeded"
                    )
            return _ok_result(args)

        with patch(
            "blueprint.fleet_dispatch.subprocess.run", side_effect=fail_second_task
        ):
            path = _write_payload(tmp_path, _make_payload())
            outbox = str(tmp_path / "outbox")

            result = dispatch_fleet(path, outbox, "local")

        assert result["ok"] is False
        assert result["tasks_created"] == 1
        assert any("task create failed" in e for e in result["errors"])

    def test_drive_fails_others_still_driven(self, tmp_path):
        """Drive fails for one task: other independent tasks still driven."""
        tasks = [
            {"name": "a", "title": "Task A", "agent_type": "coder"},
            {"name": "b", "title": "Task B", "agent_type": "coder"},
            {"name": "c", "title": "Task C", "agent_type": "coder"},
        ]
        drive_count = {"n": 0}

        def fail_first_drive(args, **_kw):
            if args[0] == "fl" and len(args) > 1 and args[1] == "drive":
                drive_count["n"] += 1
                if drive_count["n"] == 1:
                    return subprocess.CompletedProcess(
                        args=args, returncode=1, stdout="", stderr="agent offline"
                    )
            return _ok_result(args)

        with patch(
            "blueprint.fleet_dispatch.subprocess.run", side_effect=fail_first_drive
        ):
            path = _write_payload(tmp_path, _make_payload(tasks=tasks))
            outbox = str(tmp_path / "outbox")

            result = dispatch_fleet(path, outbox, "local")

        # 1 drive failed, 2 succeeded -- ok is False because errors list is non-empty
        assert result["ok"] is False
        assert result["tasks_driven"] == 2
        assert result["tasks_created"] == 3

    @patch("blueprint.fleet_dispatch.subprocess.run", side_effect=_ok_result)
    def test_result_yaml_written_to_outbox(self, _mock_run, tmp_path):
        """Result YAML written to outbox with correct structure."""
        path = _write_payload(tmp_path, _make_payload())
        outbox = str(tmp_path / "outbox")

        dispatch_fleet(path, outbox, "local")

        result_files = list((tmp_path / "outbox").glob("*_result.yaml"))
        assert len(result_files) == 1

        with open(result_files[0]) as f:
            written = yaml.safe_load(f)

        assert "ok" in written
        assert "team" in written
        assert "tasks_created" in written
        assert "tasks_driven" in written
        assert "task_ids" in written
        assert "errors" in written
        assert written["ok"] is True


# ===========================================================================
# 4. Parser validation
# ===========================================================================


class TestParserValidation:
    def test_fleet_only_spec_parses(self, tmp_path):
        """Fleet-only spec (no intent, no output_schema, only fleet triggers) parses."""
        spec = {
            "name": "fleet-test",
            "triggers": [{"action": "fleet", "path": "inbox/fleet"}],
        }
        result = SpecParser.parse_yaml(_write_spec(tmp_path, spec))
        assert result["name"] == "fleet-test"

    def test_enforcer_spec_without_intent_raises(self, tmp_path):
        """Enforcer spec without intent raises ValueError."""
        spec = {
            "name": "enforcer-test",
            "triggers": [{"action": "enforcer", "path": "inbox"}],
            "output_schema": {"type": "object"},
        }
        with pytest.raises(ValueError, match="intent"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_mixed_spec_without_intent_raises(self, tmp_path):
        """Mixed spec (fleet + enforcer triggers) without intent raises ValueError."""
        spec = {
            "name": "mixed",
            "triggers": [
                {"action": "fleet", "path": "inbox/fleet"},
                {"action": "enforcer", "path": "inbox"},
            ],
            "output_schema": {"type": "object"},
        }
        with pytest.raises(ValueError, match="intent"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_unknown_action_raises(self, tmp_path):
        """Unknown action raises ValueError."""
        spec = {
            "name": "bad-action",
            "intent": "test",
            "output_schema": {"type": "object"},
            "triggers": [{"action": "foobar", "path": "inbox"}],
        }
        with pytest.raises(ValueError, match="Unknown trigger action"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_no_triggers_no_intent_raises(self, tmp_path):
        """Spec with no triggers and no intent raises ValueError (backward compat)."""
        spec = {
            "name": "empty",
            "output_schema": {"type": "object"},
        }
        with pytest.raises(ValueError, match="intent"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))


# ===========================================================================
# 5. Orchestrator routing
# ===========================================================================


class TestOrchestratorRouting:
    @patch("blueprint.orchestrator.SpecParser.parse_yaml")
    def test_fleet_trigger_creates_fleet_handler(self, mock_parse, tmp_path):
        """Trigger with action: fleet creates BlueprintFleetHandler."""
        from blueprint.orchestrator import BlueprintFleetHandler, BlueprintOrchestrator

        spec = {
            "name": "fleet-bp",
            "triggers": [{"action": "fleet", "path": str(tmp_path / "inbox")}],
        }
        mock_parse.return_value = spec

        orch = BlueprintOrchestrator([str(tmp_path / "bp.yaml")])
        with (
            patch.object(orch.observer, "schedule"),
            patch.object(orch.observer, "start"),
        ):
            orch.start()

        assert len(orch._handlers) == 1
        assert isinstance(orch._handlers[0], BlueprintFleetHandler)

    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=None)
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="prompt"
    )
    @patch("blueprint.orchestrator.SpecParser.parse_yaml")
    def test_enforcer_trigger_creates_fs_handler(
        self, mock_parse, _mock_prompt, _mock_schema, _mock_enforcer, tmp_path
    ):
        """Trigger with action: enforcer creates BlueprintFileSystemHandler."""
        from blueprint.orchestrator import (
            BlueprintFileSystemHandler,
            BlueprintOrchestrator,
        )

        spec = {
            "name": "enf-bp",
            "intent": "test intent",
            "output_schema": {
                "type": "object",
                "properties": {"result": {"type": "string"}},
            },
            "triggers": [{"action": "enforcer", "path": str(tmp_path / "inbox")}],
        }
        mock_parse.return_value = spec

        orch = BlueprintOrchestrator([str(tmp_path / "bp.yaml")])
        with (
            patch.object(orch.observer, "schedule"),
            patch.object(orch.observer, "start"),
        ):
            orch.start()

        assert len(orch._handlers) == 1
        assert isinstance(orch._handlers[0], BlueprintFileSystemHandler)

    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch("blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=None)
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="prompt"
    )
    @patch("blueprint.orchestrator.SpecParser.parse_yaml")
    def test_no_action_defaults_to_fs_handler(
        self, mock_parse, _mock_prompt, _mock_schema, _mock_enforcer, tmp_path
    ):
        """Trigger with no action creates BlueprintFileSystemHandler (default)."""
        from blueprint.orchestrator import (
            BlueprintFileSystemHandler,
            BlueprintOrchestrator,
        )

        spec = {
            "name": "default-bp",
            "intent": "test intent",
            "output_schema": {
                "type": "object",
                "properties": {"result": {"type": "string"}},
            },
            "triggers": [{"path": str(tmp_path / "inbox")}],
        }
        mock_parse.return_value = spec

        orch = BlueprintOrchestrator([str(tmp_path / "bp.yaml")])
        with (
            patch.object(orch.observer, "schedule"),
            patch.object(orch.observer, "start"),
        ):
            orch.start()

        assert len(orch._handlers) == 1
        assert isinstance(orch._handlers[0], BlueprintFileSystemHandler)
