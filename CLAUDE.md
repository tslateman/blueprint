# Blueprint

Spec-driven LLM agent framework. Pipeline: YAML spec → parser → compiler → enforcer → evaluator.

## Quick Reference

- `just test` — run all tests
- `just eval` — run semantic evals (Gemini CLI)
- `just eval-api` — run semantic evals (direct API)
- `just orchestrate` — run the event-driven orchestrator
- `just guard` — run the guardian daemon
- `just heal-demo` — run self-healing demo

## Architecture

- `blueprint/` — core framework (parser, compiler, enforcer, evaluator, orchestrator, guardian, registry, fleet_dispatch, fleet_watcher)
- `vault/` — Shuru sandbox execution (tool_router, sandbox)
- `blueprints/` — YAML spec definitions (factory_generator, meta)
- `evals/` — golden case definitions
- `examples/` — numbered demo scripts (01-08)
- `tests/` — all test files

## Conventions

- Tests live in `tests/`, run via `just test`
- YAML specs define agent behavior — see `demo_spec.yaml` for the canonical example
- Fleet dispatch bridges to Shipyard (`fl` CLI) — see `blueprint/fleet_dispatch.py`
- Reck review runs after fleet drive for quality judgment
- Timer triggers fire actions on a recurring interval — `type: timer` with `interval` in spec triggers
- Fleet watcher polls driven tasks and drives dependents as prerequisites complete — see `blueprint/fleet_watcher.py`
- Multi-provider fallback: Gemini → OpenAI → Anthropic
- Lore integration: `lore_context` in specs triggers automatic memory hydration
- Python 3.12+, dependencies managed via `uv`

## Dependencies

- External CLIs: `fl` (Shipyard), `lore`, `shuru`
- Python: see pyproject.toml
