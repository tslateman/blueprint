# Plan: Fleet Dispatch via Blueprint Orchestrator

## Context

Background agents need three things: isolated compute, an event router, and
governance. Shipyard provides compute (FleetDriver trait, five runtimes) and
governance (invariants, scope controls, leases). The missing piece is the event
router — something that reacts to external stimuli and provisions fleets.

Blueprint's orchestrator already handles event-driven triggers (filesystem via
watchdog). Today every trigger runs `enforcer.generate()` — a single-agent LLM
call. This plan adds a `fleet` action type so triggers can provision Shipyard
fleets instead.

### Data Flow

```text
                     ┌─────────────────────────┐
                     │  Blueprint Orchestrator  │
                     │  (watchdog file events)  │
                     └────┬───────────────┬─────┘
                          │               │
                   action: enforcer  action: fleet
                          │               │
                          ▼               ▼
                   SchemaEnforcer    fleet_dispatch.py
                   (LLM call)        (fl CLI calls)
                                          │
                                          ▼
                                    Shipyard fleet.db
                                     (team → task → drive)
                                          │
                                          ▼
                                    outbox/ result YAML
                                          │
                                    lore capture (outcome)
```

**Trigger sources** write YAML files to a well-known inbox directory:

- External tools (CI, webhooks, cron wrappers) write directly
- `praxis emit` translates diagnostic signals into dispatch payloads

**Scope boundary**: this plan covers file-based fleet dispatch only. Webhook
listeners and timer triggers are future work that builds on this same handler
pattern.

### Participants

| Project   | Role              | Changes                                     |
| --------- | ----------------- | ------------------------------------------- |
| Blueprint | Event router      | New `fleet` action + dispatch module        |
| Shipyard  | Fleet provisioner | None (consumed via `fl` CLI)                |
| Praxis    | Signal source     | New `emit` command writes dispatch payloads |
| Lore      | Memory            | None (consumed via `lore capture`)          |

## What to Do

### 1. Relax parser validation for fleet-only specs

File: `blueprint/parser.py`

The parser requires `intent` and `output_schema`. Fleet dispatch configs use
neither — they route to Shipyard, not the LLM engine.

Add an `action` field to triggers. When every trigger in a spec has
`action: fleet`, skip `intent` and `output_schema` validation. When any trigger
has `action: enforcer` (or no action, the default), require both as today.

```python
# In SpecParser.parse_yaml, after loading:
triggers = spec.get('triggers', [])
if not isinstance(triggers, list):
    triggers = [triggers]
spec['triggers'] = triggers

actions = {t.get('action', 'enforcer') for t in triggers}
VALID_ACTIONS = {'enforcer', 'fleet'}
invalid = actions - VALID_ACTIONS
if invalid:
    raise ValueError(f"Unknown trigger action(s): {invalid}")

needs_llm = 'enforcer' in actions or not triggers
if needs_llm:
    if 'intent' not in spec:
        raise ValueError("Blueprint must define an 'intent'.")
    if 'output_schema' not in spec:
        raise ValueError("Blueprint must define an 'output_schema'.")
```

### 2. Define the fleet dispatch payload and module

Fleet trigger files are YAML dropped into the watched directory. The dispatch
module reads them and calls Shipyard's CLI.

File: `blueprint/fleet_dispatch.py` (new)

**Payload format:**

```yaml
# Example: inbox/fleet/review-pr-123.yaml
team: pr-review-123
runtime: nanobot
tasks:
  - name: review
    title: "Review PR #123 — auth refactor"
    agent_type: scout
    scope_in: ["src/auth/**"]
    done_when: ["review comments posted"]
  - name: fix
    title: "Fix issues from PR #123 review"
    agent_type: builder
    scope_in: ["src/auth/**"]
    done_when: ["tests pass", "review addressed"]
    depends_on: ["review"]
```

Required fields: `team`, `tasks`. Each task requires `name`, `title`,
`agent_type`. Optional per-task: `scope_in`, `scope_out`, `done_when`,
`depends_on` (list of task names), `description`. Optional top-level: `runtime`
(default: `local`), `work_dir` (default: cwd).

`depends_on` uses task `name` strings, not indices. Names must be unique within
a payload. The dispatcher validates references before calling any CLI commands.

**Dispatch sequence:**

```python
def dispatch_fleet(payload_path: str, outbox: str, default_runtime: str) -> dict:
    """Parse a dispatch YAML and provision a Shipyard fleet.

    Returns a result dict written to outbox.
    """
```

1. Parse and validate the YAML payload.
2. `fl team create <team>` — if this fails (team exists), continue. Teams are
   idempotent.
3. Topological sort tasks by `depends_on`.
4. `fl task create --team <team> --title <title> ...` for each task in
   topo order. Capture the `task_id` from stdout. Map `name → task_id`.
5. Rewrite `depends_on` name references to `task_id` references via
   `fl task update` (if Shipyard supports it) or by passing `--depends-on`
   at create time.
6. Drive independent tasks (no `depends_on`):
   `fl drive <task_id> --runtime <runtime>`.
7. Write result YAML to outbox.
8. Capture outcome to Lore:
   `lore capture "Fleet <team> dispatched: N tasks" --rationale "Trigger: <filename>"`.

**Dependent tasks are not driven.** Shipyard's existing lifecycle handles this:
agents that complete prerequisite tasks transition them to `ready_for_review` →
`approved` → `merged`. A human or lead agent uses `fl next --team <team>` to
find the next unblocked task and runs `fl drive` on it. Automating the
dependency-chain poll is future work (a "fleet watcher" process).

**Error handling:**

- `fl team create` failure (non-duplicate): abort, write error to outbox,
  capture failure to Lore via `lore capture --error-type FleetDispatch`.
- `fl task create` failure: abort remaining tasks, write partial result to
  outbox with which tasks succeeded and which failed.
- `fl drive` failure: record in outbox but continue driving other independent
  tasks. Shipyard records the failure in `fleet.db` via its own `record_failure`.
- All `subprocess.run` calls use `capture_output=True, text=True, timeout=30`.
  Timeout errors are treated as failures.

### 3. Add fleet handler to the orchestrator

File: `blueprint/orchestrator.py`

Add `BlueprintFleetHandler` alongside the existing `BlueprintFileSystemHandler`.
The fleet handler does not take a spec — it only needs the trigger config.

```python
class BlueprintFleetHandler(FileSystemEventHandler):
    """Watches for fleet dispatch YAML files and provisions Shipyard fleets."""

    def __init__(self, trigger_config: dict):
        self.path = trigger_config.get('path', 'inbox/fleet')
        self.extension = trigger_config.get('extension', '.yaml')
        self.outbox = trigger_config.get('outbox', 'outbox/fleet')
        self.runtime = trigger_config.get('runtime', 'local')
        os.makedirs(self.path, exist_ok=True)
        os.makedirs(self.outbox, exist_ok=True)

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(self.extension):
            return
        print(f"[FLEET] Dispatch triggered: {event.src_path}")
        result = dispatch_fleet(event.src_path, self.outbox, self.runtime)
        status = "OK" if result.get('ok') else "FAILED"
        print(f"[FLEET] {status}: team={result.get('team')}, "
              f"tasks={result.get('tasks_created', 0)}")
```

Update `BlueprintOrchestrator.start()` to route by action:

```python
for trigger in spec.get('triggers', []):
    action = trigger.get('action', 'enforcer')
    if action == 'enforcer':
        handler = BlueprintFileSystemHandler(spec, trigger)
    elif action == 'fleet':
        handler = BlueprintFleetHandler(trigger)
    self.observer.schedule(handler, handler.path, recursive=False)
    self._handlers.append(handler)
```

The unknown-action warning from step 1's validation means we never reach an
unhandled case here.

### 4. Add `praxis emit` command

Files: `praxis/src/praxis/emit.py` (new), `praxis/src/praxis/cli.py` (edit)

Praxis gains an `emit` command that writes dispatch payloads. The target
directory defaults to `BLUEPRINT_INBOX` env var, falling back to
`~/.local/share/blueprint/inbox/fleet`. This avoids hardcoding Blueprint's
repo path.

```bash
# Direct payload
praxis emit \
  --team fix-timeout \
  --task "Fix timeout handling" --agent-type builder \
  --task "Review timeout fix" --agent-type reviewer

# From triggers (transform Rule of Three signals into dispatch payloads)
praxis emit --from-triggers --threshold 5
```

The `emit` module:

```python
INBOX_DIR = Path(
    os.environ.get(
        "BLUEPRINT_INBOX",
        Path.home() / ".local/share/blueprint/inbox/fleet"
    )
)

def emit_payload(team: str, tasks: list[dict], runtime: str = "local") -> Path:
    """Write a fleet dispatch YAML to the inbox directory."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{ts}_{team}.yaml"
    path = INBOX_DIR / filename
    payload = {"team": team, "runtime": runtime, "tasks": tasks}
    path.write_text(yaml.dump(payload, default_flow_style=False))
    return path
```

`--from-triggers` calls `synthesis.triggers()`, filters to threshold, and
generates one dispatch payload per trigger. Each payload creates a single-task
team: one builder scoped to the project where the failure recurs.

### 5. Fleet dispatch config

File: `blueprints/fleet_dispatch.yaml` (new)

A dispatch-only config — no `intent` or `output_schema` needed because step 1
relaxed validation for fleet-only specs.

```yaml
triggers:
  - type: file
    path: inbox/fleet
    extension: .yaml
    action: fleet
    outbox: outbox/fleet
    runtime: local
```

To use a shared inbox across machines, point `path` at the env-configured
directory:

```bash
export BLUEPRINT_INBOX="$HOME/.local/share/blueprint/inbox/fleet"
```

And set the trigger path to match. Or use the repo-local `inbox/fleet/` for
single-machine setups.

### 6. Tests

File: `tests/test_fleet_dispatch.py` (new)

```python
# Payload validation
- valid payload parses → correct team, task names, topo order
- missing `team` → ValueError
- missing task `name` → ValueError
- duplicate task names → ValueError
- depends_on references nonexistent name → ValueError

# CLI call sequence (mock subprocess.run)
- 2 independent tasks → team create, 2x task create, 2x drive
- task B depends on A → team create, A create, B create, only A driven
- team create returns non-zero (non-duplicate) → abort, error in outbox
- drive fails for one task → other independent tasks still driven

# Orchestrator routing
- trigger with action: fleet → BlueprintFleetHandler
- trigger with action: enforcer → BlueprintFileSystemHandler
- trigger with no action → BlueprintFileSystemHandler (default)
- spec with only fleet triggers → no intent/output_schema required
- spec with mixed triggers → intent/output_schema required

# Outcome capture
- successful dispatch → lore capture called with team name and task count
- failed dispatch → lore capture called with error-type FleetDispatch
```

File: `praxis/tests/test_emit.py` (new)

```python
- emit_payload writes valid YAML to INBOX_DIR
- filename contains ISO timestamp and team name
- BLUEPRINT_INBOX env var overrides default path
- --from-triggers with no triggers above threshold → no files written
- --from-triggers with 2 triggers → 2 dispatch files
```

## What NOT to Do

- Do not import Shipyard's Rust code. Call `fl` via subprocess — CLI is the
  contract boundary.
- Do not add webhook or timer triggers. File-based triggers are sufficient.
  Webhooks and timers build on this same handler pattern later.
- Do not make Praxis a dispatcher. Praxis writes signals; Blueprint reacts.
- Do not modify Shipyard. It exposes everything needed via `fl`.
- Do not auto-drive dependent tasks. This plan provisions and drives independent
  tasks. Dependent task dispatch (polling `fl next`) is a separate concern — a
  "fleet watcher" process that deserves its own plan.
- Do not hardcode Blueprint's repo path in Praxis. Use `BLUEPRINT_INBOX` env
  var with a well-known default under `~/.local/share/`.

## Acceptance Criteria

1. A YAML file dropped in `inbox/fleet/` causes the orchestrator to call
   `fl team create`, `fl task create`, and `fl drive` in the correct sequence.
2. Existing enforcer triggers work unchanged (`action: enforcer` or absent).
3. Fleet-only specs skip `intent`/`output_schema` validation without error.
4. `depends_on` uses task name strings. Invalid references fail at validation,
   before any CLI calls.
5. `praxis emit --team X --task ...` writes a valid dispatch payload that the
   orchestrator picks up and provisions.
6. `praxis emit --from-triggers` converts Rule of Three signals into dispatch
   payloads.
7. Fleet dispatch results appear in `outbox/fleet/` with team ID, task count,
   per-task status (ok/error), and the source trigger filename.
8. Outcomes are captured to Lore: decisions on success, failures on error.
9. `fl drive` failures for one task do not prevent driving other independent
   tasks.
10. All new code has tests. `just test` passes. `make check` passes in praxis.
