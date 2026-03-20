"""Tests for fleet watcher: dependency polling, cascading failures, and integration."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blueprint.fleet_watcher import FleetWatcher


def _make_dispatch_result(task_names, task_ids=None, driven=None):
    """Build a minimal dispatch result."""
    if task_ids is None:
        task_ids = {name: f"task-{name}-001" for name in task_names}
    result = {
        "ok": True,
        "team": "test-team",
        "tasks_created": len(task_names),
        "tasks_driven": len(driven) if driven else 0,
        "tasks_reviewed": 0,
        "task_ids": task_ids,
        "review_verdicts": {},
        "errors": [],
    }
    return result


def _make_tasks(*specs):
    """Build a task list from (name, depends_on) tuples."""
    tasks = []
    for spec in specs:
        if isinstance(spec, str):
            tasks.append({"name": spec, "title": spec.upper(), "agent_type": "builder"})
        else:
            name, deps = spec
            tasks.append({
                "name": name, "title": name.upper(), "agent_type": "builder",
                "depends_on": deps,
            })
    return tasks


def _fl_status_mock(statuses):
    """Create a mock for _run_fl that returns statuses by task name.

    statuses: dict of task_name -> list of status strings (popped in order)
    """
    call_counts = {name: 0 for name in statuses}

    def mock_fn(args):
        # Drive calls
        if args[0] == "drive":
            return subprocess.CompletedProcess(
                args=["fl"] + args, returncode=0, stdout="{}", stderr=""
            )
        # Review calls
        if args[0] == "review":
            return subprocess.CompletedProcess(
                args=["fl"] + args, returncode=0,
                stdout=json.dumps({"ok": True, "verdict": {"verdict": "PASS", "confidence": 0.9}}),
                stderr=""
            )
        # Status calls
        if args[0] == "task" and args[1] == "status":
            task_id = args[2]
            # Find task name from id
            for name in statuses:
                if f"task-{name}-001" == task_id:
                    status_list = statuses[name]
                    idx = min(call_counts[name], len(status_list) - 1)
                    call_counts[name] += 1
                    return subprocess.CompletedProcess(
                        args=["fl"] + args, returncode=0,
                        stdout=json.dumps({"status": status_list[idx]}),
                        stderr=""
                    )
        return subprocess.CompletedProcess(
            args=["fl"] + args, returncode=0, stdout="{}", stderr=""
        )

    return mock_fn


# ===========================================================================
# 1. FleetWatcher core behavior
# ===========================================================================


class TestFleetWatcher:
    @patch("blueprint.fleet_watcher._run_fl")
    @patch("blueprint.fleet_watcher._write_result")
    def test_all_independent_tasks_complete(self, _mock_write, mock_fl, tmp_path):
        """All independent tasks -- polls until completed, returns result."""
        tasks = _make_tasks("a", "b")
        result = _make_dispatch_result(["a", "b"], driven=["a", "b"])

        mock_fl.side_effect = _fl_status_mock({
            "a": ["running", "completed"],
            "b": ["running", "completed"],
        })

        watcher = FleetWatcher(result, tasks, str(tmp_path), "local", poll_interval=0.05)
        final = watcher.watch()

        assert "a" in final["watcher_completed"]
        assert "b" in final["watcher_completed"]
        assert len(final["watcher_failed"]) == 0

    @patch("blueprint.fleet_watcher._run_fl")
    @patch("blueprint.fleet_watcher._write_result")
    def test_linear_chain(self, _mock_write, mock_fl, tmp_path):
        """Linear chain A->B->C: B driven after A completes, C after B."""
        tasks = _make_tasks("a", ("b", ["a"]), ("c", ["b"]))
        result = _make_dispatch_result(["a", "b", "c"], driven=["a"])

        # a completes first poll, b completes second, c completes third
        mock_fl.side_effect = _fl_status_mock({
            "a": ["completed"],
            "b": ["running", "completed"],
            "c": ["running", "completed"],
        })

        watcher = FleetWatcher(result, tasks, str(tmp_path), "local", poll_interval=0.05)
        final = watcher.watch()

        assert set(final["watcher_completed"]) == {"a", "b", "c"}
        assert len(final["watcher_failed"]) == 0

    @patch("blueprint.fleet_watcher._run_fl")
    @patch("blueprint.fleet_watcher._write_result")
    def test_diamond_dependency(self, _mock_write, mock_fl, tmp_path):
        """Diamond A->{B,C}->D: D driven after B and C both complete."""
        tasks = _make_tasks("a", ("b", ["a"]), ("c", ["a"]), ("d", ["b", "c"]))
        result = _make_dispatch_result(["a", "b", "c", "d"], driven=["a"])

        mock_fl.side_effect = _fl_status_mock({
            "a": ["completed"],
            "b": ["running", "completed"],
            "c": ["running", "completed"],
            "d": ["running", "completed"],
        })

        watcher = FleetWatcher(result, tasks, str(tmp_path), "local", poll_interval=0.05)
        final = watcher.watch()

        assert set(final["watcher_completed"]) == {"a", "b", "c", "d"}
        assert len(final["watcher_failed"]) == 0

    @patch("blueprint.fleet_watcher._run_fl")
    @patch("blueprint.fleet_watcher._write_result")
    def test_failed_task_cascades(self, _mock_write, mock_fl, tmp_path):
        """Failed task cascades to all transitive dependents."""
        tasks = _make_tasks("a", ("b", ["a"]), ("c", ["b"]))
        result = _make_dispatch_result(["a", "b", "c"], driven=["a"])

        mock_fl.side_effect = _fl_status_mock({
            "a": ["failed"],
        })

        watcher = FleetWatcher(result, tasks, str(tmp_path), "local", poll_interval=0.05)
        final = watcher.watch()

        assert "a" in final["watcher_failed"]
        assert "b" in final["watcher_failed"]
        assert "c" in final["watcher_failed"]

    @patch("blueprint.fleet_watcher._run_fl")
    @patch("blueprint.fleet_watcher._write_result")
    def test_stop_halts_watcher(self, _mock_write, mock_fl, tmp_path):
        """stop() halts the watcher."""
        tasks = _make_tasks("a", ("b", ["a"]))
        result = _make_dispatch_result(["a", "b"], driven=["a"])

        # a never completes — watcher would run forever without stop()
        mock_fl.side_effect = _fl_status_mock({"a": ["running"]})

        watcher = FleetWatcher(result, tasks, str(tmp_path), "local", poll_interval=0.05)
        thread = watcher.watch_async()
        watcher.stop()
        thread.join(timeout=2)
        assert not thread.is_alive()

    @patch("blueprint.fleet_watcher._find_result_file", return_value="/fake/result.json")
    @patch("blueprint.fleet_watcher._run_fl")
    @patch("blueprint.fleet_watcher._write_result")
    def test_review_called_for_completed(self, mock_write, mock_fl, _mock_find, tmp_path):
        """Review is called for completed tasks."""
        tasks = _make_tasks("a")
        result = _make_dispatch_result(["a"], driven=["a"])

        review_called = {"count": 0}
        original_mock = _fl_status_mock({"a": ["completed"]})

        def counting_mock(args):
            if args[0] == "review":
                review_called["count"] += 1
            return original_mock(args)

        mock_fl.side_effect = counting_mock

        watcher = FleetWatcher(result, tasks, str(tmp_path), "local", poll_interval=0.05)
        watcher.watch()

        assert review_called["count"] >= 1


# ===========================================================================
# 2. dispatch_fleet_with_watch
# ===========================================================================


class TestDispatchFleetWithWatch:
    @patch("blueprint.fleet_dispatch._run_fl")
    @patch("blueprint.fleet_dispatch._write_result")
    def test_watch_false_returns_standard(self, _mock_write, mock_fl, tmp_path):
        """watch=False returns standard dispatch result."""
        from blueprint.fleet_dispatch import dispatch_fleet_with_watch

        payload = {
            "team": "test",
            "tasks": [
                {"name": "a", "title": "A", "agent_type": "builder"},
                {"name": "b", "title": "B", "agent_type": "builder", "depends_on": ["a"]},
            ],
        }
        p = tmp_path / "payload.yaml"
        p.write_text(yaml.dump(payload))

        def ok_result(args, **_kw):
            if "task" in args and "create" in args:
                try:
                    idx = args.index("--title")
                    title = args[idx + 1]
                except (ValueError, IndexError):
                    title = "unknown"
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"task_id": f"task-{title.lower().replace(' ', '-')}-001"}),
                    stderr=""
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

        mock_fl.side_effect = ok_result

        result = dispatch_fleet_with_watch(str(p), str(tmp_path / "outbox"), "local", watch=False)
        assert "watcher_completed" not in result

    @patch("blueprint.fleet_dispatch._run_fl")
    @patch("blueprint.fleet_dispatch._write_result")
    def test_watch_true_no_dependents_returns_immediately(self, _mock_write, mock_fl, tmp_path):
        """watch=True with no dependents returns immediately without watcher."""
        from blueprint.fleet_dispatch import dispatch_fleet_with_watch

        payload = {
            "team": "test",
            "tasks": [
                {"name": "a", "title": "A", "agent_type": "builder"},
                {"name": "b", "title": "B", "agent_type": "builder"},
            ],
        }
        p = tmp_path / "payload.yaml"
        p.write_text(yaml.dump(payload))

        def ok_result(args, **_kw):
            if "task" in args and "create" in args:
                try:
                    idx = args.index("--title")
                    title = args[idx + 1]
                except (ValueError, IndexError):
                    title = "unknown"
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"task_id": f"task-{title.lower().replace(' ', '-')}-001"}),
                    stderr=""
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

        mock_fl.side_effect = ok_result

        result = dispatch_fleet_with_watch(str(p), str(tmp_path / "outbox"), "local", watch=True)
        # No watcher metadata since no dependents
        assert "watcher_completed" not in result

    @patch("blueprint.fleet_watcher._run_fl")
    @patch("blueprint.fleet_watcher._write_result")
    @patch("blueprint.fleet_dispatch._run_fl")
    @patch("blueprint.fleet_dispatch._write_result")
    def test_watch_true_with_dependents_blocks(
        self, _mock_write_dispatch, mock_fl_dispatch, _mock_write_watcher, mock_fl_watcher, tmp_path
    ):
        """watch=True with dependents blocks until all tasks complete."""
        from blueprint.fleet_dispatch import dispatch_fleet_with_watch

        payload = {
            "team": "test",
            "tasks": [
                {"name": "a", "title": "A", "agent_type": "builder"},
                {"name": "b", "title": "B", "agent_type": "builder", "depends_on": ["a"]},
            ],
        }
        p = tmp_path / "payload.yaml"
        p.write_text(yaml.dump(payload))

        def ok_dispatch(args, **_kw):
            if "task" in args and "create" in args:
                try:
                    idx = args.index("--title")
                    title = args[idx + 1]
                except (ValueError, IndexError):
                    title = "unknown"
                return subprocess.CompletedProcess(
                    args=args, returncode=0,
                    stdout=json.dumps({"task_id": f"task-{title.lower().replace(' ', '-')}-001"}),
                    stderr=""
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

        mock_fl_dispatch.side_effect = ok_dispatch

        # Watcher polls: a completes, then b completes
        mock_fl_watcher.side_effect = _fl_status_mock({
            "a": ["completed"],
            "b": ["running", "completed"],
        })

        result = dispatch_fleet_with_watch(
            str(p), str(tmp_path / "outbox"), "local",
            watch=True, poll_interval=0.05,
        )

        assert "watcher_completed" in result
        assert "a" in result["watcher_completed"]
        assert "b" in result["watcher_completed"]
