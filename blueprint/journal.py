"""
Journal Reader
Filtered, read-only access to the JSON-lines journal produced by TracingCollector.
"""

import json
import os
from datetime import datetime
from typing import Optional


class JournalReader:
    """Reads and queries the append-only JSON-lines journal."""

    def __init__(self, journal_dir: str):
        self.journal_dir = journal_dir

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        agent_id: Optional[str] = None,
        operation: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return entries matching the given filters, most-recent first."""
        entries = self._load_all()

        if agent_id:
            entries = [e for e in entries if e.get("agent_id") == agent_id]
        if operation:
            entries = [e for e in entries if e.get("operation") == operation]
        if since:
            since_iso = since.isoformat()
            entries = [e for e in entries if e.get("timestamp", "") >= since_iso]
        if until:
            until_iso = until.isoformat()
            entries = [e for e in entries if e.get("timestamp", "") <= until_iso]

        # Most-recent first
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return entries[:limit]

    # ------------------------------------------------------------------
    # Trace grouping
    # ------------------------------------------------------------------

    def get_trace(self, trace_id: str) -> list[dict]:
        """Return all entries sharing a trace_id, ordered chronologically."""
        entries = [e for e in self._load_all() if e.get("trace_id") == trace_id]
        entries.sort(key=lambda e: e.get("timestamp", ""))
        return entries

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self, agent_id: Optional[str] = None) -> dict:
        """Aggregate counts by operation, time range, and error count."""
        entries = self._load_all()
        if agent_id:
            entries = [e for e in entries if e.get("agent_id") == agent_id]

        if not entries:
            return {
                "total": 0,
                "by_operation": {},
                "earliest": None,
                "latest": None,
                "error_count": 0,
            }

        by_op: dict[str, int] = {}
        error_count = 0
        timestamps: list[str] = []

        for e in entries:
            op = e.get("operation", "unknown")
            by_op[op] = by_op.get(op, 0) + 1
            ts = e.get("timestamp")
            if ts:
                timestamps.append(ts)
            ctx = e.get("context", {})
            if ctx.get("error"):
                error_count += 1

        timestamps.sort()
        return {
            "total": len(entries),
            "by_operation": by_op,
            "earliest": timestamps[0] if timestamps else None,
            "latest": timestamps[-1] if timestamps else None,
            "error_count": error_count,
        }

    # ------------------------------------------------------------------
    # Internal: load every journal file
    # ------------------------------------------------------------------

    def _load_all(self) -> list[dict]:
        """Read all .jsonl files in journal_dir, skipping malformed lines."""
        entries: list[dict] = []
        if not os.path.isdir(self.journal_dir):
            return entries

        for fname in sorted(os.listdir(self.journal_dir)):
            if not fname.endswith(".jsonl"):
                continue
            path = os.path.join(self.journal_dir, fname)
            try:
                with open(path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            # Skip malformed lines gracefully
                            continue
            except OSError:
                continue

        return entries
