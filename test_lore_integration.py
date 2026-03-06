import pytest
from unittest.mock import patch, MagicMock
from blueprint.compiler import BlueprintCompiler
from vault.tool_router import ToolRouter

def test_lore_search_tool():
    router = ToolRouter()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Mocked Lore result", stderr="")
        result = router.lore_search("test query")
        assert result == "Mocked Lore result"
        mock_run.assert_called_once_with(["lore", "recall", "test query"], capture_output=True, text=True, check=False)

def test_lore_record_decision_tool():
    router = ToolRouter()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Decision recorded", stderr="")
        result = router.lore_record_decision("New feature", "Requested by user")
        assert result == "Decision recorded"
        mock_run.assert_called_once_with(["lore", "remember", "New feature", "--rationale", "Requested by user"], capture_output=True, text=True, check=False)

def test_blueprint_compiler_lore_hydration():
    spec = {
        "intent": "Summarize decisions.",
        "tools_allowed": ["lore_search"],
        "lore_context": ["architectural decisions"]
    }
    
    with patch("vault.tool_router.ToolRouter.lore_search") as mock_search:
        mock_search.return_value = "Found 3 decisions: A, B, C."
        prompt = BlueprintCompiler.compile_prompt(spec)
        
        assert "Lore Context" in prompt
        assert "Query: architectural decisions" in prompt
        assert "Found 3 decisions: A, B, C." in prompt
        mock_search.assert_called_once_with("architectural decisions")

def test_blueprint_compiler_tools_docs():
    spec = {
        "intent": "Test tools.",
        "tools_allowed": ["lore_record_decision"]
    }
    
    prompt = BlueprintCompiler.compile_prompt(spec)
    assert "# Tools Available" in prompt
    assert "lore_record_decision" in prompt
