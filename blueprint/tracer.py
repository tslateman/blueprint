"""
Agent Tracing Collector
Append-only JSON-lines recorder for every significant pipeline operation.
"""

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional


class TracingCollector:
    """Append-only JSON-lines tracer.  Thread-safe via a per-instance lock."""

    OPERATIONS = frozenset(
        {
            "lore_recall",
            "lore_record",
            "llm_call",
            "llm_fallback",
            "sandbox_exec",
            "trigger_fired",
            "fleet_dispatch",
            "fleet_review",
            "schema_compile",
            "prompt_compile",
            "evaluation_run",
        }
    )

    def __init__(self, journal_dir: str, agent_id: Optional[str] = None):
        self.journal_dir = journal_dir
        self.agent_id = agent_id or "default"
        self._lock = threading.Lock()
        self._trace_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_trace_id(self, trace_id: str) -> None:
        """Pin all subsequent emits to a shared trace_id."""
        self._trace_id = trace_id

    def new_trace(self) -> str:
        """Generate and pin a fresh trace_id."""
        tid = uuid.uuid4().hex
        self._trace_id = tid
        return tid

    # ------------------------------------------------------------------
    # Core emit
    # ------------------------------------------------------------------

    def emit(self, operation: str, context: Optional[dict] = None) -> str:
        """Append a single JSON line to today's journal file.

        Returns the entry id (a UUID hex string).
        """
        entry_id = uuid.uuid4().hex
        entry = {
            "id": entry_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": self.agent_id,
            "operation": operation,
            "context": context or {},
            "duration_ms": None,
        }
        if self._trace_id:
            entry["trace_id"] = self._trace_id

        try:
            self._append(entry)
        except Exception:
            # Fail-open: tracing must never break the main operation
            pass

        return entry_id

    # ------------------------------------------------------------------
    # Span context manager (auto-records duration_ms)
    # ------------------------------------------------------------------

    @contextmanager
    def span(self, operation: str, context: Optional[dict] = None):
        """Context manager that emits an entry with measured duration_ms on exit."""
        import time

        ctx = dict(context) if context else {}
        start = time.monotonic()
        entry_id = uuid.uuid4().hex
        try:
            yield ctx
        except Exception as exc:
            ctx["error"] = str(exc)
            raise
        finally:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            entry = {
                "id": entry_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent_id": self.agent_id,
                "operation": operation,
                "context": ctx,
                "duration_ms": elapsed_ms,
            }
            if self._trace_id:
                entry["trace_id"] = self._trace_id
            try:
                self._append(entry)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal: append a JSON line (thread-safe)
    # ------------------------------------------------------------------

    def _append(self, entry: dict) -> None:
        line = json.dumps(entry, default=str) + "\n"
        with self._lock:
            os.makedirs(self.journal_dir, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = os.path.join(self.journal_dir, f"journal-{date_str}.jsonl")
            with open(path, "a") as f:
                f.write(line)
