"""Regression test for the inbox partial-write race (on_created fires on an
empty file before a slow producer finishes writing it, and the file is never
reprocessed)."""

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from watchdog.observers import Observer

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


class _FakeEnforcer:
    def __init__(self, *args, **kwargs):
        pass

    def generate(self, system_prompt, user_input, model):
        result = MagicMock()
        result.model_dump_json = lambda indent=2: '{"seen": %r}' % user_input
        return result


def _write_slowly(path, delay, content):
    open(path, "w").close()
    time.sleep(delay)
    with open(path, "w") as f:
        f.write(content)


def test_slow_write_is_reprocessed_once_non_empty(tmp_path):
    with patch("blueprint.orchestrator.SchemaEnforcer", _FakeEnforcer), patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_prompt", return_value="p"
    ), patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_schema", return_value=MagicMock()
    ):
        from blueprint.orchestrator import BlueprintFileSystemHandler

        inbox = str(tmp_path / "inbox")
        outbox = str(tmp_path / "outbox")
        handler = BlueprintFileSystemHandler(
            {"intent": "x", "output_schema": {}},
            {"path": inbox, "extension": ".txt", "outbox": outbox},
        )

        observer = Observer()
        observer.schedule(handler, inbox, recursive=False)
        observer.start()
        try:
            slow_path = os.path.join(inbox, "slow.txt")
            thread = threading.Thread(
                target=_write_slowly, args=(slow_path, 0.5, "slow request")
            )
            thread.start()
            thread.join()

            deadline = time.time() + 5
            result_path = os.path.join(outbox, "slow_result.json")
            while time.time() < deadline and not os.path.exists(result_path):
                time.sleep(0.1)

            assert os.path.exists(result_path), (
                "slow_result.json was never written: the file that was empty "
                "on_created was dropped instead of being reprocessed once filled"
            )
            assert "slow request" in Path(result_path).read_text()
        finally:
            observer.stop()
            observer.join()
