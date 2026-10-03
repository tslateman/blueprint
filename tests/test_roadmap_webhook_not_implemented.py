"""Webhook triggers are a supported trigger type, and the roadmap says so.

The roadmap box stays checked only while the parser accepts `type: webhook`.
"""

import re
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blueprint.parser import SpecParser


def test_parser_accepts_webhook_trigger(tmp_path):
    spec = {
        "intent": "x",
        "output_schema": {"a": {"type": "string"}},
        "triggers": [{"type": "webhook", "path": "/hook", "port": 8787}],
    }
    spec_path = tmp_path / "w.yaml"
    spec_path.write_text(yaml.dump(spec))

    result = SpecParser.parse_yaml(str(spec_path))

    trigger = result["triggers"][0]
    assert trigger["type"] == "webhook"
    assert trigger["path"] == "/hook"
    assert trigger["port"] == 8787


def test_roadmap_webhook_item_is_checked_because_parser_accepts_it(tmp_path):
    """A checked webhook line is allowed only when the parser accepts one."""
    accepted = {
        "intent": "x",
        "output_schema": {"a": {"type": "string"}},
        "triggers": [{"type": "webhook", "path": "/hook", "port": 8787}],
    }
    spec_path = tmp_path / "w.yaml"
    spec_path.write_text(yaml.dump(accepted))
    SpecParser.parse_yaml(str(spec_path))

    roadmap = Path(_PROJECT_ROOT, "ROADMAP.md").read_text()
    webhook_items = [
        line
        for line in roadmap.splitlines()
        if "webhook" in line.lower() and line.lstrip().startswith("- [")
    ]
    assert webhook_items, "ROADMAP.md should list the webhook trigger item"
    checked = all(
        re.match(r"- \[x\]", line.lstrip(), re.IGNORECASE) for line in webhook_items
    )
    assert checked, (
        "ROADMAP.md leaves webhook unchecked even though the parser accepts it"
    )
