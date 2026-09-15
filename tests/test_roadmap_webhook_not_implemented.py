"""Regression test: ROADMAP must not claim webhook triggers work when the parser rejects them."""

import re
import sys
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blueprint.parser import SpecParser


def test_parser_rejects_webhook_trigger(tmp_path):
    spec = {
        "intent": "x",
        "output_schema": {"a": {"type": "string"}},
        "triggers": [{"type": "webhook", "path": "/hook"}],
    }
    spec_path = tmp_path / "w.yaml"
    spec_path.write_text(yaml.dump(spec))

    with pytest.raises(ValueError, match="Unknown trigger type"):
        SpecParser.parse_yaml(str(spec_path))


def test_roadmap_does_not_claim_webhook_triggers_are_done():
    roadmap = Path(_PROJECT_ROOT, "ROADMAP.md").read_text()

    checked_lines = [
        line
        for line in roadmap.splitlines()
        if re.match(r"- \[x\]", line, re.IGNORECASE)
    ]

    assert not any("webhook" in line.lower() for line in checked_lines), (
        "ROADMAP.md checks off a webhook capability the parser does not support"
    )
