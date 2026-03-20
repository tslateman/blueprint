# Default to listing available commands
default:
    @just --list

# Sync all dependencies using uv
install:
    uv sync

# Run the main demo script (compiles blueprint and runs LLM)
run:
    uv run python main.py

# Run all tests via pytest
test:
    uv run pytest tests/ -v

# Run the semantic evaluation suite via headless Gemini CLI (Default)
eval:
    USE_GEMINI_CLI=true uv run pytest tests/test_evals.py

# Run the background orchestrator based on blueprint triggers (Agent Team)
orchestrate:
    PYTHONPATH=. uv run python examples/07_meta_orchestration.py

# Run the Blueprint Guardian with periodic health checks
guard:
    PYTHONPATH=. uv run python blueprint/guardian.py

# Run a self-healing demonstration (Drift Detection -> Remediation)
heal-demo:
    PYTHONPATH=. uv run python examples/08_self_healing_demo.py

# Run the semantic evaluation suite via direct API
eval-api:
    uv run pytest tests/test_evals.py

# Remove cache files and temporary data
clean:
    rm -rf .pytest_cache
    rm -rf .eval_cache
    find . -type d -name "__pycache__" -exec rm -rf {} +
