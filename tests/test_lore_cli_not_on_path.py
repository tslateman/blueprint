from unittest.mock import patch, MagicMock

import blueprint.fleet_dispatch as fleet_dispatch
from vault.tool_router import ToolRouter


def test_lore_search_honors_lore_bin_env_var(monkeypatch):
    monkeypatch.setenv("LORE_BIN", "/custom/path/lore")
    router = ToolRouter()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        router.lore_search("test query")
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "/custom/path/lore"


def test_lore_record_decision_honors_lore_bin_env_var(monkeypatch):
    monkeypatch.setenv("LORE_BIN", "/custom/path/lore")
    router = ToolRouter()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        router.lore_record_decision("decision", "rationale")
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "/custom/path/lore"


def test_fleet_dispatch_lore_success_honors_lore_bin_env_var(monkeypatch):
    monkeypatch.setenv("LORE_BIN", "/custom/path/lore")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        fleet_dispatch._lore_success("team", 3, "trigger.yaml")
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "/custom/path/lore"


def test_fleet_dispatch_lore_error_honors_lore_bin_env_var(monkeypatch):
    monkeypatch.setenv("LORE_BIN", "/custom/path/lore")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        fleet_dispatch._lore_error("boom")
        called_argv = mock_run.call_args[0][0]
        assert called_argv[0] == "/custom/path/lore"
