"""
Fleet Watcher
Polls driven tasks for completion, drives dependents when prerequisites are met,
and cascades failures through the dependency graph.
"""

import json
import logging
import os
import threading
from collections import deque
from pathlib import Path

from blueprint.fleet_dispatch import _run_fl, _write_result, _find_result_file

logger = logging.getLogger(__name__)


class FleetWatcher:
    """Watches a dispatched fleet, driving dependent tasks as prerequisites complete."""

    def __init__(
        self,
        dispatch_result: dict,
        sorted_tasks: list[dict],
        outbox: str,
        runtime: str,
        poll_interval: float = 30.0,
    ):
        self.dispatch_result = dispatch_result
        self.sorted_tasks = sorted_tasks
        self.outbox = outbox
        self.runtime = runtime
        self.poll_interval = poll_interval

        self._stop_event = threading.Event()

        # Build dependency graph
        self._task_ids = dispatch_result.get("task_ids", {})
        self._by_name = {t["name"]: t for t in sorted_tasks}
        self._dependents: dict[str, list[str]] = {}  # task_name -> [dependent_names]
        self._prerequisites: dict[str, set[str]] = {}  # task_name -> {prereq_names}

        for task in sorted_tasks:
            name = task["name"]
            deps = task.get("depends_on", [])
            self._prerequisites[name] = set(deps)
            for dep in deps:
                self._dependents.setdefault(dep, []).append(name)

        # State tracking
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._driven: set[str] = set()
        self._reviewed: set[str] = set()

        # Mark independent tasks (already driven by dispatch_fleet) as driven
        for task in sorted_tasks:
            if not task.get("depends_on") and task["name"] in self._task_ids:
                self._driven.add(task["name"])

    def watch(self) -> dict:
        """Blocking poll loop. Returns updated dispatch result when all tasks are terminal."""
        while not self._stop_event.is_set():
            self._poll_driven_tasks()
            self._drive_unblocked_tasks()

            # Check if all tasks are terminal (completed or failed)
            all_names = {t["name"] for t in self.sorted_tasks}
            terminal = self._completed | self._failed
            if terminal >= all_names:
                break

            self._stop_event.wait(self.poll_interval)

        return self._build_result()

    def watch_async(self) -> threading.Thread:
        """Non-blocking watch. Returns the thread handle."""
        thread = threading.Thread(target=self.watch, daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Signal the watcher to stop."""
        self._stop_event.set()

    def _poll_driven_tasks(self):
        """Check status of driven-but-not-completed tasks."""
        to_poll = self._driven - self._completed - self._failed
        for name in list(to_poll):
            task_id = self._task_ids.get(name)
            if not task_id:
                continue

            try:
                r = _run_fl(["task", "status", task_id, "--json"])
            except Exception as e:
                logger.warning("Failed to poll task '%s': %s", name, e)
                continue

            if r.returncode != 0:
                logger.warning(
                    "fl task status failed for '%s': %s", name, r.stderr.strip()
                )
                continue

            try:
                data = json.loads(r.stdout)
            except (json.JSONDecodeError, TypeError):
                continue

            status = data.get("status", "").lower()
            if status in ("completed", "merged", "approved"):
                self._completed.add(name)
                self._review_task(name)
                logger.info("Task '%s' completed", name)
            elif status in ("failed", "error", "cancelled"):
                self._failed.add(name)
                self._cascade_failure(name)
                logger.warning("Task '%s' failed, cascading to dependents", name)

    def _drive_unblocked_tasks(self):
        """Drive tasks whose prerequisites are all completed."""
        for task in self.sorted_tasks:
            name = task["name"]
            if name in self._driven or name in self._failed:
                continue

            prereqs = self._prerequisites.get(name, set())
            if not prereqs or prereqs <= self._completed:
                task_id = self._task_ids.get(name)
                if not task_id:
                    continue

                try:
                    r = _run_fl(["drive", task_id, "--runtime", self.runtime])
                except Exception as e:
                    logger.error("Failed to drive task '%s': %s", name, e)
                    self._failed.add(name)
                    self._cascade_failure(name)
                    continue

                if r.returncode != 0:
                    logger.error(
                        "fl drive failed for '%s': %s", name, r.stderr.strip()
                    )
                    self._failed.add(name)
                    self._cascade_failure(name)
                    continue

                self._driven.add(name)
                self.dispatch_result["tasks_driven"] = (
                    self.dispatch_result.get("tasks_driven", 0) + 1
                )
                logger.info("Drove unblocked task '%s'", name)

    def _review_task(self, name: str):
        """Run Reck review for a completed task."""
        if name in self._reviewed:
            return

        task_id = self._task_ids.get(name)
        task = self._by_name.get(name, {})
        agent_name = task.get("agent_type", "builder")
        result_file = _find_result_file(self.outbox, task_id)

        if not result_file:
            logger.info("No result file for task '%s', skipping review", name)
            self._reviewed.add(name)
            return

        reck_dir = os.environ.get(
            "RECK_DIR",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "reck"),
        )

        review_args = [
            "review",
            task_id,
            "--agent", agent_name,
            "--result", result_file,
            "--json",
        ]

        reck_dir_resolved = os.path.abspath(reck_dir)
        if os.path.isdir(reck_dir_resolved):
            review_args += ["--reck-dir", reck_dir_resolved]

        try:
            r = _run_fl(review_args)
        except Exception as e:
            logger.warning("Review failed for task '%s': %s", name, e)
            self._reviewed.add(name)
            return

        # Parse review verdict
        try:
            review_data = json.loads(r.stdout)
            verdict = review_data.get("verdict", {})
            self.dispatch_result.setdefault("review_verdicts", {})[name] = {
                "verdict": verdict.get("verdict", "UNKNOWN") if isinstance(verdict, dict) else "UNKNOWN",
                "confidence": verdict.get("confidence", 0.0) if isinstance(verdict, dict) else 0.0,
                "transitioned_to": review_data.get("transitioned_to"),
            }
            if review_data.get("ok"):
                self.dispatch_result["tasks_reviewed"] = (
                    self.dispatch_result.get("tasks_reviewed", 0) + 1
                )
        except (json.JSONDecodeError, TypeError):
            if r.returncode == 0:
                self.dispatch_result["tasks_reviewed"] = (
                    self.dispatch_result.get("tasks_reviewed", 0) + 1
                )

        self._reviewed.add(name)

        # Write incremental result
        trigger_name = Path(self.outbox).name or "fleet_watcher"
        _write_result(self.outbox, f"{trigger_name}_incremental.yaml", self.dispatch_result)

    def _cascade_failure(self, name: str):
        """BFS: mark all transitive dependents of a failed task as failed."""
        queue = deque(self._dependents.get(name, []))
        while queue:
            dep = queue.popleft()
            if dep not in self._failed:
                self._failed.add(dep)
                logger.warning("Task '%s' failed (cascade from dependency)", dep)
                queue.extend(self._dependents.get(dep, []))

    def _build_result(self) -> dict:
        """Build the final result dict with watcher metadata."""
        self.dispatch_result["watcher_completed"] = sorted(self._completed)
        self.dispatch_result["watcher_failed"] = sorted(self._failed)
        self.dispatch_result["ok"] = (
            len(self._failed) == 0
            and self._completed == {t["name"] for t in self.sorted_tasks}
        )

        trigger_name = Path(self.outbox).name or "fleet_watcher"
        _write_result(self.outbox, f"{trigger_name}_final.yaml", self.dispatch_result)

        return self.dispatch_result
