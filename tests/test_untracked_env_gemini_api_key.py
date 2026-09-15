"""Regression test for the untracked-env-gemini-api-key finding.

The repo's remote is public. `.gitignore` must ignore every `.env*`
variant, not just the literal `.env`, so a renamed copy of a real secret
(`.env.local`, `.env.bak`, ...) can't slip past a `git add` and get
published. It must also carve out `.env.example` so the documented
template stays trackable.
"""

import subprocess

import pytest

REPO_ROOT = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"],
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


@pytest.mark.parametrize(
    "candidate",
    [".env", ".env.local", ".env.bak", ".env.production"],
)
def test_env_variants_are_gitignored(candidate):
    assert _is_ignored(candidate), (
        f"{candidate} is not covered by .gitignore; a renamed copy of a "
        "real secret could be committed to the public remote"
    )


def test_env_example_is_not_gitignored():
    assert not _is_ignored(".env.example"), (
        ".env.example is a template and must stay trackable so the README "
        "instructions have something to copy"
    )


def test_no_google_api_key_in_tracked_files():
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    grep = subprocess.run(
        ["grep", "-lE", r"AIza[0-9A-Za-z_-]{35}", *tracked],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert grep.returncode != 0, (
        f"Google API key found in tracked file(s): {grep.stdout}"
    )
