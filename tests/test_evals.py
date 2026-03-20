import pytest
import yaml
import os
from pathlib import Path
from dotenv import load_dotenv
from blueprint.evaluator import EvaluatorHarness

load_dotenv()

def load_cases():
    cases_path = Path("evals/golden_cases.yaml")
    if not cases_path.exists():
        return []
    with open(cases_path, "r") as f:
        return yaml.safe_load(f)

@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c['id'])
def test_blueprint_eval(case):
    use_cli = os.environ.get("USE_GEMINI_CLI", "").lower() == "true"
    
    # Skip if no API key is set AND not in CLI mode
    if not use_cli and not any(os.environ.get(k) for k in ["OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"]):
        pytest.skip("No API key found for evaluation.")
        
    harness = EvaluatorHarness(use_cli=use_cli)
    results = harness.run_case(case)
    
    # Track failures
    failures = [r for r in results if not r.passed]
    
    if failures:
        msg = "\n".join([f"- {f.reason}" for f in failures])
        pytest.fail(f"Eval Case '{case['id']}' failed with {len(failures)} assertion(s):\n{msg}")
    
    assert all(r.passed for r in results)
