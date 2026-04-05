"""Integration tests: compiler, enforcer, and full pipeline with tracing."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from pydantic import BaseModel, Field

from blueprint.tracer import TracingCollector
from blueprint.journal import JournalReader
from blueprint.compiler import BlueprintCompiler
from blueprint.enforcer import SchemaEnforcer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_entries(journal_dir: str) -> list[dict]:
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
# 1. Compiler + tracer emits lore_recall and schema_compile
# ===========================================================================


class TestCompilerTracing:
    def test_compile_prompt_traces_lore_recall(self, tmp_path):
        jd = str(tmp_path / "journal")
        tracer = TracingCollector(jd, agent_id="compiler-test")

        spec = {
            "intent": "Summarize documents",
            "lore_context": ["architecture decisions", "coding patterns"],
            "tools_allowed": [],
        }

        def fake_lore(query):
            return f"mock result for {query}"

        BlueprintCompiler.compile_prompt(spec, lore_resolver=fake_lore, tracer=tracer)

        entries = _read_entries(jd)
        lore_entries = [e for e in entries if e["operation"] == "lore_recall"]
        assert len(lore_entries) == 2
        assert lore_entries[0]["context"]["query"] == "architecture decisions"
        assert lore_entries[1]["context"]["query"] == "coding patterns"

    def test_compile_prompt_traces_prompt_compile(self, tmp_path):
        jd = str(tmp_path / "journal")
        tracer = TracingCollector(jd)

        spec = {
            "intent": "Summarize documents",
            "tools_allowed": [],
        }

        BlueprintCompiler.compile_prompt(spec, tracer=tracer)

        entries = _read_entries(jd)
        prompt_entries = [e for e in entries if e["operation"] == "prompt_compile"]
        assert len(prompt_entries) == 1

    def test_compile_schema_traces_schema_compile(self, tmp_path):
        jd = str(tmp_path / "journal")
        tracer = TracingCollector(jd)

        spec = {
            "output_schema": {
                "name": {"type": "string", "description": "The name"},
                "age": {"type": "integer", "description": "The age"},
            }
        }

        BlueprintCompiler.compile_schema(spec, tracer=tracer)

        entries = _read_entries(jd)
        schema_entries = [e for e in entries if e["operation"] == "schema_compile"]
        assert len(schema_entries) == 1
        assert schema_entries[0]["context"]["field_count"] == 2

    def test_no_tracer_still_works(self):
        """Backward compatibility: None tracer produces no errors."""
        spec = {
            "intent": "Test bot",
            "constraints": ["Be concise"],
        }
        prompt = BlueprintCompiler.compile_prompt(spec, tracer=None)
        assert "Test bot" in prompt


# ===========================================================================
# 2. Enforcer + tracer emits llm_call entries
# ===========================================================================


class TestEnforcerTracing:
    def test_generate_traces_llm_call(self, tmp_path):
        """Mock the LLM provider and verify the tracer records llm_call."""
        jd = str(tmp_path / "journal")
        tracer = TracingCollector(jd, agent_id="enforcer-test")

        class SimpleOutput(BaseModel):
            answer: str = Field(..., description="The answer")

        # Create a mock enforcer that simulates a successful API call
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            enforcer = SchemaEnforcer(
                provider="anthropic",
                api_key="fake-key",
                cache_dir=str(tmp_path / "cache"),
            )

        mock_result = SimpleOutput(answer="42")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_result

        # Patch the client factory to return our mock
        with patch.object(
            enforcer,
            "cache",
            MagicMock(get=MagicMock(return_value=None), set=MagicMock()),
        ):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False):
                with patch("blueprint.enforcer.instructor") as mock_instructor:
                    mock_instructor.from_anthropic.return_value = mock_client
                    result = enforcer.generate(
                        "system prompt",
                        "user prompt",
                        SimpleOutput,
                        tracer=tracer,
                    )

        assert result.answer == "42"
        entries = _read_entries(jd)
        llm_entries = [e for e in entries if e["operation"] == "llm_call"]
        assert len(llm_entries) == 1
        assert llm_entries[0]["context"]["provider"] == "anthropic"
        assert llm_entries[0]["context"]["success"] is True

    def test_generate_traces_failure(self, tmp_path):
        """When a provider fails, the tracer records success=False."""
        jd = str(tmp_path / "journal")
        tracer = TracingCollector(jd)

        class SimpleOutput(BaseModel):
            answer: str = Field(..., description="The answer")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            enforcer = SchemaEnforcer(
                provider="anthropic",
                api_key="fake-key",
                cache_dir=str(tmp_path / "cache"),
            )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")

        with patch.object(
            enforcer,
            "cache",
            MagicMock(get=MagicMock(return_value=None), set=MagicMock()),
        ):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False):
                with patch("blueprint.enforcer.instructor") as mock_instructor:
                    mock_instructor.from_anthropic.return_value = mock_client
                    with pytest.raises(RuntimeError):
                        enforcer.generate(
                            "system prompt",
                            "user prompt",
                            SimpleOutput,
                            tracer=tracer,
                        )

        entries = _read_entries(jd)
        llm_entries = [e for e in entries if e["operation"] == "llm_call"]
        assert len(llm_entries) >= 1
        assert llm_entries[0]["context"]["success"] is False


# ===========================================================================
# 3. Full pipeline: trace_id groups compile + enforce entries in journal
# ===========================================================================


class TestFullPipelineTracing:
    def test_trace_id_groups_entries(self, tmp_path):
        """A shared trace_id links compile and enforce journal entries."""
        jd = str(tmp_path / "journal")
        tracer = TracingCollector(jd, agent_id="pipeline")
        tid = tracer.new_trace()

        spec = {
            "intent": "Summarize documents",
            "output_schema": {
                "summary": {"type": "string", "description": "Summary text"},
            },
            "lore_context": ["architecture"],
            "tools_allowed": [],
        }

        def fake_lore(query):
            return "mock lore result"

        # Compile phase
        prompt = BlueprintCompiler.compile_prompt(
            spec, lore_resolver=fake_lore, tracer=tracer
        )
        model = BlueprintCompiler.compile_schema(spec, tracer=tracer)

        # Enforce phase (mocked)
        class FakeOutput(BaseModel):
            summary: str = Field(..., description="Summary text")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
            enforcer = SchemaEnforcer(
                provider="anthropic",
                api_key="fake-key",
                cache_dir=str(tmp_path / "cache"),
            )

        mock_result = FakeOutput(summary="test summary")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_result

        with patch.object(
            enforcer,
            "cache",
            MagicMock(get=MagicMock(return_value=None), set=MagicMock()),
        ):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=False):
                with patch("blueprint.enforcer.instructor") as mock_instructor:
                    mock_instructor.from_anthropic.return_value = mock_client
                    enforcer.generate(prompt, "test input", FakeOutput, tracer=tracer)

        # Verify journal contains a complete trace
        reader = JournalReader(jd)
        trace = reader.get_trace(tid)
        assert (
            len(trace) >= 3
        )  # lore_recall + prompt_compile + schema_compile + llm_call

        operations = {e["operation"] for e in trace}
        assert "lore_recall" in operations
        assert "prompt_compile" in operations
        assert "schema_compile" in operations
        assert "llm_call" in operations

        # All entries share the trace_id
        assert all(e["trace_id"] == tid for e in trace)
