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
    uv run pytest test_blueprint.py test_sandbox.py test_lore_integration.py -v

# Run the semantic evaluation suite via headless Gemini CLI (Default)
eval:
    USE_GEMINI_CLI=true uv run pytest test_evals.py

# Run the semantic evaluation suite via direct API
eval-api:
    uv run pytest test_evals.py

# Remove cache files and temporary data
clean:
    rm -rf .pytest_cache
    rm -rf .eval_cache
    find . -type d -name "__pycache__" -exec rm -rf {} +
