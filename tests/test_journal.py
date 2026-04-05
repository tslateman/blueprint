"""Tests for JournalReader: query, get_trace, summary, empty/malformed handling."""

import json
import os
from datetime import datetime, timezone, timedelta

import pytest

from blueprint.journal import JournalReader
from blueprint.tracer import TracingCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_entries(journal_dir: str, entries: list[dict]) -> None:
    """Write raw JSON-line entries into a single journal file."""
    os.makedirs(journal_dir, exist_ok=True)
    path = os.path.join(journal_dir, "journal-2026-04-05.jsonl")
    with open(path, "a") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _make_entry(
    operation: str = "llm_call",
    agent_id: str = "a1",
    timestamp: str = "2026-04-05T12:00:00+00:00",
    trace_id: str | None = None,
    context: dict | None = None,
) -> dict:
    import uuid

    entry = {
        "id": uuid.uuid4().hex,
        "timestamp": timestamp,
        "agent_id": agent_id,
        "operation": operation,
        "context": context or {},
        "duration_ms": None,
    }
    if trace_id:
        entry["trace_id"] = trace_id
    return entry


# ===========================================================================
# 1. query() filters
# ===========================================================================


class TestQuery:
    def test_filter_by_operation(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(
            jd,
            [
                _make_entry(operation="llm_call"),
                _make_entry(operation="lore_recall"),
                _make_entry(operation="llm_call"),
            ],
        )
        reader = JournalReader(jd)
        results = reader.query(operation="llm_call")
        assert len(results) == 2
        assert all(e["operation"] == "llm_call" for e in results)

    def test_filter_by_agent_id(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(
            jd,
            [
                _make_entry(agent_id="bot-1"),
                _make_entry(agent_id="bot-2"),
                _make_entry(agent_id="bot-1"),
            ],
        )
        reader = JournalReader(jd)
        results = reader.query(agent_id="bot-1")
        assert len(results) == 2

    def test_filter_by_time_range(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(
            jd,
            [
                _make_entry(timestamp="2026-04-05T10:00:00+00:00"),
                _make_entry(timestamp="2026-04-05T12:00:00+00:00"),
                _make_entry(timestamp="2026-04-05T14:00:00+00:00"),
            ],
        )
        reader = JournalReader(jd)
        results = reader.query(
            since=datetime(2026, 4, 5, 11, 0, tzinfo=timezone.utc),
            until=datetime(2026, 4, 5, 13, 0, tzinfo=timezone.utc),
        )
        assert len(results) == 1
        assert results[0]["timestamp"] == "2026-04-05T12:00:00+00:00"

    def test_limit(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(jd, [_make_entry() for _ in range(10)])
        reader = JournalReader(jd)
        results = reader.query(limit=3)
        assert len(results) == 3

    def test_combined_filters(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(
            jd,
            [
                _make_entry(operation="llm_call", agent_id="a1"),
                _make_entry(operation="lore_recall", agent_id="a1"),
                _make_entry(operation="llm_call", agent_id="a2"),
            ],
        )
        reader = JournalReader(jd)
        results = reader.query(operation="llm_call", agent_id="a1")
        assert len(results) == 1


# ===========================================================================
# 2. get_trace() groups by trace_id
# ===========================================================================


class TestGetTrace:
    def test_groups_by_trace_id(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(
            jd,
            [
                _make_entry(trace_id="t1", timestamp="2026-04-05T10:00:00+00:00"),
                _make_entry(trace_id="t2", timestamp="2026-04-05T10:01:00+00:00"),
                _make_entry(trace_id="t1", timestamp="2026-04-05T10:02:00+00:00"),
            ],
        )
        reader = JournalReader(jd)
        trace = reader.get_trace("t1")
        assert len(trace) == 2
        assert all(e["trace_id"] == "t1" for e in trace)
        # Chronological order
        assert trace[0]["timestamp"] <= trace[1]["timestamp"]

    def test_unknown_trace_returns_empty(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(jd, [_make_entry(trace_id="t1")])
        reader = JournalReader(jd)
        assert reader.get_trace("nonexistent") == []


# ===========================================================================
# 3. summary()
# ===========================================================================


class TestSummary:
    def test_correct_counts(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(
            jd,
            [
                _make_entry(operation="llm_call"),
                _make_entry(operation="llm_call"),
                _make_entry(operation="lore_recall"),
                _make_entry(operation="sandbox_exec", context={"error": "timeout"}),
            ],
        )
        reader = JournalReader(jd)
        s = reader.summary()
        assert s["total"] == 4
        assert s["by_operation"]["llm_call"] == 2
        assert s["by_operation"]["lore_recall"] == 1
        assert s["by_operation"]["sandbox_exec"] == 1
        assert s["error_count"] == 1
        assert s["earliest"] is not None
        assert s["latest"] is not None

    def test_summary_with_agent_filter(self, tmp_path):
        jd = str(tmp_path)
        _seed_entries(
            jd,
            [
                _make_entry(agent_id="a1"),
                _make_entry(agent_id="a2"),
            ],
        )
        reader = JournalReader(jd)
        s = reader.summary(agent_id="a1")
        assert s["total"] == 1


# ===========================================================================
# 4. Empty journal returns empty results
# ===========================================================================


class TestEmptyJournal:
    def test_empty_dir(self, tmp_path):
        reader = JournalReader(str(tmp_path))
        assert reader.query() == []
        assert reader.get_trace("any") == []
        s = reader.summary()
        assert s["total"] == 0
        assert s["by_operation"] == {}

    def test_nonexistent_dir(self, tmp_path):
        reader = JournalReader(str(tmp_path / "does_not_exist"))
        assert reader.query() == []
        assert reader.summary()["total"] == 0


# ===========================================================================
# 5. Malformed lines are skipped gracefully
# ===========================================================================


class TestMalformedLines:
    def test_skips_bad_json(self, tmp_path):
        jd = str(tmp_path)
        os.makedirs(jd, exist_ok=True)
        path = os.path.join(jd, "journal-2026-04-05.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps(_make_entry()) + "\n")
            f.write("THIS IS NOT JSON\n")
            f.write("{bad json too\n")
            f.write(json.dumps(_make_entry()) + "\n")

        reader = JournalReader(jd)
        results = reader.query()
        assert len(results) == 2

    def test_skips_empty_lines(self, tmp_path):
        jd = str(tmp_path)
        os.makedirs(jd, exist_ok=True)
        path = os.path.join(jd, "journal-2026-04-05.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps(_make_entry()) + "\n")
            f.write("\n")
            f.write("  \n")
            f.write(json.dumps(_make_entry()) + "\n")

        reader = JournalReader(jd)
        assert len(reader.query()) == 2
