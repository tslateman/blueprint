"""
Fleet Dispatch
Parses fleet dispatch YAML payloads, validates them, calls Shipyard's `fl` CLI,
and writes results to an outbox.
"""

import json
import logging
import os
import re
import subprocess
import yaml
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_payload(payload: dict) -> None:
    """Validate a fleet dispatch payload. Raises ValueError on invalid input."""
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a YAML mapping")

    if "team" not in payload:
        raise ValueError("Missing required field: 'team'")

    tasks = payload.get("tasks")
    if not tasks:
        raise ValueError("Missing or empty required field: 'tasks'")

    if not isinstance(tasks, list):
        raise ValueError("'tasks' must be a list")

    task_names = set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"Task {i} must be a mapping")

        for field in ("name", "title", "agent_type"):
            if field not in task:
                raise ValueError(f"Task {i} missing required field: '{field}'")

        name = task["name"]
        if name in task_names:
            raise ValueError(f"Duplicate task name: '{name}'")
        task_names.add(name)

    # Validate depends_on references
    for task in tasks:
        for dep in task.get("depends_on", []):
            if dep not in task_names:
                raise ValueError(
                    f"Task '{task['name']}' depends on unknown task: '{dep}'"
                )


def topo_sort(tasks: list[dict]) -> list[dict]:
    """Topological sort tasks by depends_on. Raises ValueError on cycles."""
    by_name = {t["name"]: t for t in tasks}
    visited = set()
    in_progress = set()
    result = []

    def visit(name):
        if name in in_progress:
            raise ValueError(f"Cycle detected involving task: '{name}'")
        if name in visited:
            return
        in_progress.add(name)
        for dep in by_name[name].get("depends_on", []):
            visit(dep)
        in_progress.remove(name)
        visited.add(name)
        result.append(by_name[name])

    for name in by_name:
        visit(name)

    return result


def _run_fl(args: list[str]) -> subprocess.CompletedProcess:
    """Run the Shipyard `fl` CLI with the given arguments."""
    return subprocess.run(
        ["fl"] + args,
        capture_output=True,
        text=True,
        timeout=30,
    )


def dispatch_fleet(payload_path: str, outbox: str, default_runtime: str) -> dict:
    """
    Parse a fleet dispatch YAML file, provision the team and tasks via
    Shipyard's `fl` CLI, drive independent tasks, and write results to outbox.

    Returns a dict with keys: ok, team, tasks_created, tasks_driven, errors.
    """
    filename = Path(payload_path).name
    result = {
        "ok": False,
        "team": None,
        "tasks_created": 0,
        "tasks_driven": 0,
        "task_ids": {},
        "errors": [],
    }

    # 1. Parse and validate
    try:
        with open(payload_path, "r") as f:
            payload = yaml.safe_load(f)
        validate_payload(payload)
    except Exception as e:
        result["errors"].append(f"Validation failed: {e}")
        _write_result(outbox, filename, result)
        _lore_error(str(e))
        return result

    team = payload["team"]
    runtime = payload.get("runtime", default_runtime)
    result["team"] = team

    # 2. Topological sort
    try:
        sorted_tasks = topo_sort(payload["tasks"])
    except ValueError as e:
        result["errors"].append(f"Topo sort failed: {e}")
        _write_result(outbox, filename, result)
        _lore_error(str(e))
        return result

    # 3. Create team
    try:
        r = _run_fl(["team", "create", team])
        if r.returncode != 0:
            if "already exists" in (r.stderr or ""):
                logger.info("Team '%s' already exists, continuing", team)
            else:
                msg = f"fl team create failed: {r.stderr.strip()}"
                result["errors"].append(msg)
                _write_result(outbox, filename, result)
                _lore_error(msg)
                return result
    except subprocess.TimeoutExpired:
        msg = "fl team create timed out"
        result["errors"].append(msg)
        _write_result(outbox, filename, result)
        _lore_error(msg)
        return result

    # 4. Create tasks in topo order
    for task in sorted_tasks:
        args = [
            "task",
            "create",
            "--team",
            team,
            "--title",
            task["title"],
        ]

        if task.get("scope_in"):
            args += ["--scope-in", json.dumps(task["scope_in"])]
        if task.get("scope_out"):
            args += ["--scope-out", json.dumps(task["scope_out"])]
        if task.get("done_when"):
            args += ["--done-when", json.dumps(task["done_when"])]
        if task.get("description"):
            args += ["--description", task["description"]]

        try:
            r = _run_fl(args)
        except subprocess.TimeoutExpired:
            result["errors"].append(f"fl task create timed out for '{task['name']}'")
            break

        if r.returncode != 0:
            result["errors"].append(
                f"fl task create failed for '{task['name']}': {r.stderr.strip()}"
            )
            break

        # Parse task_id from stdout JSON, fall back to regex
        task_id = None
        try:
            data = json.loads(r.stdout)
            task_id = data.get("task_id")
        except (json.JSONDecodeError, TypeError):
            match = re.search(r"task-[a-z0-9-]+", r.stdout)
            if match:
                task_id = match.group(0)

        if task_id:
            result["task_ids"][task["name"]] = task_id
            result["tasks_created"] += 1
        else:
            result["errors"].append(
                f"Could not parse task_id for '{task['name']}' "
                f"from stdout: {r.stdout.strip()}"
            )
            break

    # 5. Drive independent tasks (no depends_on)
    for task in sorted_tasks:
        if task.get("depends_on"):
            continue
        task_id = result["task_ids"].get(task["name"])
        if not task_id:
            continue

        try:
            r = _run_fl(["drive", task_id, "--runtime", runtime])
        except subprocess.TimeoutExpired:
            result["errors"].append(
                f"fl drive timed out for '{task['name']}' ({task_id})"
            )
            continue

        if r.returncode != 0:
            result["errors"].append(
                f"fl drive failed for '{task['name']}' ({task_id}): {r.stderr.strip()}"
            )
            continue

        result["tasks_driven"] += 1

    # 6. Determine success and write result
    result["ok"] = result["tasks_created"] == len(sorted_tasks) and not result["errors"]

    _write_result(outbox, filename, result)

    # 7. Capture to lore
    if result["ok"]:
        _lore_success(team, result["tasks_created"], filename)
    else:
        _lore_error(
            f"Fleet {team}: {result['tasks_created']}/{len(sorted_tasks)} "
            f"tasks created, errors: {result['errors']}"
        )

    return result


def _write_result(outbox: str, trigger_filename: str, result: dict) -> None:
    """Write a result YAML file to the outbox."""
    os.makedirs(outbox, exist_ok=True)
    stem = Path(trigger_filename).stem
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(outbox, f"{stem}_{ts}_result.yaml")
    with open(out_path, "w") as f:
        yaml.dump(result, f, default_flow_style=False)
    logger.info("Result written to %s", out_path)


def _lore_success(team: str, task_count: int, filename: str) -> None:
    """Capture a success event to lore."""
    try:
        subprocess.run(
            [
                "lore",
                "capture",
                f"Fleet {team} dispatched: {task_count} tasks",
                "--rationale",
                f"Trigger: {filename}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        logger.debug("lore capture failed (non-fatal)")


def _lore_error(msg: str) -> None:
    """Capture an error event to lore."""
    try:
        subprocess.run(
            [
                "lore",
                "capture",
                msg,
                "--error-type",
                "FleetDispatch",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        logger.debug("lore capture failed (non-fatal)")
