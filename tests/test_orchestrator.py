"""Tests for the orchestrator's fleet watcher: an exception in dispatch_fleet
must not kill the watchdog Observer thread."""

import os
import sys
import time
from pathlib import Path

import yaml
from watchdog.observers import Observer

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blueprint.orchestrator import BlueprintFleetHandler

_PAYLOAD = {
    "team": "t",
    "tasks": [{"name": "a", "title": "A", "agent_type": "builder"}],
}


def test_missing_fl_binary_does_not_kill_observer(tmp_path, monkeypatch):
    """A missing `fl` binary on PATH must not terminate the Observer thread,
    and each dropped file must still produce an error result in the outbox."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    inbox = str(tmp_path / "inbox")
    outbox = str(tmp_path / "outbox")
    handler = BlueprintFleetHandler({"path": inbox, "outbox": outbox})

    observer = Observer()
    observer.schedule(handler, inbox, recursive=False)
    observer.start()
    try:
        for i in (1, 2):
            (Path(inbox) / f"fleet{i}.yaml").write_text(yaml.dump(_PAYLOAD))
            time.sleep(1.5)
            assert observer.is_alive(), f"observer died after fleet{i}.yaml"
    finally:
        observer.stop()
        observer.join(timeout=5)

    result_files = sorted(os.listdir(outbox))
    assert len(result_files) == 2
    for fname in result_files:
        with open(os.path.join(outbox, fname)) as f:
            result = yaml.safe_load(f)
        assert result["ok"] is False
        assert result["errors"]
