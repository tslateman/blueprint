"""
Blueprint Orchestrator
Listens for events defined in Blueprints and triggers executions.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from blueprint.parser import SpecParser
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer
from blueprint.fleet_dispatch import dispatch_fleet

if TYPE_CHECKING:
    from blueprint.tracer import TracingCollector

logger = logging.getLogger(__name__)


class BlueprintFileSystemHandler(FileSystemEventHandler):
    """Specific handler for file-based triggers in a Blueprint."""

    def __init__(
        self,
        spec: Dict[str, Any],
        trigger_config: Dict[str, Any],
        tracer: "Optional[TracingCollector]" = None,
    ):
        self.spec = spec
        self.trigger_config = trigger_config
        self.tracer = tracer
        self.path = trigger_config.get("path", "inbox")
        self.extension = trigger_config.get("extension", ".txt")
        self.outbox = trigger_config.get("outbox", "outbox")

        # Pre-initialize enforcer and models
        self.enforcer = SchemaEnforcer(
            use_cli=(os.environ.get("USE_GEMINI_CLI", "").lower() == "true")
        )
        self.system_prompt = BlueprintCompiler.compile_prompt(self.spec)
        self.ResponseModel = BlueprintCompiler.compile_schema(self.spec)

        os.makedirs(self.path, exist_ok=True)
        os.makedirs(self.outbox, exist_ok=True)

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(self.extension):
            return

        print(f"[ORCHESTRATOR] Event Triggered: {event.src_path}")
        if self.tracer:
            try:
                self.tracer.emit(
                    "trigger_fired",
                    {
                        "path": event.src_path,
                        "event_type": "created",
                        "handler": "file",
                    },
                )
            except Exception:
                pass
        self.process_event(event.src_path)

    def process_event(self, file_path):
        try:
            with open(file_path, "r") as f:
                user_input = f.read().strip()

            if not user_input:
                return

            result = self.enforcer.generate(
                self.system_prompt, user_input, self.ResponseModel
            )

            output_filename = Path(file_path).stem + "_result.json"
            output_path = os.path.join(self.outbox, output_filename)

            with open(output_path, "w") as f:
                f.write(result.model_dump_json(indent=2))

            print(f"[SUCCESS] Result written to: {output_path}")
        except Exception as e:
            print(f"[ERROR] Orchestration failed for {file_path}: {e}")


class BlueprintFleetHandler(FileSystemEventHandler):
    """Watches for fleet dispatch YAML files and provisions Shipyard fleets."""

    def __init__(
        self, trigger_config: dict, tracer: "Optional[TracingCollector]" = None
    ):
        self.tracer = tracer
        self.path = trigger_config.get("path", "inbox/fleet")
        self.extension = trigger_config.get("extension", ".yaml")
        self.outbox = trigger_config.get("outbox", "outbox/fleet")
        self.runtime = trigger_config.get("runtime", "local")
        self.watch = trigger_config.get("watch", False)
        self.poll_interval = trigger_config.get("poll_interval", 30.0)
        os.makedirs(self.path, exist_ok=True)
        os.makedirs(self.outbox, exist_ok=True)

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(self.extension):
            return
        print(f"[FLEET] Dispatch triggered: {event.src_path}")
        if self.tracer:
            try:
                self.tracer.emit(
                    "trigger_fired",
                    {
                        "path": event.src_path,
                        "event_type": "created",
                        "handler": "fleet",
                    },
                )
            except Exception:
                pass
        if self.watch:
            from blueprint.fleet_dispatch import dispatch_fleet_with_watch

            result = dispatch_fleet_with_watch(
                event.src_path,
                self.outbox,
                self.runtime,
                watch=True,
                poll_interval=self.poll_interval,
            )
        else:
            result = dispatch_fleet(event.src_path, self.outbox, self.runtime)
        status = "OK" if result.get("ok") else "FAILED"
        print(
            f"[FLEET] {status}: team={result.get('team')}, "
            f"tasks={result.get('tasks_created', 0)}"
        )


class BlueprintTimerHandler:
    """Fires actions on a recurring interval."""

    def __init__(self, spec: dict, trigger_config: dict, interval: float):
        self.spec = spec
        self.trigger_config = trigger_config
        self.interval = interval
        self.action = trigger_config.get("action", "enforcer")
        self.outbox = trigger_config.get("outbox", "outbox")
        os.makedirs(self.outbox, exist_ok=True)

        self._stop_event = threading.Event()
        self._thread = None

        if self.action == "enforcer":
            self.enforcer = SchemaEnforcer(
                use_cli=(os.environ.get("USE_GEMINI_CLI", "").lower() == "true")
            )
            self.system_prompt = BlueprintCompiler.compile_prompt(self.spec)
            self.ResponseModel = BlueprintCompiler.compile_schema(self.spec)
            self.input_text = trigger_config["input"]
        elif self.action == "fleet":
            self.payload_path = trigger_config["payload_path"]
            self.runtime = trigger_config.get("runtime", "local")

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.wait(self.interval):
            try:
                self._fire()
            except Exception as e:
                logger.error("[TIMER] Action failed: %s", e)

    def _fire(self):
        if self.action == "enforcer":
            self._fire_enforcer()
        elif self.action == "fleet":
            self._fire_fleet()

    def _fire_enforcer(self):
        result = self.enforcer.generate(
            self.system_prompt, self.input_text, self.ResponseModel
        )
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = os.path.join(self.outbox, f"timer_{ts}_result.json")
        with open(output_path, "w") as f:
            f.write(result.model_dump_json(indent=2))
        logger.info("[TIMER] Enforcer result written to %s", output_path)

    def _fire_fleet(self):
        result = dispatch_fleet(self.payload_path, self.outbox, self.runtime)
        status = "OK" if result.get("ok") else "FAILED"
        logger.info(
            "[TIMER] Fleet dispatch %s: team=%s, tasks=%d",
            status,
            result.get("team"),
            result.get("tasks_created", 0),
        )

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)


class BlueprintOrchestrator:
    """Orchestrates background listeners based on Blueprint specs."""

    def __init__(self, blueprint_paths: List[str]):
        self.blueprint_paths = blueprint_paths
        self.observer = Observer()
        self._handlers = []
        self._timers: list = []

    def start(self):
        """Analyzes blueprints and starts the appropriate observers."""
        for path in self.blueprint_paths:
            spec = SpecParser.parse_yaml(path)
            for trigger in spec.get("triggers", []):
                ttype = trigger.get("type", "file")
                action = trigger.get("action", "enforcer")

                if ttype == "timer":
                    interval = trigger["interval"]
                    print(
                        f"[INIT] Setting up timer trigger "
                        f"(every {interval}s) for {path}..."
                    )
                    timer = BlueprintTimerHandler(spec, trigger, interval)
                    timer.start()
                    self._timers.append(timer)
                    continue

                # File-based triggers
                if action == "enforcer":
                    print(f"[INIT] Setting up file-system trigger for {path}...")
                    handler = BlueprintFileSystemHandler(spec, trigger)
                elif action == "fleet":
                    print(f"[INIT] Setting up fleet trigger for {path}...")
                    handler = BlueprintFleetHandler(trigger)
                else:
                    print(f"[WARN] Unknown action '{action}' in {path}")
                    continue

                self.observer.schedule(handler, handler.path, recursive=False)
                self._handlers.append(handler)

        if self._handlers:
            self.observer.start()

        if self._handlers or self._timers:
            parts = []
            if self._handlers:
                parts.append(f"{len(self._handlers)} listeners")
            if self._timers:
                parts.append(f"{len(self._timers)} timers")
            print(f"[READY] Background Orchestrator running with {', '.join(parts)}.")
        else:
            print("[INFO] No active triggers found in blueprints.")

    def stop(self):
        for timer in self._timers:
            timer.stop()
        self.observer.stop()
        self.observer.join()
