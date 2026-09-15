from pathlib import Path

README = Path(__file__).parent.parent / "README.md"
ROADMAP = Path(__file__).parent.parent / "ROADMAP.md"


def test_readme_does_not_overclaim_spec_implementation_comparison():
    text = README.read_text()
    assert "mismatches between specs and implementation" not in text


def test_roadmap_does_not_overclaim_drift_monitoring():
    text = ROADMAP.read_text()
    assert '"drift"' not in text
