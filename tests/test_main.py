import subprocess
from unittest.mock import MagicMock

import pytest

import main


def _clear_provider_env(monkeypatch):
    for key in ["OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"]:
        monkeypatch.delenv(key, raising=False)


def test_main_uses_anthropic_key(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")

    mock_enforcer_instance = MagicMock()
    mock_enforcer_instance.generate.return_value.model_dump_json.return_value = "{}"
    mock_enforcer_instance.generate.return_value.python_execution_script = None
    mock_enforcer_cls = MagicMock(return_value=mock_enforcer_instance)

    monkeypatch.setattr(main, "SchemaEnforcer", mock_enforcer_cls)

    main.main()

    mock_enforcer_cls.assert_called_once()
    mock_enforcer_instance.generate.assert_called_once()


def test_main_raises_without_any_key_or_cli(monkeypatch):
    _clear_provider_env(monkeypatch)

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "gemini":
            raise FileNotFoundError("gemini not found")
        return subprocess.run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ValueError):
        main.main()
