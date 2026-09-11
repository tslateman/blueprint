import re
from pathlib import Path

import pytest

from blueprint.parser import SpecParser


def _readme_trigger_block() -> str:
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(triggers:\n.*?)\n```", readme, re.DOTALL)
    assert match, "README.md should contain a fenced 'triggers:' YAML example"
    return match.group(1)


def test_readme_orchestrator_trigger_example_parses(tmp_path):
    spec_yaml = (
        'intent: "test"\n'
        "output_schema:\n"
        "  a: {type: string}\n"
        f"{_readme_trigger_block()}\n"
    )
    spec_file = tmp_path / "readme_trigger.yaml"
    spec_file.write_text(spec_yaml, encoding="utf-8")

    spec = SpecParser.parse_yaml(spec_file)

    assert spec["triggers"][0]["type"] == "file"
