# Shuru Blueprint: Background Agent Roadmap

This roadmap outlines the evolution of Shuru Blueprint into a platform for building, enforcing, and automating **Background Agents**—autonomous, event-driven AI workflows that operate invisibly within secure sandboxes.

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

- [ ] **Event-Driven Triggers**: Implement a `triggers:` spec to handle File System, Webhook, and Timer events.
- [ ] **State Persistence**: Create a `vault/persistence.py` layer to allow agents to checkpoint and resume long-running tasks.
- [ ] **Cross-Agent Hand-off**: Define a protocol for one blueprint to "spawn" or "delegate" to another specialist sub-agent.
- [ ] **Agent Registry**: A centralized service discovery for specialized blueprints (The "Agent Team").

---

## Phase 3: Total Autonomy (The Invisible Loop)
**Goal**: Achieving "Project Stability" through continuous, self-healing background processes.

- [ ] **Background Guardian**: A resident daemon that monitors system "drift" and auto-triggers remediations.
- [ ] **Self-Correcting Blueprints**: Enable agents to propose updates to their own `output_schema` as production data evolves.
- [ ] **Semantic Mutation Testing**: Automated "Red-Teaming" of agent constraints using an `LLMJudge`.
- [ ] **Human-in-the-Loop (HITL) Gates**: Asynchronous "Approval" checkpoints for high-stakes background actions.

---

## Philosophy: "Invisible AI"
1. **Zero-UI**: Agents live in the terminal and the sandbox, not in a chat window.
2. **Deterministic Output**: LLM outputs are always validated against a Pydantic contract.
3. **Safe-by-Default**: Code generation is restricted to the Shuru Vault.
4. **Context-Rich**: Every action is grounded in the project's `lore`.
