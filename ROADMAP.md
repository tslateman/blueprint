# Blueprint: Background Agent Roadmap

This roadmap outlines the evolution of Blueprint into a platform for building, enforcing, and automating **Background Agents**—autonomous, event-driven AI workflows that operate invisibly within secure sandboxes.

---

## Phase 1: Foundation (Secure Intent & Execution)

**Goal**: Build the core engine that transforms high-level intent into validated action.

- [x] **Blueprint Engine**: Dynamic Pydantic schema generation via `instructor`.
- [x] **Secure Vault**: Zero-trust code execution environment via `shuru`.
- [x] **Memory Hydration**: Automatic context injection via the `lore` CLI.
- [x] **Headless CLI Support**: Native integration with the Gemini CLI for non-interactive automation.

---

## Phase 2: Expansion (Durable State & Event Hooks)

**Goal**: Move from transient executions to long-running, event-aware agent swarms.

- [x] **Event-Driven Triggers**: Implement a `triggers:` spec to handle File System, Webhook, and Timer events.
- [x] **State Persistence**: The orchestrator and fleet dispatch checkpoint results to the outbox, enabling agents to resume from prior state.
- [x] **Cross-Agent Hand-off**: Fleet dispatch delegates to specialist sub-agents via Shipyard's `fl` CLI, with topological task ordering and dependency resolution.
- [x] **Agent Registry**: A centralized service discovery for specialized blueprints (The "Agent Team").
- [x] **Fleet Dispatch + Reck Review**: Multi-agent task execution through Shipyard with a Reck judgment layer that reviews output quality after each dispatch.
- [x] **Fleet Watcher**: Automated dependency-chain polling that drives dependent tasks as prerequisites complete, with failure cascading.

---

## Phase 3: Total Autonomy (The Invisible Loop)

**Goal**: Achieving "Project Stability" through continuous, self-healing background processes.

- [x] **Background Guardian**: A resident daemon that monitors system "drift" and auto-triggers remediations.
- [ ] **Self-Correcting Blueprints**: Enable agents to propose updates to their own `output_schema` as production data evolves.
- [x] **Self-Healing Agent**: A meta-agent that analyzes errors and applies fixes.
- [x] **Smart Fallback**: Automatic failover to the Gemini CLI if no API keys are found.

---

## Phase 4: Enterprise Frontier (The Trusted Swarm)

**Goal**: Scaling to production-ready, safe, and traceable background workflows.

- [ ] **Human-in-the-Loop (HITL) Gates**: Asynchronous "Approval" checkpoints for high-stakes background actions.
- [x] **Agent Tracing & Journaling**: Record thoughts, lore recall, and sandbox commands into a searchable audit trail (The "Black Box").
- [ ] **Cross-Agent Message Bus**: Enable agents to route their outputs as triggers for other specialists in the team.
- [ ] **Semantic Mutation Testing**: Automated "Red-Teaming" of agent constraints using an `LLMJudge`.
- [ ] **Cron Timer Expressions**: Full cron syntax support for timer triggers (currently interval-only).

---

## Philosophy: "Invisible AI"

1. **Zero-UI**: Agents live in the terminal and the sandbox, not in a chat window.
2. **Deterministic Output**: LLM outputs are always validated against a Pydantic contract.
3. **Safe-by-Default**: Code generation is restricted to the Shuru Vault.
4. **Context-Rich**: Every action is grounded in the project's `lore`.
