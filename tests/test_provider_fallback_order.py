import inspect
import re
from pathlib import Path

from blueprint.enforcer import SchemaEnforcer

REPO_ROOT = Path(__file__).parent.parent

PROVIDER_LABELS = {"anthropic": "Anthropic", "gemini": "Gemini", "openai": "OpenAI"}


def _code_fallback_order():
    source = inspect.getsource(SchemaEnforcer.generate)
    matches = re.findall(r'if os\.environ\.get\("(\w+)_API_KEY"\):', source)
    return [provider.lower() for provider in matches]


def test_claude_md_documents_actual_fallback_order():
    code_order = " → ".join(PROVIDER_LABELS[p] for p in _code_fallback_order())
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text()
    assert f"Multi-provider fallback: {code_order}" in claude_md


def test_readme_lists_primary_key_matching_fallback_order():
    code_order = _code_fallback_order()
    primary_provider = code_order[0]
    readme = (REPO_ROOT / "README.md").read_text()
    assert f"{primary_provider.upper()}_API_KEY=your_key" in readme


def test_schema_enforcer_selects_documented_primary_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.delenv("USE_GEMINI_CLI", raising=False)

    enforcer = SchemaEnforcer(cache_dir=str(tmp_path / "cache"))

    assert enforcer.provider == _code_fallback_order()[0]
