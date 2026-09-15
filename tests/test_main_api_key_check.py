"""Regression test: main() must accept ANTHROPIC_API_KEY alone, per README."""

import os
from unittest.mock import patch, MagicMock

import main


@patch("main.ToolRouter")
@patch("main.SchemaEnforcer")
@patch("main.BlueprintCompiler")
@patch("main.SpecParser")
def test_main_reaches_generate_with_only_anthropic_key(
    mock_spec_parser, mock_compiler, mock_enforcer_cls, mock_router, monkeypatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    mock_spec_parser.parse_yaml.return_value = {}
    mock_compiler.compile_prompt.return_value = "prompt"
    mock_compiler.compile_schema.return_value = MagicMock()

    mock_enforcer = mock_enforcer_cls.return_value
    result = MagicMock()
    result.model_dump_json.return_value = "{}"
    result.python_execution_script = None
    mock_enforcer.generate.return_value = result

    main.main()

    mock_enforcer.generate.assert_called_once()
