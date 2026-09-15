from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_lore_link_does_not_point_to_dead_domain():
    text = README.read_text()
    assert "https://lore.sh" not in text


def test_readme_lore_link_points_to_github_repo():
    text = README.read_text()
    assert "[lore](https://github.com/tslateman/lore)" in text
