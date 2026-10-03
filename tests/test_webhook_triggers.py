"""Tests for webhook trigger parsing, handler behavior, and orchestrator routing."""

import http.client
import socket
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from blueprint.parser import SpecParser


def _write_spec(tmp_path, spec):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.dump(spec))
    return str(path)


def _enforcer_spec(**trigger_overrides):
    trigger = {
        "type": "webhook",
        "action": "enforcer",
        "path": "/hook",
        "port": 8787,
    }
    trigger.update(trigger_overrides)
    return {
        "name": "webhook-test",
        "intent": "You are a status checker.",
        "output_schema": {
            "status": {"type": "string", "description": "System status"},
        },
        "triggers": [trigger],
    }


def _fleet_spec(**trigger_overrides):
    trigger = {
        "type": "webhook",
        "action": "fleet",
        "path": "/hook",
        "port": 8787,
    }
    trigger.update(trigger_overrides)
    return {
        "name": "webhook-fleet-test",
        "triggers": [trigger],
    }


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_listening(port, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError(f"webhook listener did not open 127.0.0.1:{port}")


def _request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        if body is None:
            conn.request(method, path)
        else:
            payload = body if isinstance(body, bytes) else body.encode("utf-8")
            conn.request(method, path, body=payload)
        response = conn.getresponse()
        status = response.status
        response.read()
        return status
    finally:
        conn.close()


class TestWebhookParserValidation:
    def test_valid_enforcer_webhook(self, tmp_path):
        result = SpecParser.parse_yaml(_write_spec(tmp_path, _enforcer_spec()))
        trigger = result["triggers"][0]
        assert trigger["type"] == "webhook"
        assert trigger["path"] == "/hook"
        assert trigger["port"] == 8787

    def test_fleet_webhook_does_not_require_intent(self, tmp_path):
        result = SpecParser.parse_yaml(_write_spec(tmp_path, _fleet_spec()))
        assert result["triggers"][0]["action"] == "fleet"
        assert "intent" not in result

    def test_enforcer_webhook_still_requires_intent(self, tmp_path):
        spec = _enforcer_spec()
        del spec["intent"]
        with pytest.raises(ValueError, match="intent"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_enforcer_webhook_still_requires_output_schema(self, tmp_path):
        spec = _enforcer_spec()
        del spec["output_schema"]
        with pytest.raises(ValueError, match="output_schema"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_missing_path_raises(self, tmp_path):
        spec = _enforcer_spec()
        del spec["triggers"][0]["path"]
        with pytest.raises(ValueError, match="path"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_path_must_start_with_slash(self, tmp_path):
        spec = _enforcer_spec(path="hook")
        with pytest.raises(ValueError, match="path"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_missing_port_raises(self, tmp_path):
        spec = _enforcer_spec()
        del spec["triggers"][0]["port"]
        with pytest.raises(ValueError, match="port"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_port_zero_raises(self, tmp_path):
        spec = _enforcer_spec(port=0)
        with pytest.raises(ValueError, match="port"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_bool_port_raises(self, tmp_path):
        spec = _enforcer_spec(port=True)
        with pytest.raises(ValueError, match="port"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))

    def test_unknown_trigger_type_still_raises(self, tmp_path):
        spec = _enforcer_spec(type="socket")
        with pytest.raises(ValueError, match="Unknown trigger type"):
            SpecParser.parse_yaml(_write_spec(tmp_path, spec))


class TestWebhookHandler:
    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_schema",
        return_value=MagicMock,
    )
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_prompt",
        return_value="prompt",
    )
    def test_post_fires_enforcer_with_body(
        self, _mock_prompt, _mock_schema, mock_enforcer_cls, tmp_path
    ):
        from blueprint.orchestrator import BlueprintWebhookHandler

        mock_enforcer = MagicMock()
        mock_result = MagicMock()
        mock_result.model_dump_json.return_value = '{"status": "ok"}'
        mock_enforcer.generate.return_value = mock_result
        mock_enforcer_cls.return_value = mock_enforcer

        port = _free_port()
        outbox = tmp_path / "outbox"
        handler = BlueprintWebhookHandler(
            {
                "intent": "test",
                "output_schema": {"status": {"type": "string"}},
            },
            {
                "type": "webhook",
                "action": "enforcer",
                "path": "/hook",
                "port": port,
                "outbox": str(outbox),
            },
        )
        handler.start()
        try:
            _wait_until_listening(port)
            status = _request(port, "POST", "/hook", "Check status")
        finally:
            handler.stop()

        assert status == 204
        mock_enforcer.generate.assert_called_once()
        assert mock_enforcer.generate.call_args.args[1] == "Check status"
        results = list(outbox.glob("webhook_*_result.json"))
        assert len(results) == 1
        assert results[0].read_text() == '{"status": "ok"}'

    @patch("blueprint.orchestrator.dispatch_fleet")
    def test_post_fires_fleet_with_body_as_payload(self, mock_dispatch, tmp_path):
        from blueprint.orchestrator import BlueprintWebhookHandler

        captured = {}

        def _capture(payload_path, outbox, runtime):
            captured["body"] = Path(payload_path).read_text()
            captured["outbox"] = outbox
            captured["runtime"] = runtime
            return {"ok": True, "team": "t", "tasks_created": 1}

        mock_dispatch.side_effect = _capture
        port = _free_port()
        payload = "team: t\ntasks: []\n"
        handler = BlueprintWebhookHandler(
            {},
            {
                "type": "webhook",
                "action": "fleet",
                "path": "/hook",
                "port": port,
                "runtime": "local",
                "outbox": str(tmp_path / "outbox"),
            },
        )
        handler.start()
        try:
            _wait_until_listening(port)
            status = _request(port, "POST", "/hook", payload)
        finally:
            handler.stop()

        assert status == 204
        assert captured["body"] == payload
        assert captured["outbox"] == str(tmp_path / "outbox")
        assert captured["runtime"] == "local"

    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_schema",
        return_value=MagicMock,
    )
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_prompt",
        return_value="prompt",
    )
    def test_rejects_other_paths_methods_and_empty_body(
        self, _mock_prompt, _mock_schema, mock_enforcer_cls, tmp_path
    ):
        from blueprint.orchestrator import BlueprintWebhookHandler

        mock_enforcer_cls.return_value = MagicMock()
        port = _free_port()
        handler = BlueprintWebhookHandler(
            {"intent": "test", "output_schema": {"status": {"type": "string"}}},
            {
                "type": "webhook",
                "action": "enforcer",
                "path": "/hook",
                "port": port,
                "outbox": str(tmp_path / "outbox"),
            },
        )
        handler.start()
        try:
            _wait_until_listening(port)
            assert _request(port, "POST", "/other", "hi") == 404
            assert _request(port, "GET", "/hook") == 405
            assert _request(port, "POST", "/hook", "   ") == 400
        finally:
            handler.stop()

        mock_enforcer_cls.return_value.generate.assert_not_called()


class TestOrchestratorWebhookRouting:
    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_schema",
        return_value=MagicMock,
    )
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_prompt",
        return_value="prompt",
    )
    @patch("blueprint.orchestrator.SpecParser.parse_yaml")
    def test_webhook_trigger_creates_webhook_handler(
        self, mock_parse, _p, _s, _e, tmp_path
    ):
        from blueprint.orchestrator import (
            BlueprintOrchestrator,
            BlueprintWebhookHandler,
        )

        port = _free_port()
        spec = _enforcer_spec(port=port, outbox=str(tmp_path / "outbox"))
        mock_parse.return_value = spec

        orch = BlueprintOrchestrator([str(tmp_path / "bp.yaml")])
        try:
            orch.start()
            assert len(orch._webhooks) == 1
            assert isinstance(orch._webhooks[0], BlueprintWebhookHandler)
            assert orch._timers == []
            assert orch._handlers == []
        finally:
            orch.stop()

    @patch("blueprint.orchestrator.SchemaEnforcer")
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_schema",
        return_value=MagicMock,
    )
    @patch(
        "blueprint.orchestrator.BlueprintCompiler.compile_prompt",
        return_value="prompt",
    )
    @patch("blueprint.orchestrator.SpecParser.parse_yaml")
    def test_stop_with_webhook_only_does_not_raise(
        self, mock_parse, _p, _s, _e, tmp_path
    ):
        from blueprint.orchestrator import BlueprintOrchestrator

        port = _free_port()
        mock_parse.return_value = _enforcer_spec(
            port=port, outbox=str(tmp_path / "outbox")
        )
        orch = BlueprintOrchestrator([str(tmp_path / "bp.yaml")])
        orch.start()
        orch.stop()
