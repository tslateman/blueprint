"""Tests for TracingCollector: emit, span, thread safety, fail-open, ID uniqueness."""

import json
import os
import threading
from pathlib import Path

import pytest

from blueprint.tracer import TracingCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_entries(journal_dir: str) -> list[dict]:
    """Read every JSON-line entry from journal_dir."""
    entries = []
    for fname in sorted(os.listdir(journal_dir)):
        if not fname.endswith(".jsonl"):
            continue
        with open(os.path.join(journal_dir, fname)) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    return entries


# ===========================================================================
# 1. emit() writes valid JSON line
# ===========================================================================


class TestEmit:
    def test_writes_valid_json_line(self, tmp_path):
        tc = TracingCollector(str(tmp_path), agent_id="a1")
        entry_id = tc.emit("llm_call", {"provider": "anthropic"})

        entries = _read_entries(str(tmp_path))
        assert len(entries) == 1

        e = entries[0]
        assert e["id"] == entry_id
        assert e["agent_id"] == "a1"
        assert e["operation"] == "llm_call"
        assert e["context"]["provider"] == "anthropic"
        assert e["duration_ms"] is None
        assert "timestamp" in e

    def test_multiple_emits_append(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        tc.emit("llm_call", {})
        tc.emit("lore_recall", {})

        entries = _read_entries(str(tmp_path))
        assert len(entries) == 2
        assert entries[0]["operation"] == "llm_call"
        assert entries[1]["operation"] == "lore_recall"

    def test_emit_includes_trace_id_when_set(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        tid = tc.new_trace()
        tc.emit("schema_compile", {})

        entries = _read_entries(str(tmp_path))
        assert entries[0]["trace_id"] == tid

    def test_emit_without_trace_id(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        tc.emit("sandbox_exec", {})

        entries = _read_entries(str(tmp_path))
        assert "trace_id" not in entries[0]

    def test_default_agent_id(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        tc.emit("llm_call", {})
        entries = _read_entries(str(tmp_path))
        assert entries[0]["agent_id"] == "default"


# ===========================================================================
# 2. span() context manager records duration_ms
# ===========================================================================


class TestSpan:
    def test_records_duration(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        with tc.span("llm_call", {"model": "gpt-4o"}) as ctx:
            # Simulate some work
            total = sum(range(1000))
            ctx["tokens"] = 42

        entries = _read_entries(str(tmp_path))
        assert len(entries) == 1

        e = entries[0]
        assert isinstance(e["duration_ms"], int)
        assert e["duration_ms"] >= 0
        assert e["context"]["model"] == "gpt-4o"
        assert e["context"]["tokens"] == 42

    def test_span_records_error(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        with pytest.raises(ValueError):
            with tc.span("llm_call", {}) as ctx:
                raise ValueError("boom")

        entries = _read_entries(str(tmp_path))
        assert len(entries) == 1
        assert entries[0]["context"]["error"] == "boom"
        assert entries[0]["duration_ms"] is not None

    def test_span_with_trace_id(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        tid = tc.new_trace()
        with tc.span("prompt_compile", {}):
            pass

        entries = _read_entries(str(tmp_path))
        assert entries[0]["trace_id"] == tid


# ===========================================================================
# 3. Thread safety
# ===========================================================================


class TestThreadSafety:
    def test_concurrent_emits_no_corruption(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        n_threads = 10
        n_per_thread = 50
        barrier = threading.Barrier(n_threads)

        def writer(thread_id):
            barrier.wait()
            for i in range(n_per_thread):
                tc.emit("llm_call", {"thread": thread_id, "i": i})

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        entries = _read_entries(str(tmp_path))
        assert len(entries) == n_threads * n_per_thread

        # Every line must parse cleanly (no interleaved writes)
        for e in entries:
            assert "id" in e
            assert "operation" in e


# ===========================================================================
# 4. Fail-open
# ===========================================================================


class TestFailOpen:
    def test_bad_journal_path_does_not_raise(self):
        # Use a path that cannot be created (null byte on POSIX)
        tc = TracingCollector("/dev/null/impossible\x00path")
        # Must not raise
        entry_id = tc.emit("llm_call", {"test": True})
        assert isinstance(entry_id, str)

    def test_readonly_dir_does_not_raise(self, tmp_path):
        read_only = tmp_path / "readonly"
        read_only.mkdir()
        read_only.chmod(0o444)

        tc = TracingCollector(str(read_only / "journal"))
        entry_id = tc.emit("llm_call", {})
        assert isinstance(entry_id, str)

        # Restore permissions for cleanup
        read_only.chmod(0o755)


# ===========================================================================
# 5. Entry ID uniqueness
# ===========================================================================


class TestIdUniqueness:
    def test_ids_are_unique(self, tmp_path):
        tc = TracingCollector(str(tmp_path))
        ids = {tc.emit("llm_call", {"i": i}) for i in range(200)}
        assert len(ids) == 200
